import bpy
import bmesh


class SHIYUME_OT_WeightPrune(bpy.types.Operator):
    """修剪顶点权重：先移除小于最小权重的影响，再按最大组数限制。
    通常用于优化游戏性能（大多数游戏引擎限制每个顶点受4根骨骼影响）。
    支持 '仅选中顶点' 模式（编辑模式下选中的顶点）。
    若启用 '仅骨骼顶点组'（且对象父级为骨架），会只处理与骨骼同名的顶点组。"""
    bl_idname = "shiyume.weight_prune"
    bl_label = "修剪权重 (Max 4)"
    bl_options = {'REGISTER', 'UNDO'}

    max_groups: bpy.props.IntProperty(name="最大组数", default=4, min=1, description="每个顶点保留的最大骨骼权重数量")
    min_weight: bpy.props.FloatProperty(name="最小权重", default=0.01, min=0.0, max=1.0, description="低于此值的权重将被忽略")
    selected_only: bpy.props.BoolProperty(name="仅选中顶点", default=False, description="开启时仅修剪在编辑模式下选中的顶点")
    bone_only: bpy.props.BoolProperty(name="仅骨骼顶点组", default=False, description="开启时只处理与父级骨架同名的顶点组")

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}

        if self.selected_only:
            return self._execute_selected(obj)
        else:
            return self._execute_all(obj)

    def _execute_all(self, obj):
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        dvert_layer = bm.verts.layers.deform.active
        if not dvert_layer:
            self.report({'ERROR'}, "No vertex groups found")
            bm.free()
            return {'CANCELLED'}

        bone_names = set()
        if self.bone_only and obj.parent and obj.parent.type == 'ARMATURE':
            bone_names = set(b.name for b in obj.parent.data.bones)

        for v in bm.verts:
            dvert = v[dvert_layer]

            if self.bone_only and bone_names:
                effective_items = [(gi, w) for gi, w in dvert.items() if obj.vertex_groups[gi].name in bone_names]
            else:
                effective_items = list(dvert.items())

            for gi, w in effective_items:
                if w < self.min_weight:
                    del dvert[gi]

            if self.bone_only and bone_names:
                effective_items = [(gi, w) for gi, w in dvert.items() if obj.vertex_groups[gi].name in bone_names]
            else:
                effective_items = list(dvert.items())

            if len(effective_items) > self.max_groups:
                effective_items.sort(key=lambda x: x[1], reverse=True)
                to_remove = effective_items[self.max_groups:]
                for group_idx, _ in to_remove:
                    del dvert[group_idx]

            total = sum(dvert.values())
            if total > 0:
                for group_idx in dvert.keys():
                    dvert[group_idx] /= total

        bm.to_mesh(mesh)
        bm.free()

        self.report({'INFO'}, f"Pruned weights for {obj.name}")
        return {'FINISHED'}

    def _execute_selected(self, obj):
        original_mode = obj.mode

        if original_mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        bm = bmesh.from_edit_mesh(obj.data)
        selected_verts_indices = [v.index for v in bm.verts if v.select]

        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')

        if not selected_verts_indices:
            self.report({'WARNING'}, "没有选择任何顶点。请在编辑模式下选择顶点后再运行。")
            bpy.ops.object.mode_set(mode=original_mode)
            return {'CANCELLED'}

        bone_names = set()
        if self.bone_only and obj.parent and obj.parent.type == 'ARMATURE':
            bone_names = set(b.name for b in obj.parent.data.bones)

        verts_processed = 0
        for v_index in selected_verts_indices:
            v = obj.data.vertices[v_index]

            if self.bone_only and bone_names:
                group_weights = [(g.group, g.weight) for g in v.groups if obj.vertex_groups[g.group].name in bone_names]
            else:
                group_weights = [(g.group, g.weight) for g in v.groups]

            groups_to_remove_low_weight = [gw[0] for gw in group_weights if gw[1] < self.min_weight]
            for group_index in groups_to_remove_low_weight:
                obj.vertex_groups[group_index].remove([v.index])

            if self.bone_only and bone_names:
                group_weights = [(g.group, g.weight) for g in v.groups if obj.vertex_groups[g.group].name in bone_names]
            else:
                group_weights = [(g.group, g.weight) for g in v.groups]

            if len(group_weights) > self.max_groups:
                group_weights.sort(key=lambda x: x[1])
                num_to_remove = len(group_weights) - self.max_groups
                for i in range(num_to_remove):
                    group_to_remove = group_weights[i]
                    obj.vertex_groups[group_to_remove[0]].remove([v.index])

            verts_processed += 1

        obj.data.update()
        bpy.ops.object.mode_set(mode=original_mode)

        self.report({'INFO'}, f"已修剪 {verts_processed} 个顶点的权重")
        return {'FINISHED'}
