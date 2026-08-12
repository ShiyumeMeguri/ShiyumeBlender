"""目标排布解析：算出网格三角形在输出图上的落点。

两种坐标源：

- ``UV_LAYER``：直接读目标 UV 层。
- ``MESH_XY``：展平网格**求值后**的世界 XY（修改器、形态键、物体变换都已生效）。
  这与 ortho_scale=1、对准 (0.5, 0.5) 的正交顶视相机是同一个投影——"把网格改成
  什么样，贴图就排成什么样"。

产出分两份：``triangles`` 供重采样，直接取自求值后的网格，修改器怎么改拓扑都行；
``base_loop_uv`` 是同一排布在**原始网格**上的逐 loop 表示，只有烘焙的临时 UV 层与
排布写回需要它，拓扑被改过就给不出来。
"""

import numpy as np

from . import mesh_bind

# 展平物体上记录来源物体名的自定义属性，由「网格转UV」写入
SOURCE_OBJECT_PROP = "shiyume_uv_source"


class Layout:
    def __init__(self, triangles, base_loop_uv):
        self.triangles = triangles
        self.base_loop_uv = base_loop_uv


def _world_loop_xy(evaluated, evaluated_mesh):
    """求值后网格的逐 loop 世界 XY —— 正交顶视投影的画面坐标。"""
    positions = np.empty(len(evaluated_mesh.vertices) * 3, dtype=np.float32)
    evaluated_mesh.vertices.foreach_get("co", positions)
    positions = positions.reshape(-1, 3)

    matrix = np.asarray(evaluated.matrix_world, dtype=np.float32)
    world = positions @ matrix[:3, :3].T + matrix[:3, 3]

    loop_vertices = np.empty(len(evaluated_mesh.loops), dtype=np.int32)
    evaluated_mesh.loops.foreach_get("vertex_index", loop_vertices)
    return np.ascontiguousarray(world[loop_vertices, 0:2])


def resolve(context, obj, settings):
    """解析该物体的目标排布；目标 UV 层不存在时返回 None。"""
    mesh = obj.data

    if settings.target_space == 'UV_LAYER':
        loop_uv = mesh_bind.read_uv(mesh, settings.target_uv)
        if loop_uv is None:
            return None
        triangles = mesh_bind.triangles_by_material(mesh, settings.source_uv, loop_uv)
        return Layout(triangles, loop_uv)

    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        loop_uv = _world_loop_xy(evaluated, evaluated_mesh)
        triangles = mesh_bind.triangles_by_material(
            evaluated_mesh, settings.source_uv, loop_uv)
        # 拓扑没被改动时，同一排布才能落回原始网格的 loop 上
        base_loop_uv = loop_uv if len(evaluated_mesh.loops) == len(mesh.loops) else None
        return Layout(triangles, base_loop_uv)
    finally:
        evaluated.to_mesh_clear()


def write_uv_layer(mesh, name, loop_uv):
    """把每 loop 坐标写进指定 UV 层（不存在就建），返回是否成功。"""
    if loop_uv is None or len(mesh.loops) != loop_uv.shape[0]:
        return False
    layer = mesh.uv_layers.get(name)
    if layer is None:
        layer = mesh.uv_layers.new(name=name, do_init=False)
    mesh.attributes[layer.name].data.foreach_set(
        "vector", np.ascontiguousarray(loop_uv, dtype=np.float32).reshape(-1))
    mesh.update()
    return True
