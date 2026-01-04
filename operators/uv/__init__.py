import bpy
from . import pack_lock
from . import render_texture
from . import sync_shapekey
from . import mesh_to_uv

classes = (
    pack_lock.SHIYUME_OT_UVPackLockGroup,
    render_texture.SHIYUME_OT_UVRenderTexture,
    sync_shapekey.SHIYUME_OT_MeshUVSync,
    mesh_to_uv.SHIYUME_OT_MeshToUV,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
