import bpy

class SHIYUME_OT_CurveSmoothFix(bpy.types.Operator):
    """修复曲线的平滑度问题。
    将曲线类型转换为 NURBS，并启用 Endpoint U，使曲线在端点处正确贴合控制点。
    适用于从其他软件导入的曲线（如HairStrands）显示不平滑的情况。"""
    bl_idname = "shiyume.curve_smooth_fix"
    bl_label = "曲线平滑修复"
    bl_options = {'REGISTER', 'UNDO'}

    order: bpy.props.IntProperty(name="NURBS阶数", default=5, description="NURBS曲线的阶数，越高越平滑")

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'CURVE'

    def execute(self, context):
        obj = context.object
        for spline in obj.data.splines:
            if spline.type != 'NURBS': spline.type = 'NURBS'
            spline.use_endpoint_u = True
            spline.order_u = min(len(spline.points), self.order)
        obj.update_tag()
        return {'FINISHED'}
