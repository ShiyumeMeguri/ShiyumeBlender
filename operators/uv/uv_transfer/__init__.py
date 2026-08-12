import bpy

from . import operator
from . import settings

classes = (
    operator.SHIYUME_OT_UVTransfer,
)


def register():
    settings.register()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    settings.unregister()
