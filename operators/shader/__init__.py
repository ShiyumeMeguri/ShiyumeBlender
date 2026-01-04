import bpy
from . import viewport_render
from . import normal_expansion
from . import vertex_color_rgba
from . import batch_bake

classes = (
    viewport_render.SHIYUME_OT_RenderViewportAsTexture,
    normal_expansion.SHIYUME_OT_NormalExpansion,
    vertex_color_rgba.SHIYUME_OT_VertexColorRGBA,
    batch_bake.SHIYUME_OT_BatchBakeTextures,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
