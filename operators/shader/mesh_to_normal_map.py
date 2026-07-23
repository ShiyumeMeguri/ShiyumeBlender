import bpy
import numpy

from . import _normal_map_bake as bake_common


class SHIYUME_OT_MeshToNormalMap(bpy.types.Operator):
    """网格法线烘焙到贴图（反向：自定义法线 → 切线空间法线贴图）。

    对每个选中的网格，以其“清掉自定义法线、全平滑”的原始几何法线作为 base，读取当前
    自定义法线相对该 base 的差值，逐三角形 barycentric 光栅化进 UV。多个对象一起烘焙到
    同一张新建贴图（按名字复用，use_fake_user 保活），绝不覆盖材质里已有的任何贴图。
    与“法线贴图烘焙到网格”互为逆操作；全程在临时副本上取 base，不破坏原网格。"""
    bl_idname = "shiyume.mesh_to_normal_map"
    bl_label = "网格法线烘焙到贴图"
    bl_options = {'REGISTER', 'UNDO'}

    image_name: bpy.props.StringProperty(
        name="贴图名",
        default="Baked_Normal",
        description="烘焙目标贴图的数据块名；已存在同名贴图则复用并覆盖其内容",
    )
    image_size: bpy.props.IntProperty(
        name="贴图尺寸",
        default=2048, min=16, max=8192,
        description="新建贴图的边长（复用已存在贴图时若尺寸不符则缩放到此值）",
    )
    margin: bpy.props.IntProperty(
        name="边缘外扩",
        default=8, min=0, max=64,
        description="向 UV 岛外扩张的像素圈数，消除采样 / mipmap 接缝",
    )
    flip_green: bpy.props.BoolProperty(
        name="翻转绿色通道",
        default=False,
        description="按 DirectX 约定翻转 Y 分量；关闭则用 OpenGL 约定",
    )

    @classmethod
    def poll(cls, context):
        active = context.active_object
        if active is not None and active.type == 'MESH':
            return True
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        objects = self._gather_target_objects(context)
        if not objects:
            self.report({'ERROR'}, "没有带 UV 的网格被选中")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        image = self._resolve_new_image()
        width, height = image.size

        # 所有对象共享同一缓冲，逐个累加进去（后写覆盖先写，UV 重叠时以最后一个为准）。
        pixel_matrix = _new_flat_buffer(width, height)
        coverage = numpy.zeros((height, width), dtype=numpy.bool_)

        total_loops = 0
        for obj in objects:
            total_loops += self._bake_object(context, obj, pixel_matrix, coverage, width, height)

        # 边缘外扩，把已覆盖像素往 UV 岛外推，消除接缝。
        if self.margin > 0:
            _dilate(pixel_matrix, coverage, self.margin)

        # 写回贴图（法线贴图必须是 Non-Color）。
        image.colorspace_settings.name = 'Non-Color'
        bake_common.write_image_pixels(image, pixel_matrix)

        self.report(
            {'INFO'},
            f"已把 {len(objects)} 个对象 / {total_loops} 条法线烘焙到 {image.name} ({width}x{height})",
        )
        return {'FINISHED'}

    def _gather_target_objects(self, context):
        """收集所有带激活 UV 的选中网格；选区为空时退回活动对象。"""
        objects = [
            obj for obj in context.selected_objects
            if obj.type == 'MESH' and obj.data.uv_layers.active is not None
        ]
        if objects:
            return objects

        active = context.active_object
        if active is not None and active.type == 'MESH' and active.data.uv_layers.active is not None:
            return [active]
        return []

    def _resolve_new_image(self):
        """取烘焙目标贴图：按名字新建，已存在同名则复用（尺寸不符则缩放），绝不碰材质。"""
        image = bpy.data.images.get(self.image_name)
        if image is None:
            image = bpy.data.images.new(
                name=self.image_name,
                width=self.image_size,
                height=self.image_size,
                alpha=False,
                float_buffer=False,
            )
        elif tuple(image.size) != (self.image_size, self.image_size):
            image.scale(self.image_size, self.image_size)
        image.use_fake_user = True
        return image

    def _bake_object(self, context, obj, pixel_matrix, coverage, width, height):
        """把单个对象的自定义法线差值光栅化进共享缓冲，返回该对象的 loop 数。"""
        mesh = obj.data

        # 1. 当前实际角法线（含自定义法线），从原网格无损读取。
        current_normals = bake_common.read_current_corner_normals(mesh)

        # 2. base 切线基底：在临时副本上清自定义法线 + 全平滑，绝不污染原网格。
        normals, tangents, bitangents = self._base_tangent_basis(context, obj)

        # 3. 物体空间法线 → 切线空间：tx = T·os, ty = B·os, tz = N·os。
        tangent_space = numpy.stack(
            (
                numpy.sum(tangents * current_normals, axis=1),
                numpy.sum(bitangents * current_normals, axis=1),
                numpy.sum(normals * current_normals, axis=1),
            ),
            axis=1,
        )
        tangent_space = bake_common.normalize_rows(tangent_space)

        # 4. 逐 loop 的像素坐标（纹素中心落在整数坐标，故 -0.5 对齐）。
        uvs = bake_common.read_loop_uvs(mesh)
        pixel_x = uvs[:, 0] * width - 0.5
        pixel_y = uvs[:, 1] * height - 0.5

        # 5. 三角形 → 像素：barycentric 插值 + 光栅化进共享缓冲。
        _rasterize_into(
            mesh, tangent_space, pixel_x, pixel_y, width, height, self.flip_green,
            pixel_matrix, coverage,
        )
        return len(mesh.loops)

    def _base_tangent_basis(self, context, obj):
        """在临时副本上构造 base（清自定义法线 + 全平滑），返回切线基底数组。

        副本与原网格拓扑完全一致（loop 序号一一对应），用完即删，原网格毫发无损。
        """
        temp_obj = obj.copy()
        temp_obj.data = obj.data.copy()
        context.collection.objects.link(temp_obj)
        try:
            bake_common.clear_custom_split_normals(context, temp_obj)
            bake_common.force_all_smooth(temp_obj.data)
            return bake_common.read_loop_tangent_basis(temp_obj.data)
        finally:
            temp_mesh = temp_obj.data
            bpy.data.objects.remove(temp_obj)
            bpy.data.meshes.remove(temp_mesh)


