"""发片每个面角的程序输入：占比、尺度、编号、规则与否，以及纹路的横向与纵向在这个角的切线空间里的两个分量。

烘焙从这张表取四边形的四个角，实时预览把同一张表写成网格的角属性，两边的输入是同一份。
纹路方向取 UV 占比的梯度（与折算滑条无关）：一个面角的两个邻角和它自己组成三角形，量出该三角形里的两个方向，
切线沿 U 方向的世界向量，副切线垂直于它并与 V 方向同侧，法线朝面的绕向；UV 怎么缩放、拉伸、旋转都不影响纹路在世界里的方向。纯 numpy，不引用 bpy。
"""

from collections import namedtuple

import numpy as np

from . import procedural

ORDER = tuple(procedural.geometry_inputs())
Table = namedtuple("Table", ("offset", "loops", "values"))

DEGENERATE_AREA = 1.0e-24
DEGENERATE_DIRECTION = 1.0e-12


def _unit(vectors, fallback):
    norm = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.where(norm > DEGENERATE_DIRECTION, vectors / np.maximum(norm, DEGENERATE_DIRECTION), fallback)


def _surface_gradient(edge_one, edge_two, source, channel):
    """线性插值的标量（源坐标的一个通道）在三角形所在平面里的梯度向量。"""
    first = (source[:, 1, channel] - source[:, 0, channel]).astype(np.float64)
    second = (source[:, 2, channel] - source[:, 0, channel]).astype(np.float64)
    gram_one = np.sum(edge_one * edge_one, axis=-1)
    gram_cross = np.sum(edge_one * edge_two, axis=-1)
    gram_two = np.sum(edge_two * edge_two, axis=-1)
    determinant = gram_one * gram_two - gram_cross * gram_cross
    valid = np.abs(determinant) > DEGENERATE_AREA
    safe = np.where(valid, determinant, 1.0)
    coefficient_one = (gram_two * first - gram_cross * second) / safe
    coefficient_two = (gram_one * second - gram_cross * first) / safe
    gradient = edge_one * coefficient_one[:, None] + edge_two * coefficient_two[:, None]
    return np.where(valid[:, None], gradient, 0.0)


def frames(target, source, positions):
    """每个三角形里纹路的横向与纵向（源坐标增大的方向）在切线空间里的两个分量 (T, 2)。"""
    world = positions.astype(np.float64)
    edge_one = world[:, 1] - world[:, 0]
    edge_two = world[:, 2] - world[:, 0]
    normal = _unit(np.cross(edge_one, edge_two), np.array([0.0, 0.0, 1.0]))
    uv_one = (target[:, 1] - target[:, 0]).astype(np.float64)
    uv_two = (target[:, 2] - target[:, 0]).astype(np.float64)
    determinant = uv_one[:, 0] * uv_two[:, 1] - uv_two[:, 0] * uv_one[:, 1]
    safe = np.where(np.abs(determinant) > DEGENERATE_AREA, determinant, 1.0)[:, None]
    along_u = (edge_one * uv_two[:, 1:2] - edge_two * uv_one[:, 1:2]) / safe
    along_v = (edge_two * uv_one[:, 0:1] - edge_one * uv_two[:, 0:1]) / safe
    tangent = _unit(along_u, np.array([1.0, 0.0, 0.0]))
    bitangent = np.cross(normal, tangent)
    bitangent = np.where((np.sum(bitangent * along_v, axis=-1) < 0.0)[:, None], -bitangent, bitangent)
    across_direction = _unit(_surface_gradient(edge_one, edge_two, source, 0), tangent)
    along_direction = _unit(_surface_gradient(edge_one, edge_two, source, 1), bitangent)
    across = np.stack((np.sum(across_direction * tangent, axis=-1), np.sum(across_direction * bitangent, axis=-1)), axis=-1)
    along = np.stack((np.sum(along_direction * tangent, axis=-1), np.sum(along_direction * bitangent, axis=-1)), axis=-1)
    return across.astype(np.float32), along.astype(np.float32)


def build(strips, uv_layer):
    """strips 里每个面的每个面角一行，列顺序是 ORDER；offset 是 {面下标: 该面第一个角的行号}，loops 是每行对应的网格面角下标（物体模式的 bmesh 才准）。"""
    loops = []
    uvs = []
    positions = []
    fixed = []
    first = []
    sizes = []
    offset = {}
    for strip in strips:
        constants = {"uvWidth": strip.uv_width, "uvLength": strip.uv_length, "meanWidth": strip.mean_width, "pathLength": strip.path_length,
                     "stripId": float(strip.index), "objectTag": float(strip.tag), "regular": 1.0 if strip.regular else 0.0}
        for face in strip.faces:
            members = list(face.loops)
            offset[face.index] = len(loops)
            for loop in members:
                vertex = loop.vert
                loops.append(loop.index)
                uvs.append(tuple(loop[uv_layer].uv))
                positions.append(strip.positions[vertex])
                fixed.append({"acrossUv": strip.across_uv[vertex], "acrossArc": strip.across_arc[vertex],
                              "alongUv": strip.along_uv[vertex], "alongArc": strip.along_arc[vertex], **constants})
                first.append(offset[face.index])
                sizes.append(len(members))
    count = len(loops)
    if not count:
        return Table(offset, np.zeros(0, np.int64), np.zeros((0, len(ORDER)), np.float32))
    uvs = np.array(uvs, dtype=np.float32)
    positions = np.array(positions, dtype=np.float32)
    columns = {name: np.array([row[name] for row in fixed], dtype=np.float32) for name in fixed[0]}
    index = np.arange(count)
    first = np.array(first)
    sizes = np.array(sizes)
    neighbours = np.stack((first + (index - first - 1) % sizes, index, first + (index - first + 1) % sizes), axis=1)
    source = np.stack((columns["acrossUv"][neighbours], columns["alongUv"][neighbours]), axis=-1)
    across_frame, along_frame = frames(uvs[neighbours], source, positions[neighbours])
    columns.update({"frameAcrossX": across_frame[:, 0], "frameAcrossY": across_frame[:, 1],
                    "frameAlongX": along_frame[:, 0], "frameAlongY": along_frame[:, 1],
                    "positionX": positions[:, 0], "positionY": positions[:, 1], "positionZ": positions[:, 2]})
    return Table(offset, np.array(loops, dtype=np.int64), np.column_stack([columns[name] for name in ORDER]).astype(np.float32))
