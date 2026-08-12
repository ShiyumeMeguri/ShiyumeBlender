"""目标排布解析：算出每个 loop 在输出图上的落点。

两种坐标源归一到同一件东西——每 loop 一个 (u, v)：

- ``UV_LAYER``：直接读目标 UV 层。
- ``MESH_XY``：展平网格**求值后**的世界 XY（修改器、形态键、物体变换都已生效）。
  这与 ortho_scale=1、对准 (0.5, 0.5) 的正交顶视相机是同一个投影——世界 X/Y 就是画面
  归一化坐标，所以"把网格改成什么样，贴图就排成什么样"。
"""

import numpy as np

from . import mesh_bind

# 展平物体上记录来源物体名的自定义属性，由「网格转UV」写入
SOURCE_OBJECT_PROP = "shiyume_uv_source"


def resolve_loop_uv(context, obj, settings):
    """返回该物体每个 loop 的目标坐标 (loop_count, 2) float32；解析不了返回 None。"""
    mesh = obj.data
    if settings.target_space == 'UV_LAYER':
        return mesh_bind.read_uv(mesh, settings.target_uv)

    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        if len(evaluated_mesh.loops) != len(mesh.loops):
            return None

        positions = np.empty(len(evaluated_mesh.vertices) * 3, dtype=np.float32)
        evaluated_mesh.vertices.foreach_get("co", positions)
        positions = positions.reshape(-1, 3)

        matrix = np.asarray(evaluated.matrix_world, dtype=np.float32)
        world = positions @ matrix[:3, :3].T + matrix[:3, 3]

        loop_vertices = np.empty(len(evaluated_mesh.loops), dtype=np.int32)
        evaluated_mesh.loops.foreach_get("vertex_index", loop_vertices)
        return np.ascontiguousarray(world[loop_vertices, 0:2])
    finally:
        evaluated.to_mesh_clear()


def write_uv_layer(mesh, name, loop_uv):
    """把每 loop 坐标写进指定 UV 层（不存在就建），返回是否成功。"""
    if len(mesh.loops) != loop_uv.shape[0]:
        return False
    layer = mesh.uv_layers.get(name)
    if layer is None:
        layer = mesh.uv_layers.new(name=name, do_init=False)
    mesh.attributes[layer.name].data.foreach_set(
        "vector", np.ascontiguousarray(loop_uv, dtype=np.float32).reshape(-1))
    mesh.update()
    return True
