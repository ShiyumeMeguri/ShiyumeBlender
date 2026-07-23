import bpy
from . import pack_lock
from . import sync_shapekey
from . import mesh_to_uv
from . import smart_uv_redirect
from . import island_arrange
from . import uv_render_rt
from . import mesh_uv_sync_live

classes = (
    pack_lock.SHIYUME_OT_UVPackLockGroup,
    sync_shapekey.SHIYUME_OT_MeshUVSync,
    mesh_to_uv.SHIYUME_OT_MeshToUV,
    smart_uv_redirect.SHIYUME_OT_PrepareUVCopy,
    smart_uv_redirect.SHIYUME_OT_SmartUVRedirect,
    island_arrange.SHIYUME_OT_UVIslandEquidistant,
    island_arrange.SHIYUME_OT_UVIslandSortByHeight,
    uv_render_rt.SHIYUME_OT_UVRenderRT,
    mesh_uv_sync_live.SHIYUME_OT_MeshUVSyncLive,
    mesh_uv_sync_live.SHIYUME_OT_MeshUVSyncLiveDisable,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    # ensure live UV handler is removed when unregistering
    try:
        mesh_uv_sync_live.unregister_handler()
    except Exception:
        pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
