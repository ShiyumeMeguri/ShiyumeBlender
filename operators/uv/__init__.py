import bpy
from . import pack_lock
from . import sync_shapekey
from . import mesh_to_uv
from . import uv_from_mesh
from . import island_arrange
from . import mesh_uv_sync_live
from . import uv_transfer

classes = (
    pack_lock.SHIYUME_OT_UVPackLockGroup,
    sync_shapekey.SHIYUME_OT_MeshUVSync,
    mesh_to_uv.SHIYUME_OT_MeshToUV,
    uv_from_mesh.SHIYUME_OT_UVFromMesh,
    island_arrange.SHIYUME_OT_UVIslandEquidistant,
    island_arrange.SHIYUME_OT_UVIslandSortByHeight,
    mesh_uv_sync_live.SHIYUME_OT_MeshUVSyncLive,
    mesh_uv_sync_live.SHIYUME_OT_MeshUVSyncLiveDisable,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    uv_transfer.register()

def unregister():
    uv_transfer.unregister()
    # ensure live UV handler is removed when unregistering
    try:
        mesh_uv_sync_live.unregister_handler()
    except Exception:
        pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
