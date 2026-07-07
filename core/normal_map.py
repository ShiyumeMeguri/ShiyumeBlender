"""法线贴图烘焙核。

正向(法线贴图 → 自定义法线)与反向(自定义法线 → 法线贴图)两个算子共用同一套
节点查找、像素读写、切线基底提取、光栅化与边缘外扩,从而保证两者互为精确逆变换:
反向取 `ts = TBNᵀ · os`,正向取 `os = TBN · ts`,TBN 正交 → 往返无损。
"""

import bpy
import numpy as np

from . import batch


# ---------------------------------------------------------------------------
# 材质 / 图像
# ---------------------------------------------------------------------------

def find_normal_image_node(material):
    """在材质节点树中查找承载法线贴图的图像纹理节点。

    优先匹配名字含 "normal"、或其输出连向名字含 "normal" 的节点;
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
    flat = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(flat)
    return flat.reshape((height, width, 4))


def write_image_pixels(image, pixel_matrix):
    """把 (height, width, 4) 数组极速写回图像并刷新。"""
    image.pixels.foreach_set(np.ascontiguousarray(pixel_matrix, dtype=np.float32).reshape(-1))
    image.update()


# ---------------------------------------------------------------------------
# 网格基准态
# ---------------------------------------------------------------------------

def clear_custom_split_normals(context, obj):
    """清空物体的自定义拆分法线(兼容 Blender 4.1 / 4.2+ / 5.x)。

    优先用 customdata_custom_splitnormals_clear 算子;上下文没对齐时退回
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
    """强制网格所有面平滑着色,作为切线空间计算的基准面。"""
    smooth_flags = np.ones(len(mesh.polygons), dtype=np.bool_)
    mesh.polygons.foreach_set("use_smooth", smooth_flags)


def read_loop_tangent_basis(mesh):
    """计算并极速读取每个 loop 的切线基底(法线 / 切线 / 副切线)。

    调用方需先把 mesh 调到目标基准态(已清自定义法线、已设平滑),本函数负责
    calc_tangents 并返回三组 (loop_count, 3) 的 float32 数组。
    副切线按 Blender 约定 `bitangent = bitangent_sign * cross(normal, tangent)`。
    """
    mesh.calc_tangents()

    normals = batch.read_float(mesh.loops, "normal", 3)
    tangents = batch.read_float(mesh.loops, "tangent", 3)
    signs = batch.read_float(mesh.loops, "bitangent_sign", 1)
    bitangents = np.cross(normals, tangents) * signs[:, None]

    return normals, tangents, bitangents


# ---------------------------------------------------------------------------
# 光栅化 / 外扩
# ---------------------------------------------------------------------------

def new_flat_buffer(width, height):
    """新建像素缓冲,整张预填平面法线 (0.5, 0.5, 1.0),作为未覆盖区域的底色。"""
    pixel_matrix = np.empty((height, width, 4), dtype=np.float32)
    pixel_matrix[..., 0] = 0.5
    pixel_matrix[..., 1] = 0.5
    pixel_matrix[..., 2] = 1.0
    pixel_matrix[..., 3] = 1.0
    return pixel_matrix


