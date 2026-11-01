"""发片朝向修复：高光法线只能存在发片正面半球里的方向（切线空间 Z ≥ 0），法线明显朝里的发片，高光会被夹平成碎片。

所以预览与烘焙之前，把明显朝里的发片整张翻朝外：发片是头发材质的面按边相连成的一片，整张翻保持相邻面朝向一致；
朝向取面积加权的「法线 · 最近的椭球法线」平均，低于 -CONFIDENT_INWARD 才翻（贴着头的发片这个值在 ±0.5 以上；
立在头外面的、垂着的发片法线与椭球法线近乎垂直，值在 0 附近，翻不翻高光都一样，不去动它的漫反射朝向）。
网格带自定义法线时翻绕向翻不动法线，不动它。
"""

from collections import namedtuple

import bmesh
import numpy as np

from ...uv.uv_transfer import mesh_bind
from ..endfield_target import importer
from . import bake

Repair = namedtuple("Repair", ("cards", "flipped_cards", "flipped_faces", "skipped"))

NOT_APPLICABLE = Repair(0, 0, 0, "")
CONFIDENT_INWARD = 0.2


def hair_slots(obj):
    return {index for index, slot in enumerate(obj.material_slots) if slot.material is not None and importer.is_hair(slot.material)}


def _facing(obj, depsgraph, ellipsoid, uv_name):
    """每个多边形的 (面积, 面积 × 法线与椭球法线的点积)。"""
    triangles = bake.triangles_of(obj, depsgraph, uv_name)
    surface = bake.surface_of(ellipsoid, obj, depsgraph)
    first = triangles.position[:, 1] - triangles.position[:, 0]
    second = triangles.position[:, 2] - triangles.position[:, 0]
    area = 0.5 * np.linalg.norm(np.cross(first, second), axis=1)
    normal = bake._unit(triangles.normal.mean(axis=1))
    proxy = bake._unit(bake.nearest_normals(surface, triangles.position.mean(axis=1)))
    polygons = len(obj.data.polygons)
    return (np.bincount(triangles.polygon, weights=area, minlength=polygons),
            np.bincount(triangles.polygon, weights=area * np.sum(normal * proxy, axis=1), minlength=polygons))


def _cards(bm, in_hair):
    """头发材质的面按边相连分成发片：每个面的发片编号（不是头发的面为 -1）与发片数。"""
    label = np.full(len(bm.faces), -1, dtype=np.int64)
    count = 0
    for seed in bm.faces:
        if label[seed.index] >= 0 or not in_hair[seed.index]:
            continue
        label[seed.index] = count
        pending = [seed]
        while pending:
            face = pending.pop()
            for edge in face.edges:
                for neighbour in edge.link_faces:
                    if label[neighbour.index] < 0 and in_hair[neighbour.index]:
                        label[neighbour.index] = count
                        pending.append(neighbour)
        count += 1
    return label, count


def repair(obj, ellipsoid, depsgraph):
    """把头发物体里法线明显朝里的发片整张翻朝外；返回 Repair(发片数, 翻了几张, 翻了几个面, 没翻的原因)。物体要在物体模式。"""
    mesh = obj.data
    slots = hair_slots(obj)
    uv_name = mesh_bind.render_uv_name(mesh)
    if not slots or not uv_name or not len(mesh.polygons):
        return NOT_APPLICABLE
    if mesh.has_custom_normals:
        return Repair(0, 0, 0, "带自定义法线，翻绕向翻不动法线，发片朝向没有自动修复")
    if len(obj.evaluated_get(depsgraph).data.polygons) != len(mesh.polygons):
        return Repair(0, 0, 0, "有改变面数的修改器，发片朝向没有自动修复")
    area, facing = _facing(obj, depsgraph, ellipsoid, uv_name)
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        last_slot = len(obj.material_slots) - 1
        in_hair = np.array([min(face.material_index, last_slot) in slots for face in bm.faces], dtype=bool)
        label, count = _cards(bm, in_hair)
        if not count:
            return NOT_APPLICABLE
        covered = label >= 0
        card_area = np.bincount(label[covered], weights=area[covered], minlength=count)
        card_facing = np.bincount(label[covered], weights=facing[covered], minlength=count)
        inward = card_facing < -CONFIDENT_INWARD * card_area
        flipped = [bm.faces[index] for index in np.flatnonzero(covered & inward[np.maximum(label, 0)])]
        if flipped:
            bmesh.ops.reverse_faces(bm, faces=flipped)
            bm.to_mesh(mesh)
            mesh.update()
    finally:
        bm.free()
    return Repair(count, int(inward.sum()), len(flipped), "")
