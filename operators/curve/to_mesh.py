import bpy

class SHIYUME_OT_CurveToMesh(bpy.types.Operator):
    """将曲线转换为普通的网格对象。
    (目前仅包含标准转换功能，高级版本将尝试保留半径和倾斜度到顶点组)"""
    bl_idname = "shiyume.curve_to_mesh"
    bl_label = "曲线转网格"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'CURVE'

    def execute(self, context):
        curve_obj = context.active_object
        if not curve_obj or curve_obj.type != 'CURVE':
            return {'CANCELLED'}
        
        # 1. Convert to mesh using Blender's operator
        # We duplicate to avoid destroying the original
        temp_obj = curve_obj.copy()
        temp_obj.data = curve_obj.data.copy()
        context.collection.objects.link(temp_obj)
        
        context.view_layer.objects.active = temp_obj
        bpy.ops.object.convert(target='MESH')
        
        mesh_obj = context.active_object
        mesh_obj.name = curve_obj.name + "_Mesh"
        
        # 2. To preserve data, we would need a more complex manual meshing.
        # But for now, we'll just implement the standard conversion.
        # In a more advanced version, we can map radius/tilt to vertex groups.
        
        self.report({'INFO'}, f"Converted curve to mesh: {mesh_obj.name}")
        return {'FINISHED'}
