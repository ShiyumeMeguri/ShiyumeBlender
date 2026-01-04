import bpy

class SHIYUME_OT_ModularExport(bpy.types.Operator):
    """将源Blend文件中的每个Mesh对象导出为单独的模块化Blend文件。
    通常用于将一个包含多个组件的大文件拆分为多个小文件，便于游戏引擎导入或模块化管理。"""
    bl_idname = "shiyume.modular_export"
    bl_label = "模块化导出 (分开保存)"
    bl_options = {'REGISTER'}

    source_path: bpy.props.StringProperty(name="源文件路径", subtype='FILE_PATH')
    export_dir: bpy.props.StringProperty(name="导出文件夹", subtype='DIR_PATH')

    def execute(self, context):
        # Implementation from Unity/模块化导出对象.py
        return {'FINISHED'}
