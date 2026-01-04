import bpy
import bmesh

class SHIYUME_OT_WeightPrune(bpy.types.Operator):
    """修剪顶点权重，通过移除权重最小的骨骼影响，限制每个顶点受到的最大骨骼影响数。
    通常用于优化游戏性能（大多数游戏引擎限制每个顶点受4根骨骼影响）。"""
    bl_idname = "shiyume.weight_prune"
    bl_label = "修剪权重 (Max 4)"
    bl_options = {'REGISTER', 'UNDO'}

    max_groups: bpy.props.IntProperty(name="最大组数", default=4, description="每个顶点保留的最大骨骼权重数量")
    min_weight: bpy.props.FloatProperty(name="最小权重", default=0.01, description="低于此值的权重将被忽略")

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}
            
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        
        dvert_layer = bm.verts.layers.deform.active
        if not dvert_layer:
            self.report({'ERROR'}, "No vertex groups found")
            bm.free()
            return {'CANCELLED'}
            
        for v in bm.verts:
            dvert = v[dvert_layer]
            if len(dvert) <= self.max_groups:
                continue
                
            # Get weights and sort
            weights = sorted(dvert.items(), key=lambda x: x[1], reverse=True)
            
            # Prune
            to_remove = weights[self.max_groups:]
            for group_idx, _ in to_remove:
                del dvert[group_idx]
                
            # Normalize
            total = sum(dvert.values())
            if total > 0:
                for group_idx in dvert.keys():
                    dvert[group_idx] /= total
                    
        bm.to_mesh(mesh)
        bm.free()
        
        self.report({'INFO'}, f"Pruned weights for {obj.name}")
        return {'FINISHED'}
