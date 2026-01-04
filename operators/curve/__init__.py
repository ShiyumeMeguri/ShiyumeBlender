import bpy
from . import smooth_fix
from . import to_mesh
from . import from_mesh

classes = (
    smooth_fix.SHIYUME_OT_CurveSmoothFix,
    to_mesh.SHIYUME_OT_CurveToMesh,
    from_mesh.SHIYUME_OT_MeshToCurve,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
