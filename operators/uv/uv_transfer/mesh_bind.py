"""网格适配层：把 mesh 的 loop 数据取成按材质槽分组的三角形，以及逐 loop 的 UV 层数组。"""

import numpy as np


def render_uv_name(mesh):
    """返回渲染激活的 UV 层名——没有显式标记时退到激活层。"""
    for layer in mesh.uv_layers:
        if layer.active_render:
            return layer.name
    active = mesh.uv_layers.active
    return active.name if active else ""


def read_uv(mesh, name):
    """按名字读取 CORNER 域的 FLOAT2 属性（UV 层），返回 (loop_count, 2) float32。"""
    attribute = mesh.attributes.get(name)
    if attribute is None or attribute.domain != 'CORNER' or attribute.data_type != 'FLOAT2':
        return None
    values = np.empty(len(attribute.data) * 2, dtype=np.float32)
    attribute.data.foreach_get("vector", values)
    return values.reshape(-1, 2)


def read_all_uv(mesh):
    """网格上全部 UV 层，{层名: (loop_count, 2) float32}。"""
    layers = {}
    for layer in mesh.uv_layers:
        values = read_uv(mesh, layer.name)
        if values is not None:
            layers[layer.name] = values
    return layers


def loops_by_material(mesh):
    """返回 {material_index: (T, 3) int64}，每个三角形的三个 loop 下标。"""
    # 4.0 需要显式三角化，4.1+ 起访问 loop_triangles 会自动构建
    if hasattr(mesh, "calc_loop_triangles"):
        mesh.calc_loop_triangles()

    triangle_count = len(mesh.loop_triangles)
    if triangle_count == 0:
        return {}

    loops = np.empty(triangle_count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    loops = loops.reshape(-1, 3).astype(np.int64)

    material_indices = np.empty(triangle_count, dtype=np.int32)
    mesh.loop_triangles.foreach_get("material_index", material_indices)

    return {int(index): loops[material_indices == index] for index in np.unique(material_indices)}
