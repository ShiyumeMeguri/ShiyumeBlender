import bpy

from . import state
from .tabs import BY_KEY
from .tabs import TABS


class SHIYUME_PT_Sidebar(bpy.types.Panel):
    """View3D > N > Shiyume：一排标签，下面画选中标签的正文。"""
    bl_label = "Shiyume"
    bl_idname = "SHIYUME_PT_Sidebar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'

    def draw(self, context):
        layout = self.layout
        window_manager = context.window_manager
        strip = layout.grid_flow(row_major=True, columns=0, even_columns=True, even_rows=False, align=True)
        for tab in TABS:
            strip.prop_enum(window_manager, state.PROPERTY, tab.key, text=tab.label)
        layout.separator()
        BY_KEY[getattr(window_manager, state.PROPERTY)].draw(layout, context)
