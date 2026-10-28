"""描边平滑法线的数学（纯 numpy，不碰 bpy）。

游戏的描边顶点着色器把 UV2 当切线空间平滑法线的 XY，Z 现算：z = sqrt(1 - x² - y²)，平滑法线 = 切线 * x + 副切线 * y + 法线 * z，
副切线 = cross(法线, 切线) * 符号。烘焙是它的逆过程：把平滑法线投到每个角自己的切线框里取 XY。

平滑法线 = 焊接点上各面的几何法线按所在角的夹角加权求和再归一化。拿游戏导入网格的真实 UV2 逐角对过（身体、脸和主要衣物 96%～100%
的角差在 1° 以内，中位差 0.25°；头发 89%，中位差 0.34°），余量是 Unity 与 Blender 两套切线的差；面积加权、均匀加权、顶点法线、
角法线求平均都差得远。
"""

import numpy as np

EPSILON = 1e-12
ZERO_SUM = 1e-9


def unit(vectors):
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), EPSILON)


def corner_angles(corner_position, previous_position, next_position):
    """每个角在自己多边形里的夹角（弧度）。"""
    toward_next = unit(next_position - corner_position)
    toward_previous = unit(previous_position - corner_position)
    return np.arccos(np.clip(np.sum(toward_next * toward_previous, axis=1), -1.0, 1.0))


def weighted_smooth_normals(face_normal, angle, group):
    """每个焊接组里各角的 面法线 × 夹角 求和再归一化，按角回填。求和为零的组（背靠背的面）给零向量，由调用方换成角自己的法线。"""
    sums = np.zeros((int(group.max()) + 1, 3), dtype=np.float64)
    np.add.at(sums, group, face_normal * angle[:, None])
    summed = sums[group]
    length = np.linalg.norm(summed, axis=1, keepdims=True)
    return np.where(length > ZERO_SUM, summed / np.maximum(length, EPSILON), 0.0)


def encode(smooth, tangent, bitangent, normal):
    """平滑法线在每个角的切线框里的 XY。Z 小于零（平滑法线翻到面背后）的角 UV 表示不了，XY 归一化到单位长度（着色器算出的 Z 为 0）。
    返回 (XY, 被收缩的角的掩码)。"""
    x = np.sum(smooth * tangent, axis=1)
    y = np.sum(smooth * bitangent, axis=1)
    z = np.sum(smooth * normal, axis=1)
    behind = z < 0.0
    shrink = np.where(behind, 1.0 / np.maximum(np.hypot(x, y), EPSILON), 1.0)
    return np.stack((x * shrink, y * shrink), axis=1), behind


def decode(xy, tangent, bitangent, normal):
    """着色器的解码：平滑法线 = 切线 * x + 副切线 * y + 法线 * sqrt(1 - x² - y²)。"""
    z = np.sqrt(np.maximum(1.0 - np.sum(xy * xy, axis=1), 0.0))
    return unit(tangent * xy[:, 0:1] + bitangent * xy[:, 1:2] + normal * z[:, None])


def angle_degrees(first, second):
    return np.degrees(np.arccos(np.clip(np.sum(unit(first) * unit(second), axis=1), -1.0, 1.0)))
