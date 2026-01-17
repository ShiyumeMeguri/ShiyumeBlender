import bpy
from . import clear_empty

classes = (
    clear_empty.SHIYUME_OT_ClearEmpty,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
