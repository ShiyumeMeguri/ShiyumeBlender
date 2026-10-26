import bpy

from . import panel
from . import state


def register():
    state.register()
    bpy.utils.register_class(panel.SHIYUME_PT_Sidebar)


def unregister():
    bpy.utils.unregister_class(panel.SHIYUME_PT_Sidebar)
    state.unregister()