def _new_flat_buffer(width, height):
    """新建像素缓冲，整张预填平面法线 (0.5, 0.5, 1.0)，作为未覆盖区域的底色。"""
    pixel_matrix = numpy.empty((height, width, 4), dtype=numpy.float32)
    pixel_matrix[..., 0] = 0.5
    pixel_matrix[..., 1] = 0.5
    pixel_matrix[..., 2] = 1.0
    pixel_matrix[..., 3] = 1.0
    return pixel_matrix


def _rasterize_into(mesh, tangent_space, pixel_x, pixel_y, width, height, flip_green, pixel_matrix, coverage):
    """逐三角形把切线空间法线 barycentric 光栅化进已有的像素矩阵 / 覆盖掩码。

    每个三角形的包围盒很小，内部用 NumPy 向量化求 barycentric，是 Python 层唯一的循环。
    """
    mesh.calc_loop_triangles()
    triangle_count = len(mesh.loop_triangles)
    triangle_loops = numpy.empty(triangle_count * 3, dtype=numpy.int32)
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
    """填充单个三角形覆盖到的所有纹素：barycentric 插值切线空间法线 → 编码写入。"""
    min_column = max(int(numpy.floor(min(x0, x1, x2))), 0)
    max_column = min(int(numpy.ceil(max(x0, x1, x2))), width - 1)
    min_row = max(int(numpy.floor(min(y0, y1, y2))), 0)
    max_row = min(int(numpy.ceil(max(y0, y1, y2))), height - 1)
    if min_column > max_column or min_row > max_row:
        return

    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denominator) < 1e-12:
        return
    inverse = 1.0 / denominator

    columns = numpy.arange(min_column, max_column + 1)
    rows = numpy.arange(min_row, max_row + 1)
    grid_column, grid_row = numpy.meshgrid(columns, rows)
    sample_x = grid_column.astype(numpy.float32)
    sample_y = grid_row.astype(numpy.float32)

    weight0 = ((y1 - y2) * (sample_x - x2) + (x2 - x1) * (sample_y - y2)) * inverse
    weight1 = ((y2 - y0) * (sample_x - x2) + (x0 - x2) * (sample_y - y2)) * inverse
    weight2 = 1.0 - weight0 - weight1

    # 留极小负容差，避免相邻三角形共享边上出现一像素裂缝。
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

    inverse_length = 1.0 / numpy.sqrt(interp_x * interp_x + interp_y * interp_y + interp_z * interp_z + 1e-20)
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


def _dilate(pixel_matrix, coverage, margin):
    """把已覆盖像素向未覆盖邻居外扩 margin 圈（8 邻域最近邻填充），消除 UV 接缝。"""
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
    current_coverage = coverage
    for _ in range(margin):
        if current_coverage.all():
            break
        # 每圈以本圈起点为快照取源，避免本圈新填的值再被本圈引用。
        base_pixels = pixel_matrix.copy()
        base_coverage = current_coverage
        next_coverage = current_coverage.copy()
        for offset_row, offset_column in offsets:
            neighbor_coverage = _shift(base_coverage, offset_row, offset_column)
            need = neighbor_coverage & (~next_coverage)
            if not need.any():
                continue
            neighbor_pixels = _shift(base_pixels, offset_row, offset_column)
            target_rows, target_columns = numpy.nonzero(need)
            pixel_matrix[target_rows, target_columns, :] = neighbor_pixels[target_rows, target_columns, :]
            next_coverage[target_rows, target_columns] = True
        current_coverage = next_coverage


def _shift(array, offset_row, offset_column):
    """返回 result[r, c] = array[r + offset_row, c + offset_column]，越界处补零。"""
    height, width = array.shape[0], array.shape[1]
    result = numpy.zeros_like(array)
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
