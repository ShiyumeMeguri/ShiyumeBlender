import bmesh
import bpy

from . import hair_strip_unwrap


ROOT_RULES = [
    ("Z_HIGH", "发根在上", "世界空间里较高的一端是发根（头发从头顶垂下）"),
    ("Z_LOW", "发根在下", "世界空间里较低的一端是发根"),
    ("RING", "曲线方向", "按「头发网格绑定到曲线」记下的沿线位置，曲线起点一端是发根"),
]

RING_ATTRIBUTE = "shiyume_hair_ring"


class SHIYUME_OT_HairUVUnwrap(bpy.types.Operator):
    """修复头发展开：把目标 UV 层里每个孤岛（一列或多列四边形的头发长条）重新按真实长度展成不拉伸的长条，
    发根朝上，所有孤岛使用同一把真实长度的尺子，再统一等比缩放使最大的一条占满 0-1，每个孤岛左上角对齐 (0, 1)。
    等价于「展开 → 孤岛大小平均化 → UVToolkit 对齐左上角 → 归一化等比缩放占满」一键完成，
    之后在这层 UV 上做 UV 切割，并排的头发同一高度的切线对应同样的真实长度，不会错位。
    孤岛划分沿用目标 UV 层现有的孤岛；编辑模式下只处理选中面所在的孤岛；不是规则长条的孤岛会被跳过并在汇报里列出。"""
    bl_idname = "shiyume.hair_uv_unwrap"
    bl_label = "修复头发展开"
    bl_options = {'REGISTER', 'UNDO'}

    uv_layer_name: bpy.props.StringProperty(
        name="目标 UV 层", default="UVMap.001",
        description="被重写的 UV 层，其现有孤岛即头发长条的划分；不存在时按活动 UV 层复制一份")
    root_rule: bpy.props.EnumProperty(
        name="发根", items=ROOT_RULES, default="Z_HIGH",
        description="判定哪一端是发根（展开后在 V = 1 的上方）")

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
        bm.faces.ensure_lookup_table()

        key_of_vertex = self._vertex_key(obj, bm)
        if key_of_vertex is None:
            self.report({'ERROR'}, "网格没有「头发网格绑定到曲线」记下的沿线位置，先绑定，或改用按高度判定发根")
            return self._finish(bm, mesh, in_edit_mode, False, {'CANCELLED'})

        uv_layer = bm.loops.layers.uv.get(self.uv_layer_name)
        if uv_layer is None:
            source = bm.loops.layers.uv.active
            if source is None:
                self.report({'ERROR'}, "网格没有 UV 层")
                return self._finish(bm, mesh, in_edit_mode, False, {'CANCELLED'})
            uv_layer = bm.loops.layers.uv.new(self.uv_layer_name)
            for face in bm.faces:
                for loop in face.loops:
                    loop[uv_layer].uv = loop[source].uv

        count, skipped, scale = hair_strip_unwrap.unwrap(
            bm, uv_layer, key_of_vertex, in_edit_mode, context.tool_settings)
        if count == 0:
            reasons = "；".join("%s（%d 个面）" % item for item in skipped[:3])
            self.report({'ERROR'}, "没有可展开的孤岛。" + reasons)
            return self._finish(bm, mesh, in_edit_mode, False, {'CANCELLED'})

        if skipped:
            self.report({'WARNING'}, "展开了 %d 个孤岛，跳过 %d 个：%s" % (
                count, len(skipped), "；".join("%s（%d 个面）" % item for item in skipped[:3])))
        else:
            self.report({'INFO'}, "展开了 %d 个孤岛，统一缩放 %.4f，发根朝上、左上角对齐" % (count, scale))
        return self._finish(bm, mesh, in_edit_mode, True, {'FINISHED'})

    def _vertex_key(self, obj, bm):
        if self.root_rule == "RING":
            layer = bm.verts.layers.float.get(RING_ATTRIBUTE)
            if layer is None:
                return None
            return lambda vertex: vertex[layer]
        matrix = obj.matrix_world
        sign = -1.0 if self.root_rule == "Z_HIGH" else 1.0
        return lambda vertex: sign * (matrix @ vertex.co).z

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
