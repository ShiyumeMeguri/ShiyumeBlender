import bpy
from . import viewport_simple
from . import normal_expansion
from . import normal_map_to_mesh
from . import mesh_to_normal_map
from . import vertex_color_rgba
from . import batch_bake

classes = (
    viewport_simple.SHIYUME_OT_ViewportSimpleRender,
    normal_expansion.SHIYUME_OT_NormalExpansion,
    normal_map_to_mesh.SHIYUME_OT_NormalMapToMesh,
    mesh_to_normal_map.SHIYUME_OT_MeshToNormalMap,
    vertex_color_rgba.SHIYUME_OT_VertexColorRGBA,
    batch_bake.SHIYUME_OT_BatchBakeTextures,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
