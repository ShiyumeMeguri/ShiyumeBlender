import bpy

from . import operator
from . import settings

classes = (
    operator.SHIYUME_OT_HairPreviewStart,
    operator.SHIYUME_OT_HairPreviewLocal,
    operator.SHIYUME_OT_HairPreviewDropLocal,
    operator.SHIYUME_OT_HairPreviewRandomSeed,
    operator.SHIYUME_OT_HairPreviewRefresh,
    operator.SHIYUME_OT_HairPreviewCancel,
    operator.SHIYUME_OT_HairPreviewBake,
)


def register():
    settings.register()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    settings.unregister()
