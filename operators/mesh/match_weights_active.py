import bpy
import bmesh


class SHIYUME_OT_MatchWeightsActive(bpy.types.Operator):
    """权重匹配激活点：把当前编辑模式下激活顶点的所有顶点组权重，
    复制到其他选中顶点；并删除选中顶点上激活点没有的顶点组。
    用于快速统一一组顶点的权重设置。"""
    bl_idname = "shiyume.match_weights_active"
    bl_label = "权重匹配激活点"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        original_mode = context.object.mode

        obj = context.object
        if original_mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        bm = bmesh.from_edit_mesh(obj.data)
        deform_layer = bm.verts.layers.deform.active

        if deform_layer is None:
            self.report({'WARNING'}, "No vertex groups found.")
            bpy.ops.object.mode_set(mode=original_mode)
            return {'CANCELLED'}

        active_vert = bm.select_history.active if isinstance(bm.select_history.active, bmesh.types.BMVert) else None

        if active_vert:
            active_weights = {group: weight for group, weight in active_vert[deform_layer].items()}

            for vert in bm.verts:
                if vert.select and vert != active_vert:
                    vert_groups = {group: weight for group, weight in vert[deform_layer].items()}
                    groups_to_remove = [group for group in vert_groups if group not in active_weights]
                    for group in groups_to_remove:
                        del vert[deform_layer][group]

                    for group, weight in active_weights.items():
                        vert[deform_layer][group] = weight

            bmesh.update_edit_mesh(obj.data)

        bpy.ops.object.mode_set(mode=original_mode)

        return {'FINISHED'}
