import bpy
from . import clear_empty
from . import sort_roots_x

classes = (
    clear_empty.SHIYUME_OT_ClearEmpty,
    sort_roots_x.SHIYUME_OT_SortRootsX,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
