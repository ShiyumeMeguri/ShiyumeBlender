"""网格适配层：把 mesh 的 loop 数据取成按材质槽分组的三角形数组。"""

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
    if attribute is None:
        return None
    values = np.empty(len(attribute.data) * 2, dtype=np.float32)
    attribute.data.foreach_get("vector", values)
    return values.reshape(-1, 2)


def triangles_by_material(mesh, source_name, target_loop_uv):
    """返回 {material_index: (target_tris, source_tris)}，两者均为 (T, 3, 2) float32。

    target_loop_uv 是每 loop 的目标坐标，由 layout 模块解析——可能来自 UV 层，
    也可能来自展平网格的世界 XY，这里不关心它从哪来。
    """
    # 4.0 需要显式三角化，4.1+ 起访问 loop_triangles 会自动构建
    if hasattr(mesh, "calc_loop_triangles"):
        mesh.calc_loop_triangles()

    triangle_count = len(mesh.loop_triangles)
    if triangle_count == 0:
        return {}

    source_uv = read_uv(mesh, source_name)
    if source_uv is None or target_loop_uv is None:
        return {}
    if source_uv.shape[0] != target_loop_uv.shape[0]:
        return {}

    loops = np.empty(triangle_count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    loops = loops.reshape(-1, 3)

    material_indices = np.empty(triangle_count, dtype=np.int32)
    mesh.loop_triangles.foreach_get("material_index", material_indices)

    grouped = {}
    for material_index in np.unique(material_indices):
        selected = loops[material_indices == material_index]
        grouped[int(material_index)] = (
            target_loop_uv[selected],
            source_uv[selected],
        )
    return grouped
