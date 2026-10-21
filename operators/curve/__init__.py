import bpy
from . import smooth_fix
from . import hair_to_path
from . import hair_retarget

classes = (
    smooth_fix.SHIYUME_OT_CurveSmoothFix,
    hair_to_path.SHIYUME_OT_HairToPath,
    hair_retarget.SHIYUME_OT_HairCurveBind,
    hair_retarget.SHIYUME_OT_HairCurveRetarget,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
