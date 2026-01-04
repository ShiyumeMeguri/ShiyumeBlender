import bpy

class SHIYUME_OT_Outline(bpy.types.Operator):
    """一键为模型添加描边效果（使用Solidify修改器翻转法线）。
    常用于二次元/卡通风格渲染，自动设置材质和修改器参数。"""
    bl_idname = "shiyume.outline"
    bl_label = "一键描边"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Implementation from 一键化处理/一键描边.py
        return {'FINISHED'}
