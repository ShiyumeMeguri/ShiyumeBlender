"""平滑轮廓法线核心。

按空间位置分组聚合角法线(跨 UV 缝 / 材质缝 / 硬边拆分的重合顶点会被归为同组),
得到处处连续的平滑法线场 —— 二次元描边(背面外扩)的标准前置数据。
全程 NumPy:分组用整数量化 + unique,聚合用 bincount。
"""

import numpy as np

from . import batch

_POSITION_QUANT = 1.0e6  # 位置量化精度 1e-6 米


def smoothed_corner_normals(mesh, weight_mode='ANGLE'):
    """计算每个 loop 的平滑法线 (L, 3)。

    以当前实际着色角法线为输入(尊重既有的平滑 / 硬边 / 自定义法线),
    把空间位置重合的所有角聚为一组做加权平均:
    - ANGLE   按角的张角加权(几何正确,推荐);
    - UNIFORM 算术平均。
    """
    loop_vertex = batch.read_int(mesh.loops, "vertex_index")
    normals = batch.read_corner_normals(mesh)

    positions_per_vertex = batch.read_float(mesh.vertices, "co", 3)
    positions = positions_per_vertex[loop_vertex]

    if weight_mode == 'ANGLE':
        previous_loops, next_loops = batch.loop_neighbors(mesh)
        to_previous = positions_per_vertex[loop_vertex[previous_loops]] - positions
        to_next = positions_per_vertex[loop_vertex[next_loops]] - positions
        to_previous = batch.normalize_rows(to_previous)
        to_next = batch.normalize_rows(to_next)
        cosine = np.clip((to_previous * to_next).sum(axis=1), -1.0, 1.0)
        weights = np.arccos(cosine).astype(np.float64)
    else:
        weights = np.ones(len(mesh.loops), dtype=np.float64)

    quantized = np.round(positions.astype(np.float64) * _POSITION_QUANT).astype(np.int64)
    inverse, group_count = batch.group_rows(quantized)
    return batch.group_weighted_mean_normalized(inverse, group_count, normals, weights)


def tangent_space_transform(mesh, object_space_normals):
    """把 (L, 3) 物体空间法线变换到切线空间。

    基底约定:N = 顶点法线,T = loop 切线,B = N x T(不乘 bitangent 符号),
    与常见引擎侧描边采样约定一致。调用前需保证 calc_tangents 已成功。
    """
    loop_vertex = batch.read_int(mesh.loops, "vertex_index")
    tangents = batch.read_float(mesh.loops, "tangent", 3)
    vertex_normals = batch.read_float(mesh.vertex_normals, "vector", 3)[loop_vertex]
    bitangents = np.cross(vertex_normals, tangents)

    tangent_space = np.stack(
        (
            (tangents * object_space_normals).sum(axis=1),
            (bitangents * object_space_normals).sum(axis=1),
            (vertex_normals * object_space_normals).sum(axis=1),
        ),
        axis=1,
    )
    return batch.normalize_rows(tangent_space)


def octahedral_encode(normals):
    """八面体编码 (N, 3) -> (N, 2),分量式符号处理,与 Unity SRP 解码严格互逆。"""
    scale = np.maximum(np.abs(normals).sum(axis=1, keepdims=True), 1e-6)
    folded = normals / scale
    t = np.clip(-folded[:, 2:3], 0.0, 1.0)
    xy = folded[:, :2]
    return xy + np.where(xy >= 0.0, t, -t)


def pack_octahedral_into_uv(mesh, object_space_normals, uv_layer_name):
    """物体空间法线 → 切线空间 → 八面体编码 → 写入指定 UV 层(不存在则新建)。

    需要激活 UV(切线基底)与纯三角/四边面;成功返回 None,失败返回错误信息。
    """
    if mesh.uv_layers.active is None:
        return "没有 UV,无法解算切线空间"
    try:
        mesh.calc_tangents()
    except RuntimeError as error:
        return f"切线计算失败(存在多边形面?): {error}"

    tangent_space = tangent_space_transform(mesh, object_space_normals)
    encoded = octahedral_encode(tangent_space)

    uv_layer = mesh.uv_layers.get(uv_layer_name)
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name=uv_layer_name, do_init=False)
    if uv_layer is None:
        return "UV 层已满(上限 8 个)"
    batch.write_float(uv_layer.data, "uv", encoded)
    mesh.update()
    return None
