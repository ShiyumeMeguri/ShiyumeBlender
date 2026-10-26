"""头发长条的几何：UV 孤岛整理成排，量出每个顶点在发片矩形里的横向与沿长度的占比（按 UV 与按 3D 弧长两种）、三维位置，以及发片的尺度。

长条的 UV 是矩形，纹路在矩形里是竖条纹。程序（procedural）按「按 3D 折算」滑条把两种占比和尺度折成毫米坐标，所以这里只量不折算：
规则的四边形长条（与「修复头发展开」同一把判据）按顶点排布精确量；发根一端取 UV 里 V 大的一边。
不规则的孤岛（含三角形的发梢、不成网格的片）退而按 UV 包围盒近似，尺度取 UV 到 3D 位置的仿射拟合，发根取 3D 里较高的一端，
只配套生成颜色用，法线纹路依赖精确的排布，不生成。
"""

import zlib
from collections import namedtuple

import numpy as np

from ...uv import hair_strip_unwrap
from ...uv import uv_islands

Strip = namedtuple("Strip", ("faces", "across_uv", "across_arc", "along_uv", "along_arc", "positions", "mean_width", "path_length",
                             "uv_width", "uv_length", "index", "tag", "regular"))

MILLIMETRES_PER_METRE = 1000.0
DEGENERATE_LENGTH = 1.0e-9
TAG_MASK = 0xFFFF


def _row_fractions(row_positions):
    distances = [0.0]
    for index in range(1, len(row_positions)):
        distances.append(distances[-1] + (row_positions[index] - row_positions[index - 1]).length)
    width = distances[-1]
    if width < DEGENERATE_LENGTH:
        return [index / (len(row_positions) - 1) for index in range(len(row_positions))], 0.0
    return [distance / width for distance in distances], width


def _measure(rows, uvs, matrix, millimetres_per_unit):
    across_arc = {}
    positions = {}
    widths = []
    centers = []
    for row in rows:
        row_positions = [matrix @ vertex.co for vertex in row]
        fractions, width = _row_fractions(row_positions)
        for vertex, position, fraction in zip(row, row_positions, fractions):
            across_arc[vertex] = fraction
            positions[vertex] = tuple(position * millimetres_per_unit)
        widths.append(width)
        centers.append(0.5 * (row_positions[0] + row_positions[-1]))
    arc = [0.0]
    area = 0.0
    for index in range(1, len(centers)):
        step = (centers[index] - centers[index - 1]).length
        arc.append(arc[-1] + step)
        area += step * 0.5 * (widths[index] + widths[index - 1])
    length = arc[-1]
    if length < DEGENERATE_LENGTH:
        raise hair_strip_unwrap.UnsupportedIsland("长度为零")
    us = [uvs[vertex][0] for row in rows for vertex in row]
    u_low, u_span = min(us), max(us) - min(us)
    row_v = [float(np.mean([uvs[vertex][1] for vertex in row])) for row in rows]
    v_span = row_v[-1] - row_v[0]
    if u_span < DEGENERATE_LENGTH or abs(v_span) < DEGENERATE_LENGTH:
        raise hair_strip_unwrap.UnsupportedIsland("UV 退化")
    across_uv = {}
    along_uv = {}
    along_arc = {}
    for row, distance, v in zip(rows, arc, row_v):
        for vertex in row:
            across_uv[vertex] = (uvs[vertex][0] - u_low) / u_span
            along_uv[vertex] = (v - row_v[0]) / v_span
            along_arc[vertex] = distance / length
    return (across_uv, across_arc, along_uv, along_arc, positions, area / length * millimetres_per_unit,
            length * millimetres_per_unit, u_span, abs(v_span))


def _approximate(faces, uvs, uv_layer, matrix, millimetres_per_unit):
    """按 UV 包围盒近似：横向取 U、长度取 V，发根在 3D 里较高的一端；
    毫米尺度取 UV 到 3D 位置的仿射拟合，U、V 两个方向各量各的，UV 各向异性缩放也折算得对。"""
    vertices = {}
    positions = {}
    for face in faces:
        for loop in face.loops:
            world_position = matrix @ loop.vert.co
            vertices[loop.vert] = (loop[uv_layer].uv.x, loop[uv_layer].uv.y, world_position.z)
            positions[loop.vert] = tuple(world_position * millimetres_per_unit)
    values = np.array(list(vertices.values()))
    low = values[:, :2].min(axis=0)
    span = values[:, :2].max(axis=0) - low
    if min(span) < DEGENERATE_LENGTH:
        raise hair_strip_unwrap.UnsupportedIsland("包围盒退化")
    design = np.column_stack((values[:, :2], np.ones(len(values))))
    world = np.array([positions[vertex] for vertex in vertices])
    solution = np.linalg.lstsq(design, world, rcond=None)[0]
    width = float(span[0]) * float(np.linalg.norm(solution[0]))
    length = float(span[1]) * float(np.linalg.norm(solution[1]))
    if min(width, length) < DEGENERATE_LENGTH:
        raise hair_strip_unwrap.UnsupportedIsland("包围盒退化")
    slope = np.polyfit(values[:, 1], values[:, 2], 1)[0]
    across = {}
    along = {}
    for vertex, (u, v, _height) in vertices.items():
        across[vertex] = (u - low[0]) / span[0]
        along[vertex] = ((low[1] + span[1] - v) if slope > 0.0 else (v - low[1])) / span[1]
    return across, across, along, along, positions, width, length, float(span[0]), float(span[1])


def collect(obj, bm, uv_layer, scene):
    """返回 ([Strip], [(不规则的原因, 面数)])：规则长条精确量；不规则的孤岛按包围盒近似也放进列表（regular 为假），原因另外记下。"""
    millimetres_per_unit = scene.unit_settings.scale_length * MILLIMETRES_PER_METRE
    matrix = obj.matrix_world
    tag = zlib.crc32(obj.name.encode("utf-8")) & TAG_MASK
    strips = []
    irregular = []
    for faces in uv_islands.collect_islands(bm, uv_layer):
        height_of_vertex = {loop.vert: loop[uv_layer].uv.y for face in faces for loop in face.loops}
        uvs = {loop.vert: tuple(loop[uv_layer].uv) for face in faces for loop in face.loops}
        try:
            rows = hair_strip_unwrap.root_first(
                hair_strip_unwrap.strip_rows(faces), lambda vertex: -height_of_vertex[vertex])
            values = _measure(rows, uvs, matrix, millimetres_per_unit)
            regular = True
        except hair_strip_unwrap.UnsupportedIsland as error:
            irregular.append((str(error), len(faces)))
            try:
                values = _approximate(faces, uvs, uv_layer, matrix, millimetres_per_unit)
            except hair_strip_unwrap.UnsupportedIsland:
                continue
            regular = False
        strips.append(Strip(faces, *values, min(face.index for face in faces), tag, regular))
    return strips, irregular
