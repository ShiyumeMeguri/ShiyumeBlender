"""NumPy 批量读写桥。

所有热路径禁止逐元素 Python 循环:读写一律 foreach_get/foreach_set 打平数组,
计算一律向量化。本模块同时提供网格常用派生量(角法线、UV、多边形内前驱后继)。
"""

import numpy as np


# ---------------------------------------------------------------------------
# foreach 桥
# ---------------------------------------------------------------------------

def read_float(collection, attribute, components, dtype=np.float32):
    """把集合的浮点属性极速读入 (N, components) 数组;components=1 时返回一维。"""
    count = len(collection)
    flat = np.empty(count * components, dtype=dtype)
    collection.foreach_get(attribute, flat)
    return flat.reshape(count, components) if components > 1 else flat


def write_float(collection, attribute, array):
    """把数组极速写回集合的浮点属性。"""
    collection.foreach_set(attribute, np.ascontiguousarray(array, dtype=np.float32).ravel())


def read_int(collection, attribute, components=1):
    count = len(collection)
    flat = np.empty(count * components, dtype=np.int32)
    collection.foreach_get(attribute, flat)
    return flat.reshape(count, components) if components > 1 else flat


def read_bool(collection, attribute):
    count = len(collection)
    flat = np.empty(count, dtype=np.bool_)
    collection.foreach_get(attribute, flat)
    return flat


# ---------------------------------------------------------------------------
# 网格派生量
# ---------------------------------------------------------------------------

def read_corner_normals(mesh):
    """读取网格当前实际着色用的角法线(含自定义法线 / 平滑标记的最终结果)。"""
    loop_count = len(mesh.loops)
    flat = np.empty(loop_count * 3, dtype=np.float32)
    corner = getattr(mesh, "corner_normals", None)
    if corner is not None and len(corner) == loop_count:
        corner.foreach_get("vector", flat)
    else:
        mesh.loops.foreach_get("normal", flat)
    return flat.reshape(loop_count, 3)


def read_uvs(mesh, uv_layer=None):
    """读取 UV 层(默认激活层)每个 loop 的坐标,返回 (L, 2)。"""
    if uv_layer is None:
        uv_layer = mesh.uv_layers.active
    return read_float(uv_layer.data, "uv", 2)


def loop_neighbors(mesh):
    """每个 loop 在其所属多边形内的 (前驱, 后继) loop 下标,全向量化。"""
    loop_start = read_int(mesh.polygons, "loop_start")
    loop_total = read_int(mesh.polygons, "loop_total")
    starts = np.repeat(loop_start, loop_total)
    sizes = np.repeat(loop_total, loop_total)
    local = np.arange(len(mesh.loops), dtype=np.int32) - starts
    previous_loops = starts + (local - 1) % sizes
    next_loops = starts + (local + 1) % sizes
    return previous_loops, next_loops


def apply_matrix(matrix_world, points):
    """4x4 矩阵批量变换 (N, 3) 点集。"""
    matrix = np.array(matrix_world, dtype=np.float64)
    return points.astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3]


# ---------------------------------------------------------------------------
# 向量 / 分组
# ---------------------------------------------------------------------------

def normalize_rows(vectors):
    """对 (N, 3) 数组逐行归一化,零向量保持为零。"""
    lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
    lengths[lengths == 0.0] = 1.0
    return vectors / lengths


def scatter_first_loop(vertex_count, loop_vertex_indices, loop_values, out=None):
    """按"每顶点第一条 loop 优先"把 loop 值散射到顶点(倒序写入,首现胜出)。"""
    if out is None:
        out = np.zeros((vertex_count, loop_values.shape[1]), dtype=loop_values.dtype)
    out[loop_vertex_indices[::-1]] = loop_values[::-1]
    return out


def group_rows(rows_int):
    """整数行分组:返回 (每行所属组号, 组数)。"""
    if len(rows_int) == 0:
        return np.empty(0, dtype=np.int64), 0
    unique, inverse = np.unique(rows_int, axis=0, return_inverse=True)
    return inverse.reshape(-1), len(unique)


def group_weighted_mean_normalized(inverse, group_count, vectors, weights):
    """按组加权求和并归一化,再散播回每个元素。bincount 路径,零 Python 循环。"""
    sums = np.empty((group_count, vectors.shape[1]), dtype=np.float64)
    weighted = vectors.astype(np.float64) * weights.astype(np.float64)[:, None]
    for component in range(vectors.shape[1]):
        sums[:, component] = np.bincount(inverse, weights=weighted[:, component], minlength=group_count)
    return normalize_rows(sums)[inverse].astype(np.float32)


class UnionFind:
    """路径压缩并查集(小规模聚类用)。"""

    __slots__ = ("parent",)

    def __init__(self, count):
        self.parent = list(range(count))

    def find(self, node):
        parent = self.parent
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(self, a, b):
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a
