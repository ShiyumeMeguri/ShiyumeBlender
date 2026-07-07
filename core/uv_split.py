"""UV 不连续边检测(全 NumPy)与拆分应用。

"网格转 UV"一族的共同前置:凡 UV 缝(seam)、非双面边、或两侧面在共享顶点上
UV 坐标不一致的边,都要拆开,拆分后的网格顶点才能与 UV 顶点一一对应。
检测在 Mesh 数据层向量化完成,bmesh 只负责执行拆分。
"""

import bmesh
import numpy as np

from . import batch


def uv_discontinuous_edge_indices(mesh, uv_name=None, epsilon=1e-6):
    """返回需要拆分的边下标数组(int32)。

    规则与语义:seam 边、loop 数不等于 2 的边(边界 / 非流形 / 线框)、
    以及两侧 loop 在共享顶点处 UV 坐标差超过 epsilon 的边。
    """
    edge_count = len(mesh.edges)
    if edge_count == 0:
        return np.empty(0, dtype=np.int32)

    seam = batch.read_bool(mesh.edges, "use_seam")

    loop_count = len(mesh.loops)
    if loop_count == 0:
        return np.flatnonzero(seam).astype(np.int32)

    if uv_name is not None:
        uv_layer = mesh.uv_layers.get(uv_name)
    else:
        uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return np.flatnonzero(seam).astype(np.int32)

    loop_vertex = batch.read_int(mesh.loops, "vertex_index")
    loop_edge = batch.read_int(mesh.loops, "edge_index")
    uv = batch.read_uvs(mesh, uv_layer)
    _, next_loops = batch.loop_neighbors(mesh)

    # 按边号聚拢 loop:排序后按段切
    order = np.argsort(loop_edge, kind='stable')
    sorted_edges = loop_edge[order]
    segment_starts = np.flatnonzero(np.r_[True, sorted_edges[1:] != sorted_edges[:-1]])
    segment_counts = np.diff(np.r_[segment_starts, loop_count])

    # loop 数恰为 2 的边:比较两侧 UV;其余(含无 loop 的线框边)一律拆
    pair_mask = segment_counts == 2
    pair_edge_indices = sorted_edges[segment_starts[pair_mask]]
    loop_a = order[segment_starts[pair_mask]]
    loop_b = order[segment_starts[pair_mask] + 1]

    # loop 覆盖的有向边为 (vert[loop], vert[next(loop)])
    a_start = loop_vertex[loop_a]
    a_end = loop_vertex[next_loops[loop_a]]
    b_start = loop_vertex[loop_b]
    b_end = loop_vertex[next_loops[loop_b]]

    epsilon_squared = epsilon * epsilon

    def uv_close(loop_x, loop_y):
        difference = uv[loop_x] - uv[loop_y]
        return (difference * difference).sum(axis=1) < epsilon_squared

    opposite_winding = (a_start == b_end) & (a_end == b_start)
    same_winding = (a_start == b_start) & (a_end == b_end)
    matched_opposite = uv_close(loop_a, next_loops[loop_b]) & uv_close(next_loops[loop_a], loop_b)
    matched_same = uv_close(loop_a, loop_b) & uv_close(next_loops[loop_a], next_loops[loop_b])
    matched = np.where(opposite_winding, matched_opposite,
                       np.where(same_winding, matched_same, False))

    non_pair_mask = np.ones(edge_count, dtype=np.bool_)
    non_pair_mask[pair_edge_indices] = False

    split_mask = non_pair_mask | seam
    split_mask[pair_edge_indices[~matched]] = True
    return np.flatnonzero(split_mask).astype(np.int32)


def split_mesh_edges(mesh, edge_indices):
    """按边下标在网格上执行拆分(会清空形态键以外的自定义层保持原样)。"""
    if len(edge_indices) == 0:
        return 0
    working = bmesh.new()
    working.from_mesh(mesh)
    working.edges.ensure_lookup_table()
    edges = [working.edges[int(index)] for index in edge_indices]
    bmesh.ops.split_edges(working, edges=edges)
    working.to_mesh(mesh)
    working.free()
    mesh.update()
    return len(edges)
