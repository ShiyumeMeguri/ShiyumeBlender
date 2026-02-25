import bpy
from . import pack_lock
from . import sync_shapekey
from . import mesh_to_uv
from . import smart_uv_redirect
from . import island_arrange

classes = (
    pack_lock.SHIYUME_OT_UVPackLockGroup,
    sync_shapekey.SHIYUME_OT_MeshUVSync,
    mesh_to_uv.SHIYUME_OT_MeshToUV,
    smart_uv_redirect.SHIYUME_OT_PrepareUVCopy,
    smart_uv_redirect.SHIYUME_OT_SmartUVRedirect,
    island_arrange.SHIYUME_OT_UVIslandEquidistant,
    island_arrange.SHIYUME_OT_UVIslandSortByHeight,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
