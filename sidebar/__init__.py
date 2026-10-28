import bpy

from . import importer_slots
from . import panel
from . import state


def register():
    state.register()
    bpy.utils.register_class(panel.SHIYUME_PT_Sidebar)
    importer_slots.register()


def unregister():
    importer_slots.unregister()
    bpy.utils.unregister_class(panel.SHIYUME_PT_Sidebar)
    state.unregister()
