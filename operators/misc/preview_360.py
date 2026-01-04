import bpy

class SHIYUME_OT_Preview360(bpy.types.Operator):
    """为选中的或所有的根对象生成360度旋转的预览图。
    主要用于资产库的缩略图生成，自动设置相机和灯光并渲染。"""
    bl_idname = "shiyume.preview_360"
    bl_label = "生成360预览图"
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Implementation from 一键化处理/生成360度预览图.py
        return {'FINISHED'}
