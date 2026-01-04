import bpy
from . import modular_export
from . import preview_360
from . import fractal_fish
from . import outline

classes = (
    modular_export.SHIYUME_OT_ModularExport,
    preview_360.SHIYUME_OT_Preview360,
    fractal_fish.SHIYUME_OT_FractalFish,
    outline.SHIYUME_OT_Outline,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
