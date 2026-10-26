"""贴图里别人占着的像素：读同一张目标贴图、却不在这次生成范围里的面，外扩不许写到它们上面。"""

from collections import namedtuple

import bmesh
import bpy
import numpy as np

from ...uv.uv_transfer import kernel
from ...uv.uv_transfer import mesh_bind
from . import targets

Generation = namedtuple("Generation", ("uv_name", "included", "regular"))

PROTECTION_RING = 1


def _mesh_triangles(mesh, uv_name):
    uv = mesh_bind.read_uv(mesh, uv_name)
    if uv is None:
        return None
    if hasattr(mesh, "calc_loop_triangles"):
        mesh.calc_loop_triangles()
    count = len(mesh.loop_triangles)
    loops = np.empty(count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    polygons = np.empty(count, dtype=np.int32)
    mesh.loop_triangles.foreach_get("polygon_index", polygons)
    materials = np.empty(count, dtype=np.int32)
    mesh.loop_triangles.foreach_get("material_index", materials)
    return uv[loops.reshape(-1, 3)], polygons, materials


def _edit_triangles(mesh, uv_name):
    bm = bmesh.from_edit_mesh(mesh)
    uv_layer = bm.loops.layers.uv.get(uv_name)
    if uv_layer is None:
        return None
    triples = bm.calc_loop_triangles()
    uv = np.empty((len(triples), 3, 2), dtype=np.float32)
    polygons = np.empty(len(triples), dtype=np.int32)
    materials = np.empty(len(triples), dtype=np.int32)
    for index, triple in enumerate(triples):
        face = triple[0].face
        polygons[index] = face.index
        materials[index] = face.material_index
        for corner, loop in enumerate(triple):
            uv[index, corner] = loop[uv_layer].uv
    return uv, polygons, materials


def protected(key, width, height, generations, settings, regular_only):
    """目标图 key 上被生成范围以外的面占着的像素 (H, W) bool；generations 是 {物体名: Generation}，
    不在里面的物体整个都算范围以外；法线通道的生成范围只有规则长条（regular_only），颜色通道是全部发片。"""
    mask = np.zeros((height, width), dtype=bool)
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.data is None or not obj.material_slots:
            continue
        matching = [index for index, slot in enumerate(obj.material_slots)
                    if slot.material is not None and targets.key_of(slot.material, settings) == key]
        if not matching:
            continue
        generation = generations.get(obj.name)
        uv_name = generation.uv_name if generation is not None else mesh_bind.render_uv_name(obj.data)
        read = _edit_triangles if obj.mode == 'EDIT' else _mesh_triangles
        triangles = read(obj.data, uv_name)
        if triangles is None:
            continue
        uv, polygons, materials = triangles
        keep = np.isin(np.minimum(materials, len(obj.material_slots) - 1), matching)
        if generation is not None:
            keep &= ~(generation.regular if regular_only else generation.included)[polygons]
        mask |= kernel.coverage_mask(uv[keep], width, height, 1)
    return kernel.grow(mask, PROTECTION_RING)
