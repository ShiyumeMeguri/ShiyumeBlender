import bpy
import math

class SHIYUME_OT_AABBSelect(bpy.types.Operator):
    """根据物体的AABB（包围盒）大小进行选择。
    用于快速筛选出场景中很小（如碎片）或很大（如地形）的物体。"""
    bl_idname = "shiyume.aabb_select"
    bl_label = "按尺寸选择"
    bl_options = {'REGISTER', 'UNDO'}

    threshold: bpy.props.FloatProperty(name="尺寸阈值 (米)", default=1.0, description="选择对角线长度小于此值的物体")

    def execute(self, context):
        for obj in context.scene.objects:
            dim = obj.dimensions
            length = math.sqrt(dim.x**2 + dim.y**2 + dim.z**2)
            obj.select_set(length < self.threshold)
        return {'FINISHED'}