def rasterize_into(mesh, tangent_space, pixel_x, pixel_y, width, height, flip_green, pixel_matrix, coverage):
    """逐三角形把切线空间法线 barycentric 光栅化进已有的像素矩阵 / 覆盖掩码。

    每个三角形的包围盒很小,内部用 NumPy 向量化求 barycentric,是 Python 层唯一的循环。
    """
    mesh.calc_loop_triangles()
    triangle_count = len(mesh.loop_triangles)
    triangle_loops = np.empty(triangle_count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", triangle_loops)
    triangle_loops = triangle_loops.reshape((triangle_count, 3))

    for index0, index1, index2 in triangle_loops:
        _fill_triangle(
            pixel_matrix, coverage,
            pixel_x[index0], pixel_y[index0],
            pixel_x[index1], pixel_y[index1],
            pixel_x[index2], pixel_y[index2],
            tangent_space[index0], tangent_space[index1], tangent_space[index2],
            width, height, flip_green,
        )


def _fill_triangle(pixel_matrix, coverage, x0, y0, x1, y1, x2, y2, normal0, normal1, normal2, width, height, flip_green):
    """填充单个三角形覆盖到的所有纹素:barycentric 插值切线空间法线 → 编码写入。"""
    min_column = max(int(np.floor(min(x0, x1, x2))), 0)
    max_column = min(int(np.ceil(max(x0, x1, x2))), width - 1)
    min_row = max(int(np.floor(min(y0, y1, y2))), 0)
    max_row = min(int(np.ceil(max(y0, y1, y2))), height - 1)
    if min_column > max_column or min_row > max_row:
        return

    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denominator) < 1e-12:
        return
    inverse = 1.0 / denominator

    columns = np.arange(min_column, max_column + 1)
    rows = np.arange(min_row, max_row + 1)
    grid_column, grid_row = np.meshgrid(columns, rows)
    sample_x = grid_column.astype(np.float32)
    sample_y = grid_row.astype(np.float32)

    weight0 = ((y1 - y2) * (sample_x - x2) + (x2 - x1) * (sample_y - y2)) * inverse
    weight1 = ((y2 - y0) * (sample_x - x2) + (x0 - x2) * (sample_y - y2)) * inverse
    weight2 = 1.0 - weight0 - weight1

    # 留极小负容差,避免相邻三角形共享边上出现一像素裂缝。
    epsilon = -1e-4
    inside = (weight0 >= epsilon) & (weight1 >= epsilon) & (weight2 >= epsilon)
    if not inside.any():
        return

    selected_rows = grid_row[inside]
    selected_columns = grid_column[inside]
    bary0 = weight0[inside]
    bary1 = weight1[inside]
    bary2 = weight2[inside]

    interp_x = bary0 * normal0[0] + bary1 * normal1[0] + bary2 * normal2[0]
    interp_y = bary0 * normal0[1] + bary1 * normal1[1] + bary2 * normal2[1]
    interp_z = bary0 * normal0[2] + bary1 * normal1[2] + bary2 * normal2[2]

    inverse_length = 1.0 / np.sqrt(interp_x * interp_x + interp_y * interp_y + interp_z * interp_z + 1e-20)
    interp_x *= inverse_length
    interp_y *= inverse_length
    interp_z *= inverse_length

    if flip_green:
        interp_y = -interp_y

    pixel_matrix[selected_rows, selected_columns, 0] = interp_x * 0.5 + 0.5
    pixel_matrix[selected_rows, selected_columns, 1] = interp_y * 0.5 + 0.5
    pixel_matrix[selected_rows, selected_columns, 2] = interp_z * 0.5 + 0.5
    pixel_matrix[selected_rows, selected_columns, 3] = 1.0
    coverage[selected_rows, selected_columns] = True


def dilate(pixel_matrix, coverage, margin):
    """把已覆盖像素向未覆盖邻居外扩 margin 圈(8 邻域最近邻填充),消除 UV 接缝。"""
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
    current_coverage = coverage
    for _ in range(margin):
        if current_coverage.all():
            break
        # 每圈以本圈起点为快照取源,避免本圈新填的值再被本圈引用。
        base_pixels = pixel_matrix.copy()
        base_coverage = current_coverage
        next_coverage = current_coverage.copy()
        for offset_row, offset_column in offsets:
            neighbor_coverage = _shift(base_coverage, offset_row, offset_column)
            need = neighbor_coverage & (~next_coverage)
            if not need.any():
                continue
            neighbor_pixels = _shift(base_pixels, offset_row, offset_column)
            target_rows, target_columns = np.nonzero(need)
            pixel_matrix[target_rows, target_columns, :] = neighbor_pixels[target_rows, target_columns, :]
            next_coverage[target_rows, target_columns] = True
        current_coverage = next_coverage


def _shift(array, offset_row, offset_column):
    """返回 result[r, c] = array[r + offset_row, c + offset_column],越界处补零。"""
    height, width = array.shape[0], array.shape[1]
    result = np.zeros_like(array)
    source_row0 = max(0, offset_row)
    source_row1 = min(height, height + offset_row)
    source_column0 = max(0, offset_column)
    source_column1 = min(width, width + offset_column)
    span_rows = source_row1 - source_row0
    span_columns = source_column1 - source_column0
    if span_rows <= 0 or span_columns <= 0:
        return result
    target_row0 = max(0, -offset_row)
    target_column0 = max(0, -offset_column)
    result[target_row0:target_row0 + span_rows, target_column0:target_column0 + span_columns] = \
        array[source_row0:source_row1, source_column0:source_column1]
    return result
