"""发片四边形的数组形态与细分。

四边形在 UV 里是双线性面片，直接拆成两个三角形会让坐标在对角线两侧各自线性插值，
收窄的发片里纹路会在对角线上折弯；先按双线性细分成 DIVISIONS x DIVISIONS 个小格再拆三角形，
小三角形内的线性近似误差降到 1 / DIVISIONS 的平方。每个角带着 attributes 表里的一整行程序输入，细分时一起插值。纯 numpy，不引用 bpy。
"""

from collections import namedtuple

import numpy as np

DIVISIONS = 4
TRIANGLES_PER_QUAD = 2 * DIVISIONS * DIVISIONS

Quads = namedtuple("Quads", ("uv", "attributes", "strip", "slot", "face", "regular"))

TAG_SHIFT = 20


def _corner_sets(count):
    """面的角怎么落成四边形：四边形原样，其余按扇形拆成三角形、第四个角重复第三个，成退化的四边形。"""
    if count == 4:
        return [(0, 1, 2, 3)]
    return [(0, index, index + 1, index + 1) for index in range(1, count - 1)]


def build(strips, uv_layer, table, include):
    """把发片里 include(face) 为真的面取成数组：每个角的 UV 与程序输入行（table 来自 attributes.build），
    每个面所属发片的编号、材质槽、面下标与是否规则。"""
    count = sum(len(_corner_sets(len(face.loops))) for strip in strips for face in strip.faces if include(face))
    width = table.values.shape[1]
    uv = np.zeros((count, 4, 2), np.float32)
    attributes = np.zeros((count, 4, width), np.float32)
    strip_id = np.zeros(count, np.int64)
    slot = np.zeros(count, np.int32)
    face_index = np.zeros(count, np.int32)
    regular = np.zeros(count, bool)
    cursor = 0
    for strip in strips:
        for face in strip.faces:
            if not include(face):
                continue
            loops = list(face.loops)
            start = table.offset[face.index]
            for corners in _corner_sets(len(loops)):
                for position, corner in enumerate(corners):
                    uv[cursor, position] = loops[corner][uv_layer].uv
                    attributes[cursor, position] = table.values[start + corner]
                strip_id[cursor] = (strip.tag << TAG_SHIFT) | strip.index
                slot[cursor] = face.material_index
                face_index[cursor] = face.index
                regular[cursor] = strip.regular
                cursor += 1
    return Quads(uv, attributes, strip_id, slot, face_index, regular)


def select(quads, mask):
    return Quads(*(array[mask] for array in quads))


def concatenate(parts):
    return Quads(*(np.concatenate([part[index] for part in parts]) for index in range(len(Quads._fields))))


def _cell_weights():
    grid = np.linspace(0.0, 1.0, DIVISIONS + 1)
    first, second = np.meshgrid(grid, grid)
    weights = np.stack(((1.0 - first) * (1.0 - second), first * (1.0 - second), first * second, (1.0 - first) * second),
                       axis=-1)
    return weights.reshape(-1, 4).astype(np.float32)


def _cell_triangles():
    stride = DIVISIONS + 1
    cells = np.array([[row * stride + column, row * stride + column + 1,
                       (row + 1) * stride + column + 1, (row + 1) * stride + column]
                      for row in range(DIVISIONS) for column in range(DIVISIONS)])
    return np.concatenate((cells[:, [0, 1, 2]], cells[:, [0, 2, 3]]))


def triangles(quads):
    """返回 (目标 UV 三角形 (T, 3, 2), 对应的程序输入 (T, 3, 列数))，第 i 个面的三角形下标是 [i * TRIANGLES_PER_QUAD, (i + 1) * TRIANGLES_PER_QUAD)。"""
    weights = _cell_weights()
    split = _cell_triangles()
    points_uv = np.einsum('gc,qcd->qgd', weights, quads.uv)
    points_attributes = np.einsum('gc,qcd->qgd', weights, quads.attributes)
    target = points_uv[:, split, :].reshape(-1, 3, 2).astype(np.float32)
    attributes = points_attributes[:, split, :].reshape(-1, 3, quads.attributes.shape[2]).astype(np.float32)
    return target, attributes
