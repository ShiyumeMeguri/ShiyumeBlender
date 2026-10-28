"""高光法线烘焙：贴图每个像素取发片表面上的点，找椭球上离它最近的点的平滑法线，转进该像素的切线空间，编码成 B、A 两个通道。

三角形按 UV 光栅化，位置、法线、切线按重心坐标插值；全部在头发物体的局部空间里算，与预览一侧的几何节点是同一套最近点与法线。
法线朝向发片背面（切线空间 Z 小于零）的像素贴图表示不了，把 XY 归一化到单位长度，与预览一侧的节点组同一条规则。
"""

from collections import namedtuple

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

from ...uv.uv_transfer import kernel
from ...uv.uv_transfer import mesh_bind

Surface = namedtuple("Surface", ("tree", "positions", "normals", "triangles"))
Triangles = namedtuple("Triangles", ("uv", "position", "normal", "tangent", "sign", "slot"))
Source = namedtuple("Source", ("triangles", "surface"))
Field = namedtuple("Field", ("covered", "values"))

BARYCENTRIC_SOURCE = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]], dtype=np.float32)
SLICE_SAMPLES = 100000
EPSILON = 1e-12
BYTE_LEVELS = 255.0


def _read(array_owner, name, shape, dtype=np.float64):
    values = np.empty(int(np.prod(shape)), dtype=dtype)
    array_owner.foreach_get(name, values)
    return values.reshape(shape)


def surface_of(ellipsoid, obj, depsgraph):
    """椭球（含细分）搬进头发物体的局部空间后的表面：顶点、Blender 自己算的顶点平滑法线、三角形和最近点查询树。"""
    mesh = bpy.data.meshes.new_from_object(ellipsoid.evaluated_get(depsgraph), preserve_all_data_layers=False, depsgraph=depsgraph)
    try:
        mesh.transform(obj.matrix_world.inverted() @ ellipsoid.matrix_world)
        mesh.calc_loop_triangles()
        positions = _read(mesh.vertices, "co", (len(mesh.vertices), 3))
        normals = _read(mesh.vertex_normals, "vector", (len(mesh.vertices), 3))
        triangles = _read(mesh.loop_triangles, "vertices", (len(mesh.loop_triangles), 3), np.int64)
    finally:
        bpy.data.meshes.remove(mesh)
    tree = BVHTree.FromPolygons(positions.tolist(), triangles.tolist(), all_triangles=True)
    return Surface(tree, positions, normals, triangles)


def triangles_of(obj, depsgraph, uv_name):
    """头发物体（求值后）的三角形：每个角的 UV、局部位置、法线、切线，以及切线的副切线符号和材质槽下标。"""
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        mesh.calc_tangents(uvmap=uv_name)
        loop_count = len(mesh.loops)
        triangle_count = len(mesh.loop_triangles)
        loops = _read(mesh.loop_triangles, "loops", (triangle_count, 3), np.int64)
        vertex_index = _read(mesh.loops, "vertex_index", loop_count, np.int64)
        positions = _read(mesh.vertices, "co", (len(mesh.vertices), 3))
        normals = _read(mesh.loops, "normal", (loop_count, 3))
        tangents = _read(mesh.loops, "tangent", (loop_count, 3))
        signs = _read(mesh.loops, "bitangent_sign", loop_count)
        slots = _read(mesh.loop_triangles, "material_index", triangle_count, np.int64)
        uv = mesh_bind.read_uv(mesh, uv_name)[loops]
    finally:
        evaluated.to_mesh_clear()
    return Triangles(uv, positions[vertex_index[loops]], normals[loops], tangents[loops], signs[loops], slots)


def select(triangles, mask):
    return Triangles(*(array[mask] for array in triangles))


def nearest_normals(surface, points):
    """表面上离每个点最近的点的平滑法线：最近三角形上的重心坐标插值顶点法线，不归一化（与几何节点的采样一致）。"""
    found = [surface.tree.find_nearest(point) for point in points.tolist()]
    nearest = np.array([coordinate for item in found for coordinate in item[0]]).reshape(-1, 3)
    corners = surface.triangles[np.array([item[2] for item in found], dtype=np.int64)]
    first, second, third = (surface.positions[corners[:, index]] for index in range(3))
    edge_second = second - first
    edge_third = third - first
    offset = nearest - first
    dot_second = np.sum(edge_second * edge_second, axis=1)
    dot_cross = np.sum(edge_second * edge_third, axis=1)
    dot_third = np.sum(edge_third * edge_third, axis=1)
    offset_second = np.sum(offset * edge_second, axis=1)
    offset_third = np.sum(offset * edge_third, axis=1)
    denominator = dot_second * dot_third - dot_cross * dot_cross
    weight_second = (dot_third * offset_second - dot_cross * offset_third) / denominator
    weight_third = (dot_second * offset_third - dot_cross * offset_second) / denominator
    weight_first = 1.0 - weight_second - weight_third
    return (surface.normals[corners[:, 0]] * weight_first[:, None] + surface.normals[corners[:, 1]] * weight_second[:, None]
            + surface.normals[corners[:, 2]] * weight_third[:, None])


def _blend(corner_values, triangle, weights):
    return np.einsum("sc,scd->sd", weights, corner_values[triangle])


def _unit(vectors):
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), EPSILON)


def _encode(highlight, tangent, bitangent, normal):
    x = np.sum(highlight * tangent, axis=1)
    y = np.sum(highlight * bitangent, axis=1)
    z = np.sum(highlight * normal, axis=1)
    shrink = np.where(z < 0.0, 1.0 / np.maximum(np.hypot(x, y), EPSILON), 1.0)
    encoded = np.stack((x * shrink, y * shrink), axis=1) * 0.5 + 0.5
    return (np.round(np.clip(encoded, 0.0, 1.0) * BYTE_LEVELS) / BYTE_LEVELS).astype(np.float32)


def field_of(sources, width, height):
    """按贴图尺寸光栅化全部来源，返回覆盖到的像素 (H, W) 和每个像素的 B、A 编码 (H, W, 2)。"""
    covered = np.zeros(width * height, dtype=bool)
    values = np.zeros((width * height, 2), dtype=np.float32)
    for triangles, surface in sources:
        basis = np.broadcast_to(BARYCENTRIC_SOURCE, (len(triangles.uv), 3, 2))
        for pixel, weights, triangle in kernel.iter_samples(triangles.uv, basis, width, height, 1):
            for start in range(0, pixel.size, SLICE_SAMPLES):
                part = slice(start, start + SLICE_SAMPLES)
                part_triangle = triangle[part]
                first = weights[part, 0].astype(np.float64)
                second = weights[part, 1].astype(np.float64)
                stacked = np.stack((first, second, 1.0 - first - second), axis=1)
                position = _blend(triangles.position, part_triangle, stacked)
                normal = _unit(_blend(triangles.normal, part_triangle, stacked))
                tangent = _unit(_blend(triangles.tangent, part_triangle, stacked))
                sign = triangles.sign[part_triangle, np.argmax(stacked, axis=1)]
                bitangent = _unit(sign[:, None] * np.cross(normal, tangent))
                highlight = _unit(nearest_normals(surface, position))
                values[pixel[part]] = _encode(highlight, tangent, bitangent, normal)
                covered[pixel[part]] = True
    return Field(covered.reshape(height, width), values.reshape(height, width, 2))
