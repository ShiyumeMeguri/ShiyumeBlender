import bpy
from . import smooth_fix
from . import to_mesh
from . import from_mesh
from . import hair_to_path

classes = (
    smooth_fix.SHIYUME_OT_CurveSmoothFix,
    to_mesh.SHIYUME_OT_CurveToMesh,
    from_mesh.SHIYUME_OT_MeshToCurve,
    hair_to_path.SHIYUME_OT_HairToPath,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
