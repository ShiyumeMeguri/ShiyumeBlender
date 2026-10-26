import bpy

from . import operator
from . import session
from . import settings

classes = (
    operator.SHIYUME_OT_EndfieldHighlightCreate,
    operator.SHIYUME_OT_EndfieldHighlightPreview,
    operator.SHIYUME_OT_EndfieldHighlightStop,
    operator.SHIYUME_OT_EndfieldHighlightBake,
)


def register():
    settings.register()
    for cls in classes:
        bpy.utils.register_class(cls)
    session.register()


def unregister():
    session.unregister()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    settings.unregister()
