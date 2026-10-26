"""预览会话：期望状态由 Scene 上的设置决定，实际状态（头发上的修改器、材质里的预览节点）每次对账一遍。

算子、定时器、存盘与读盘处理器都只调用对账，所以撤销、椭球被删、材质被导入器重建这类意外由同一处收拾，不靠谁记得去还原。
存盘前摘干净、存盘后接回，文件里不留预览；读盘后会话作废。
"""

import bpy
from bpy.app.handlers import persistent

from ..endfield_target import importer
from . import ellipsoid
from . import preview_geometry
from . import preview_shader

POLL_SECONDS = 0.5


def hair_objects(options):
    return [entry.obj for entry in options.hair if entry.obj is not None and entry.obj.type == 'MESH' and bpy.data.objects.get(entry.obj.name) is entry.obj]


def hair_materials(obj):
    return [slot.material for slot in obj.material_slots if slot.material is not None and importer.is_hair(slot.material)]


def reconcile():
    """让实际状态等于期望状态；椭球没了或没有可预览的头发就把那个场景的预览关掉；椭球永远只剩线框（旧版做的椭球读盘时在这里改过来）。
    返回没能接上预览的材质名。"""
    kept_objects = set()
    kept_materials = set()
    unwired = []
    for scene in bpy.data.scenes:
        options = scene.shiyume_endfield_highlight
        if ellipsoid.usable(scene, options.ellipsoid):
            ellipsoid.show_as_wire(options.ellipsoid)
        if not options.previewing:
            continue
        hair = hair_objects(options)
        if not ellipsoid.usable(scene, options.ellipsoid) or not hair:
            options.previewing = False
            continue
        for obj in hair:
            preview_geometry.attach(obj, options.ellipsoid)
            kept_objects.add(obj)
            for material in hair_materials(obj):
                if preview_shader.wire(material):
                    kept_materials.add(material)
                else:
                    unwired.append(material.name)
    preview_geometry.strip(kept_objects)
    preview_shader.strip(kept_materials)
    if kept_objects and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=POLL_SECONDS, persistent=True)
    return unwired


def _tick():
    reconcile()
    return POLL_SECONDS if any(scene.shiyume_endfield_highlight.previewing for scene in bpy.data.scenes) else None


def stop(scene):
    scene.shiyume_endfield_highlight.previewing = False
    reconcile()


@persistent
def _on_load(_path):
    for scene in bpy.data.scenes:
        scene.shiyume_endfield_highlight.previewing = False
    reconcile()


@persistent
def _on_save_pre(_path):
    preview_geometry.strip(set())
    preview_shader.strip(set())


@persistent
def _on_save_post(_path):
    reconcile()


def register():
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.save_pre.append(_on_save_pre)
    bpy.app.handlers.save_post.append(_on_save_post)


def unregister():
    for scene in bpy.data.scenes:
        scene.shiyume_endfield_highlight.previewing = False
    reconcile()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    bpy.app.handlers.save_post.remove(_on_save_post)
    bpy.app.handlers.save_pre.remove(_on_save_pre)
    bpy.app.handlers.load_post.remove(_on_load)
