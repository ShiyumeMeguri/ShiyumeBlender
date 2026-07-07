"""算子聚合注册:每个模块暴露 classes 元组,此处统一注册/注销。"""

import bpy

from . import (
    animation,
    bake_render,
    curves,
    endfield,
    export_scene,
    generate,
    mesh_cut,
    normals,
    object_layout,
    uv_layout,
    uv_morph,
    uv_redirect,
    vertex_color,
    weights,
)

_MODULES = (
    animation,
    object_layout,
    weights,
    normals,
    endfield,
    mesh_cut,
    vertex_color,
    uv_morph,
    uv_layout,
    uv_redirect,
    curves,
    bake_render,
    export_scene,
    generate,
)


def register():
    for module in _MODULES:
        for cls in module.classes:
            bpy.utils.register_class(cls)


def unregister():
    uv_morph.unregister_live_handler()
    for module in reversed(_MODULES):
        for cls in reversed(module.classes):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass
