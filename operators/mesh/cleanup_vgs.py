import bpy

class SHIYUME_OT_CleanupVertexGroups(bpy.types.Operator):
    """清理那些不在骨架中的顶点组。
    (保留 Alpha, Red, Blue, Green 等特殊用途的顶点组)。
    用于在绑定后清理垃圾数据，减小文件体积并避免混淆。"""
    bl_idname = "shiyume.cleanup_vgs"
    bl_label = "清理无效顶点组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH': return {'CANCELLED'}
        
        arm = obj.find_armature()
        if not arm: return {'CANCELLED'}
        
        bone_names = set(b.name for b in arm.data.bones)
        safe_list = {'Alpha', 'Red', 'Blue', 'Green'}
        
        to_remove = [g.index for g in obj.vertex_groups if g.name not in bone_names and g.name not in safe_list]
        for idx in reversed(to_remove):
            obj.vertex_groups.remove(obj.vertex_groups[idx])
            
        return {'FINISHED'}
