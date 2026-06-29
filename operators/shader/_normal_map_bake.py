"""法线贴图烘焙的共享底层。

正向（法线贴图 → 自定义法线）与反向（自定义法线 → 法线贴图）两个算子共用同一套
节点查找、像素读写、切线基底提取，从而保证两者互为精确逆变换：
反向取 `ts = TBNᵀ · os`，正向取 `os = TBN · ts`，TBN 正交 → 往返无损。

本模块只放无副作用的纯工具函数，不注册任何算子。
"""

import bpy
import numpy


def find_normal_image_node(material):
    """在材质节点树中查找承载法线贴图的图像纹理节点。

    优先匹配名字含 "normal"、或其输出连向名字含 "normal" 的节点；
    找不到则回退到第一个图像纹理节点。返回节点或 None。
    """
    if not material or not material.use_nodes:
        return None

    nodes = material.node_tree.nodes

    for node in nodes:
        if node.type != 'TEX_IMAGE':
            continue
        name_hit = "normal" in node.name.lower()
        link_hit = (
            bool(node.outputs[0].links)
            and "normal" in node.outputs[0].links[0].to_node.name.lower()
        )
        if name_hit or link_hit:
            return node

    for node in nodes:
        if node.type == 'TEX_IMAGE':
            return node

    return None


def read_image_pixels(image):
    """把图像像素极速读入 (height, width, 4) 的 float32 数组。"""
    width, height = image.size
    flat = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(flat)
    return flat.reshape((height, width, 4))


def write_image_pixels(image, pixel_matrix):
    """把 (height, width, 4) 数组极速写回图像并刷新。"""
    image.pixels.foreach_set(numpy.ascontiguousarray(pixel_matrix, dtype=numpy.float32).reshape(-1))
    image.update()


def clear_custom_split_normals(context, obj):
    """清空物体的自定义拆分法线（兼容 Blender 4.1 / 4.2+ / 5.x）。

    优先用 customdata_custom_splitnormals_clear 算子；上下文没对齐时退回
    进入编辑模式全选再清空的稳妥路径。结束后恢复原来的激活物体。
    """
    previous_active = context.view_layer.objects.active
    context.view_layer.objects.active = obj
    try:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    except RuntimeError:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
        bpy.ops.object.mode_set(mode='OBJECT')
    finally:
        context.view_layer.objects.active = previous_active


def force_all_smooth(mesh):
    """强制网格所有面平滑着色，作为切线空间计算的基准面。"""
    smooth_flags = numpy.ones(len(mesh.polygons), dtype=numpy.bool_)
    mesh.polygons.foreach_set("use_smooth", smooth_flags)


def read_loop_tangent_basis(mesh):
    """计算并极速读取每个 loop 的切线基底（法线 / 切线 / 副切线）。

    调用方需先把 mesh 调到目标基准态（已清自定义法线、已设平滑），本函数负责
    calc_tangents 并返回三组 (loop_count, 3) 的 float32 数组。
    副切线按 Blender 约定 `bitangent = bitangent_sign * cross(normal, tangent)`。
    """
    mesh.calc_tangents()

    loop_count = len(mesh.loops)

    normals = numpy.empty(loop_count * 3, dtype=numpy.float32)
    mesh.loops.foreach_get("normal", normals)
    normals = normals.reshape((loop_count, 3))

    tangents = numpy.empty(loop_count * 3, dtype=numpy.float32)
    mesh.loops.foreach_get("tangent", tangents)
    tangents = tangents.reshape((loop_count, 3))

    signs = numpy.empty(loop_count, dtype=numpy.float32)
    mesh.loops.foreach_get("bitangent_sign", signs)

    bitangents = numpy.cross(normals, tangents) * signs[:, None]

    return normals, tangents, bitangents


def read_current_corner_normals(mesh):
    """读取网格当前实际着色用的角法线（含自定义法线 / 平滑标记的最终结果）。"""
    loop_count = len(mesh.loops)
    out = numpy.empty(loop_count * 3, dtype=numpy.float32)
    corner = getattr(mesh, "corner_normals", None)
    if corner is not None and len(corner) == loop_count:
        corner.foreach_get("vector", out)
    else:
        mesh.loops.foreach_get("normal", out)
    return out.reshape((loop_count, 3))


def read_loop_uvs(mesh):
    """读取激活 UV 层每个 loop 的坐标，返回 (loop_count, 2) 的 float32 数组。"""
    uv_layer = mesh.uv_layers.active
    loop_count = len(mesh.loops)
    uvs = numpy.empty(loop_count * 2, dtype=numpy.float32)
    uv_layer.data.foreach_get("uv", uvs)
    return uvs.reshape((loop_count, 2))


def normalize_rows(vectors):
    """对 (N, 3) 数组逐行归一化，零向量保持为零。"""
    lengths = numpy.linalg.norm(vectors, axis=1, keepdims=True)
    lengths[lengths == 0.0] = 1.0
    return vectors / lengths
