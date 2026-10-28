import bpy
from . import normal_expansion
from . import normal_map_to_mesh
from . import mesh_to_normal_map
from . import vertex_color_rgba
from . import endfield_highlight
from . import endfield_outline
from . import endfield_target
from . import hair_procedural

classes = (
    normal_expansion.SHIYUME_OT_NormalExpansion,
    normal_map_to_mesh.SHIYUME_OT_NormalMapToMesh,
    mesh_to_normal_map.SHIYUME_OT_MeshToNormalMap,
    vertex_color_rgba.SHIYUME_OT_VertexColorRGBA,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    endfield_target.register()
    hair_procedural.register()
    endfield_highlight.register()
    endfield_outline.register()

def unregister():
    endfield_outline.unregister()
    endfield_highlight.unregister()
    hair_procedural.unregister()
    endfield_target.unregister()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
