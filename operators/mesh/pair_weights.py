import bpy
import bmesh


def _snapshot_weights(vert, deform_layer):
    return dict(vert[deform_layer].items())


def _overwrite_weights(vert, deform_layer, weights):
    """整组覆盖：先清空再写入，保证对方没有的顶点组不会在这一侧残留。"""
    deform_weights = vert[deform_layer]
    deform_weights.clear()
    for group_index, weight in weights.items():
        deform_weights[group_index] = weight


class _PairWeightOperatorBase:
    """两点权重操作的公共骨架：编辑模式下恰好选中 2 个顶点才可用。"""
    bl_options = {'REGISTER', 'UNDO'}

    # 子类置 True 时必须能从选择历史里读出先后顺序，否则拒绝执行
    requires_selection_order = False

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH' or obj.mode != 'EDIT':
            return False
        return obj.data.total_vert_sel == 2

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)

        deform_layer = bm.verts.layers.deform.active
        if deform_layer is None:
            self.report({'WARNING'}, "网格上没有任何顶点组权重")
            return {'CANCELLED'}

        # 选择历史按点选先后排列：[0] 先选、[1] 后选（即激活点）
        history = []
        for element in bm.select_history:
            if isinstance(element, bmesh.types.BMVert) and element.select and element not in history:
                history.append(element)

        if len(history) == 2:
            first, second = history
        elif self.requires_selection_order:
            self.report({'ERROR'}, "分不清先后：请先单击源顶点，再单击目标顶点（框选不记录顺序）")
            return {'CANCELLED'}
        else:
            selected = [vert for vert in bm.verts if vert.select]
            if len(selected) != 2:
                self.report({'ERROR'}, f"需要恰好选中 2 个顶点，当前 {len(selected)} 个")
                return {'CANCELLED'}
            first, second = selected

        self.transfer_weights(first, second, deform_layer)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        return {'FINISHED'}


class SHIYUME_OT_SwapVertexWeights(_PairWeightOperatorBase, bpy.types.Operator):
    """交换两点权重：把选中的两个顶点的全部顶点组权重整组互换，
    只有一侧存在的顶点组也跟着换到另一侧。
    只在编辑模式下恰好选中 2 个顶点时可用；与点选先后无关。"""
    bl_idname = "shiyume.swap_vertex_weights"
    bl_label = "交换两点权重"

    def transfer_weights(self, first, second, deform_layer):
        first_weights = _snapshot_weights(first, deform_layer)
        second_weights = _snapshot_weights(second, deform_layer)
        _overwrite_weights(first, deform_layer, second_weights)
        _overwrite_weights(second, deform_layer, first_weights)


class SHIYUME_OT_CopyVertexWeights(_PairWeightOperatorBase, bpy.types.Operator):
    """复制两点权重：先点选的顶点为源、后点选的顶点为目标，
    把源的全部顶点组权重整组覆盖到目标，使两点权重完全一致
    （源没有的顶点组会从目标上移除）。
    只在编辑模式下恰好选中 2 个顶点、且能分辨点选先后时可用。"""
    bl_idname = "shiyume.copy_vertex_weights"
    bl_label = "复制两点权重(源→目标)"

    requires_selection_order = True

    def transfer_weights(self, source, target, deform_layer):
        _overwrite_weights(target, deform_layer, _snapshot_weights(source, deform_layer))
