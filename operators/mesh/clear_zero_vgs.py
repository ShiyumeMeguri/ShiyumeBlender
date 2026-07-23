import bpy


class SHIYUME_OT_ClearZeroVertexGroups(bpy.types.Operator):
    """清除空顶点组：移除所有'最大权重 <= 0'的顶点组（即根本没有顶点引用，或所有引用权重都为 0）。
    与 '清理无效顶点组' 不同：那个按骨骼名筛，这个按是否有有效权重筛。"""
    bl_idname = "shiyume.clear_zero_vgs"
    bl_label = "清除空顶点组"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.active_object

        gid_to_maxw = {}
        for g in obj.vertex_groups:
            gid_to_maxw[g.index] = 0

        for v in obj.data.vertices:
            for g in v.groups:
                gid = g.group
                w = obj.vertex_groups[gid].weight(v.index)
                if gid_to_maxw.get(gid) is None or w > gid_to_maxw[gid]:
                    gid_to_maxw[gid] = w

        wait_to_del_gids = []
        for gid, maxw in gid_to_maxw.items():
            if maxw <= 0:
                wait_to_del_gids.append(gid)

        wait_to_del_gids = sorted(wait_to_del_gids)[::-1]

        for gid in wait_to_del_gids:
            obj.vertex_groups.remove(obj.vertex_groups[gid])

        self.report({'INFO'}, f"删除了 {len(wait_to_del_gids)} 个空顶点组")
        return {'FINISHED'}
