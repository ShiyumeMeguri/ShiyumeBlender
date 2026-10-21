import bmesh
import bpy

from . import uv_relax_locked


COLUMN_MODES = [
    ("EVEN", "均匀居中", "各列等分矩形宽度，中间列正好居中，首尾收拢的点也完全居中"),
    ("SHAPE", "按头发形状", "各列取 3D 里各排宽度比例的加权平均位置，更贴近头发的左右不对称"),
]


class SHIYUME_OT_UVRelaxLocked(bpy.types.Operator):
    """锁边修复 UV 拉伸：孤岛是矩形，外轮廓（四个角和四条边）一点不动，里面重新排成规整的网格。
    每一排所有顶点落在同一个 V 上（横向严格水平对齐），V 按沿头发的真实弧长占比分布，纵向没有拉伸；
    两侧的顶点只沿矩形左右边上下滑动。每一列所有顶点落在同一个 U 上（纵向垂直对齐），
    首尾收拢成一点的几排也按同样的列位置排，完全居中。展开方向沿用孤岛现有的朝向，贴图不会被翻转。
    只支持头发长条那种规则四边形网格；编辑模式下只处理选中面所在的孤岛，其他模式处理整个网格。"""
    bl_idname = "shiyume.uv_relax_locked"
    bl_label = "锁边修复 UV 拉伸"
    bl_options = {'REGISTER', 'UNDO'}

    uv_layer_name: bpy.props.StringProperty(
        name="UV 层", default="UVMap", description="要修复的 UV 层，其矩形孤岛的轮廓保持不动")
    column_mode: bpy.props.EnumProperty(name="列位置", items=COLUMN_MODES, default="EVEN")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        in_edit_mode = obj.mode == 'EDIT'

        if in_edit_mode:
            bm = bmesh.from_edit_mesh(mesh)
        else:
            bm = bmesh.new()
            bm.from_mesh(mesh)
        bm.verts.index_update()
        bm.faces.ensure_lookup_table()

        uv_layer = bm.loops.layers.uv.get(self.uv_layer_name)
        if uv_layer is None:
            self.report({'ERROR'}, "没有名为 %s 的 UV 层" % self.uv_layer_name)
            return self._finish(bm, mesh, in_edit_mode, False, {'CANCELLED'})

        done, skipped = uv_relax_locked.regrid(bm, uv_layer, self.column_mode, in_edit_mode, context.tool_settings)
        if done == 0:
            reasons = "；".join("%s（%d 个面）" % item for item in skipped[:3])
            self.report({'WARNING'}, "没有可修复的孤岛。" + reasons)
            return self._finish(bm, mesh, in_edit_mode, False, {'CANCELLED'})

        message = "重排了 %d 个孤岛" % done
        if skipped:
            message += "；跳过 %d 个：%s" % (len(skipped), "；".join("%s（%d 个面）" % item for item in skipped[:3]))
            self.report({'WARNING'}, message)
        else:
            self.report({'INFO'}, message)
        return self._finish(bm, mesh, in_edit_mode, True, {'FINISHED'})

    @staticmethod
    def _finish(bm, mesh, in_edit_mode, changed, result):
        if in_edit_mode:
            if changed:
                bmesh.update_edit_mesh(mesh)
        else:
            if changed:
                bm.to_mesh(mesh)
            bm.free()
        return result
