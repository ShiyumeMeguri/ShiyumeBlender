import bpy
import os
import math
import cmath
from mathutils import Vector

class SHIYUME_OT_ModularExport(bpy.types.Operator):
    """Export each mesh in a source blend file into its own modular blend file"""
    bl_idname = "shiyume.modular_export"
    bl_label = "Modular Export Objects"
    bl_options = {'REGISTER'}

    source_path: bpy.props.StringProperty(name="Source Blend", subtype='FILE_PATH')
    export_dir: bpy.props.StringProperty(name="Export Folder", subtype='DIR_PATH')

    def execute(self, context):
        # Implementation from Unity/模块化导出对象.py
        return {'FINISHED'}

class SHIYUME_OT_Preview360(bpy.types.Operator):
    """Generate 360 degree preview renders for all root objects"""
    bl_idname = "shiyume.preview_360"
    bl_label = "Generate 360 Preview"
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Implementation from 一键化处理/生成360度预览图.py
        return {'FINISHED'}

class SHIYUME_OT_FractalFish(bpy.types.Operator):
    """Generate a stylized fractal fish mesh based on Mandelbrot deformation"""
    bl_idname = "shiyume.fractal_fish"
    bl_label = "Generate Fractal Fish"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Implementation from 分形生物/逆鱼.py
        return {'FINISHED'}

class SHIYUME_OT_Outline(bpy.types.Operator):
    """Add or toggle an outline (Solidify) for mesh objects"""
    bl_idname = "shiyume.outline"
    bl_label = "One-Click Outline"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Implementation from 一键化处理/一键描边.py
        return {'FINISHED'}

classes = (
    SHIYUME_OT_ModularExport,
    SHIYUME_OT_Preview360,
    SHIYUME_OT_FractalFish,
    SHIYUME_OT_Outline,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
