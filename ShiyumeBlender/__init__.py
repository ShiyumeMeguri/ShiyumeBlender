bl_info = {
    "name": "ShiyumeTools",
    "author": "Shiyume Meguri",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Edit Tab / Edit Mode Context Menu",
    "warning": "",
    "description": "包含我对blender所有不满与对应的解决方案",
    "doc_url": "{BLENDER_MANUAL_URL}/addons/mesh/shiyumetools.html",
    "category": "Object",
}

import bpy
import bmesh
from bpy.types import (
        Operator,
        Menu,
        Panel,
        PropertyGroup,
        AddonPreferences,
        )
from bpy.props import (
        BoolProperty,
        EnumProperty,
        FloatProperty,
        IntProperty,
        PointerProperty,
        StringProperty,
        )
from .Other.Curve.ToMesh import *
from .Other.Mesh.ToCurve import *

# ########################################
# ##### GUI and registration #############
# ########################################

# menu containing all tools
class VIEW3D_MT_object_shiyumetools(Menu):
    bl_label = "ShiyumeTools"

    def draw(self, context):
        layout = self.layout

        layout.operator("curve.shiyumetools_tomesh")
        layout.operator("mesh.shiyumetools_tocurve")

# draw function for integration in menus
def menu_func(self, context):
    self.layout.menu("VIEW3D_MT_object_shiyumetools")
    self.layout.separator()

# define classes for registration
classes = (
    VIEW3D_MT_object_shiyumetools,
    ToMesh,
    ToCurve,
)


# registering and menu integration
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_object_context_menu.prepend(menu_func)


# unregistering and removing menus
def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.types.VIEW3D_MT_object_context_menu.remove(menu_func)


if __name__ == "__main__":
    register()
