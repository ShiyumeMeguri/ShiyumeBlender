bl_info = {
    "name": "Shiyume Blender Addon",
    "author": "Shiyume",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Context (W) Menu",
    "description": "Consolidated toolset for modeling, animation, and UVs",
    "category": "Object",
}

import bpy
from . import ui
from .operators import animation, shader, uv, mesh, curve, misc, object_ops

modules = [
    animation,
    shader,
    uv,
    mesh,
    curve,
    misc,
    object_ops,
    ui
]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()

if __name__ == "__main__":
    register()
