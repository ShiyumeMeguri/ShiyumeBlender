import bpy
from . import pack_lock
from . import sync_shapekey
from . import mesh_to_uv
from . import smart_uv_redirect

classes = (
    pack_lock.SHIYUME_OT_UVPackLockGroup,
    sync_shapekey.SHIYUME_OT_MeshUVSync,
    mesh_to_uv.SHIYUME_OT_MeshToUV,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # 注册 debug 步骤 + 面板 + 一键执行
    for cls in smart_uv_redirect._debug_classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(smart_uv_redirect._debug_classes):
        bpy.utils.unregister_class(cls)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
