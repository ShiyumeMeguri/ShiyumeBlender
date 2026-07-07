"""网格切割 / 重建:等距平面切割(发片工作流)与参考拓扑重建。"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector, kdtree

from ..core import batch, compat


# ---------------------------------------------------------------------------
# 等距切割
# ---------------------------------------------------------------------------

class SHIYUME_OT_GridCut(bpy.types.Operator):
    """按世界坐标等距切割选中面并溶解旧的内部分割边。
    发片等距工作流专用:配合「网格UV同步」生成的 UV 平面网格,
    把不均匀的发片重新切成等距条带,同时保持轮廓与 UV 缝完整"""
    bl_idname = "shiyume.grid_cut"
    bl_label = "网格等距切割"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(
        name="轴向",
        items=[
            ('X', "X", "沿 X 轴方向切割(生成竖向切线)"),
            ('Y', "Y", "沿 Y 轴方向切割(生成横向切线)"),
        ],
        default='X',
    )
    interval: bpy.props.FloatProperty(
        name="间隔", default=0.01, min=0.0001, unit='LENGTH',
        description="切割间距(世界坐标,自动对齐全局网格)",
    )
    dissolve_old: bpy.props.BoolProperty(
        name="溶解旧边", default=True,
        description="切割后溶解对应轴向上的旧内部边(保留轮廓与 UV 缝)",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.row().prop(self, "axis", expand=True)
        layout.prop(self, "interval")
        layout.prop(self, "dissolve_old")

    def _process_object(self, obj, axis_index):
        """单个物体:标记旧边 → 逐位置切割 → 溶解旧边。返回 (切割数, 溶解边数)。"""
        mesh = obj.data
        working = bmesh.from_edit_mesh(mesh)
        working.faces.ensure_lookup_table()
        working.edges.ensure_lookup_table()

        selected_faces = [face for face in working.faces if face.select]
        if not selected_faces:
            return 0, 0

        matrix = obj.matrix_world
        matrix_inverse = matrix.inverted()

        tag_key = "_grid_cut_old"
        tag_layer = working.edges.layers.int.get(tag_key)
        if tag_layer is None:
            tag_layer = working.edges.layers.int.new(tag_key)
        for edge in working.edges:
            edge[tag_layer] = 0

        # 切割前:垂直于切割轴的旧内部边标记待溶解(跳过轮廓 / 非流形 / UV 缝)
        marked_count = 0
        if self.dissolve_old:
            for edge in working.edges:
                if edge.is_boundary or not edge.is_manifold or edge.seam:
                    continue
                if not (edge.verts[0].select or edge.verts[1].select):
                    continue
                position_a = (matrix @ edge.verts[0].co)[axis_index]
                position_b = (matrix @ edge.verts[1].co)[axis_index]
                if abs(position_b - position_a) < 1e-5:
                    edge[tag_layer] = 1
                    marked_count += 1

        # 选中面在目标轴上的世界坐标范围
        axis_values = [
            (matrix @ vertex.co)[axis_index]
            for face in selected_faces
            for vertex in face.verts
        ]
        minimum = min(axis_values)
        maximum = max(axis_values)

        # 对齐到全局网格
        start = math.ceil(minimum / self.interval) * self.interval
        if abs(start - minimum) < 1e-6:
            start += self.interval

        cut_positions = []
        position = start
        while position < maximum - 1e-6:
            cut_positions.append(position)
            position += self.interval

        if not cut_positions and marked_count == 0:
            working.edges.layers.int.remove(tag_layer)
            return 0, 0

        normal_world = Vector((0, 0, 0))
        normal_world[axis_index] = 1.0
        normal_local = (matrix_inverse.to_3x3() @ normal_world).normalized()

        cut_count = 0
        for cut_position in cut_positions:
            point_world = Vector((0, 0, 0))
            point_world[axis_index] = cut_position
            point_local = matrix_inverse @ point_world

            geometry = (
                [vertex for vertex in working.verts if vertex.select]
                + [edge for edge in working.edges if edge.select]
                + [face for face in working.faces if face.select]
            )
            if not geometry:
                break

            result = bmesh.ops.bisect_plane(
                working,
                geom=geometry,
                dist=0.0001,
                plane_co=point_local,
                plane_no=normal_local,
                clear_outer=False,
                clear_inner=False,
            )

            # 切割平面上的边清除待溶解标记(切口即新边界)
            cut_vertices = set()
            for element in result['geom_cut']:
                if isinstance(element, bmesh.types.BMVert):
                    cut_vertices.add(element)
                elif isinstance(element, bmesh.types.BMEdge):
                    element[tag_layer] = 0
                    cut_vertices.add(element.verts[0])
                    cut_vertices.add(element.verts[1])

            # 两端都落在切割平面上的既有边同样豁免
            for vertex in cut_vertices:
                for edge in vertex.link_edges:
                    if edge.verts[0] in cut_vertices and edge.verts[1] in cut_vertices:
                        edge[tag_layer] = 0

            # bisect 产生的新面可能失选,补选保证后续切割不漏区域
            for element in result['geom_cut']:
                element.select = True
                if isinstance(element, bmesh.types.BMVert):
                    for face in element.link_faces:
                        face.select = True
                    for edge in element.link_edges:
                        edge.select = True

            cut_count += 1

        dissolved_count = 0
        if self.dissolve_old and marked_count > 0:
            edges_to_dissolve = [
                edge for edge in working.edges
                if edge.is_valid and edge[tag_layer] == 1
            ]
            if edges_to_dissolve:
                bmesh.ops.dissolve_edges(working, edges=edges_to_dissolve, use_verts=True)
                dissolved_count = len(edges_to_dissolve)

        tag_layer = working.edges.layers.int.get(tag_key)
        if tag_layer is not None:
            working.edges.layers.int.remove(tag_layer)

        bmesh.update_edit_mesh(mesh)
        return cut_count, dissolved_count

    def execute(self, context):
        axis_index = 0 if self.axis == 'X' else 1
        total_cuts = 0
        total_dissolved = 0
        object_count = 0

        for obj in context.objects_in_mode:
            if obj.type != 'MESH':
                continue
            cuts, dissolved = self._process_object(obj, axis_index)
            if cuts > 0 or dissolved > 0:
                total_cuts += cuts
                total_dissolved += dissolved
                object_count += 1

        if object_count == 0:
            self.report({'WARNING'}, "未选中任何面")
            return {'CANCELLED'}

        message = f"沿 {self.axis} 轴对 {object_count} 个物体完成 {total_cuts} 次切割"
        if self.dissolve_old:
            message += f",溶解 {total_dissolved} 条旧边"
        self.report({'INFO'}, message)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# 参考拓扑重建
# ---------------------------------------------------------------------------

class SHIYUME_OT_TopologyCut(bpy.types.Operator):
    """用参考网格的拓扑重建目标网格,并在 UVSync 平面上插值全部形态键。
    约定:活动物体为目标网格,另一个选中网格为参考。两者需在 UVSync
    形态键定义的二维平面上轮廓一致(如均由「网格UV同步」生成)。
    采样为网格加速 + 向量化 barycentric,形态键整键 gather"""
    bl_idname = "shiyume.topology_cut"
    bl_label = "参考拓扑重建"
    bl_options = {'REGISTER', 'UNDO'}

    flat_key_name: bpy.props.StringProperty(
        name="平面形态键", default="UVSync",
        description="定义二维采样平面的形态键名",
    )
    tolerance: bpy.props.FloatProperty(
        name="容差", default=0.000001, min=0.000000001, precision=6,
        description="二维点落在三角形内的判断容差",
    )
    grid_size: bpy.props.IntProperty(
        name="网格加速", default=64, min=8, max=512,
        description="二维三角形查找的加速网格分辨率",
    )

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            return False
        active = context.active_object
        if active is None or active.type != 'MESH':
            return False
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        return len(selected_meshes) == 2 and active in selected_meshes

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "flat_key_name")
        layout.prop(self, "tolerance")
        layout.prop(self, "grid_size")

    # ------------------------------------------------------------------

    @staticmethod
    def _shape_key_points(obj, key_name):
        """形态键坐标 (V, 3);键不存在时退回网格顶点。"""
        mesh = obj.data
        if mesh.shape_keys and key_name in mesh.shape_keys.key_blocks:
            return batch.read_float(mesh.shape_keys.key_blocks[key_name].data, "co", 3)
        return batch.read_float(mesh.vertices, "co", 3)

    @staticmethod
    def _has_shape_key(obj, key_name):
        return bool(obj.data.shape_keys and key_name in obj.data.shape_keys.key_blocks)

    def _world_xy(self, obj, points):
        return batch.apply_matrix(obj.matrix_world, points)[:, :2]

    def execute(self, context):
        target = context.active_object
        others = [
            obj for obj in context.selected_objects
            if obj.type == 'MESH' and obj != target
        ]
        if len(others) != 1:
            self.report({'ERROR'}, "请选择 2 个网格,并将目标网格设为活动物体")
            return {'CANCELLED'}
        source = others[0]

        if not self._has_shape_key(source, self.flat_key_name):
            self.report({'ERROR'}, f"参考网格缺少形态键: {self.flat_key_name}")
            return {'CANCELLED'}
        if not self._has_shape_key(target, self.flat_key_name):
            self.report({'ERROR'}, f"目标网格缺少形态键: {self.flat_key_name}")
            return {'CANCELLED'}

        target_mesh = target.data
        target_mesh.calc_loop_triangles()
        triangle_count = len(target_mesh.loop_triangles)
        if triangle_count == 0:
            self.report({'ERROR'}, "目标网格没有面,无法重建参考拓扑")
            return {'CANCELLED'}

        # ---- 目标网格:UVSync 平面三角形 + 加速网格 ----
        triangles = batch.read_int(target_mesh.loop_triangles, "vertices", 3)
        flat_plane = self._world_xy(target, self._shape_key_points(target, self.flat_key_name))

        corner_a = flat_plane[triangles[:, 0]]
        corner_b = flat_plane[triangles[:, 1]]
        corner_c = flat_plane[triangles[:, 2]]
        triangle_min = np.minimum(np.minimum(corner_a, corner_b), corner_c)
        triangle_max = np.maximum(np.maximum(corner_a, corner_b), corner_c)

        plane_min = flat_plane.min(axis=0)
        plane_max = flat_plane.max(axis=0)
        cell_size = np.maximum((plane_max - plane_min), self.tolerance) / self.grid_size

        cell_low = np.clip(((triangle_min - plane_min) / cell_size).astype(np.int32), 0, self.grid_size - 1)
        cell_high = np.clip(((triangle_max - plane_min) / cell_size).astype(np.int32), 0, self.grid_size - 1)

        cells = {}
        for triangle_index in range(triangle_count):
            for grid_x in range(cell_low[triangle_index, 0], cell_high[triangle_index, 0] + 1):
                for grid_y in range(cell_low[triangle_index, 1], cell_high[triangle_index, 1] + 1):
                    cells.setdefault((grid_x, grid_y), []).append(triangle_index)
        cells = {key: np.array(value, dtype=np.int32) for key, value in cells.items()}

        # 最近顶点回退用的 KD 树
        fallback_tree = kdtree.KDTree(len(flat_plane))
        for index, (x, y) in enumerate(flat_plane):
            fallback_tree.insert(Vector((float(x), float(y), 0.0)), index)
        fallback_tree.balance()

        # ---- 参考网格顶点 → 命中三角形 + barycentric ----
        source_plane = self._world_xy(source, self._shape_key_points(source, self.flat_key_name))
        point_count = len(source_plane)

        hit_triangle = np.full(point_count, -1, dtype=np.int32)
        hit_weights = np.zeros((point_count, 3), dtype=np.float64)
        fallback_vertex = np.zeros(point_count, dtype=np.int32)

        tolerance = self.tolerance
        for point_index in range(point_count):
            point = source_plane[point_index]
            grid_x = int((point[0] - plane_min[0]) / cell_size[0])
            grid_y = int((point[1] - plane_min[1]) / cell_size[1])
            grid_x = max(0, min(self.grid_size - 1, grid_x))
            grid_y = max(0, min(self.grid_size - 1, grid_y))

            found = False
            for radius in range(3):
                candidate_arrays = [
                    cells[(cell_x, cell_y)]
                    for cell_x in range(max(0, grid_x - radius), min(self.grid_size - 1, grid_x + radius) + 1)
                    for cell_y in range(max(0, grid_y - radius), min(self.grid_size - 1, grid_y + radius) + 1)
                    if (cell_x, cell_y) in cells
                ]
                if not candidate_arrays:
                    continue
                candidates = np.unique(np.concatenate(candidate_arrays))

                # 包围盒粗筛
                box_hit = (
                    (point[0] >= triangle_min[candidates, 0] - tolerance)
                    & (point[0] <= triangle_max[candidates, 0] + tolerance)
                    & (point[1] >= triangle_min[candidates, 1] - tolerance)
                    & (point[1] <= triangle_max[candidates, 1] + tolerance)
                )
                candidates = candidates[box_hit]
                if len(candidates) == 0:
                    continue

                # 向量化 barycentric
                a = corner_a[candidates]
                b = corner_b[candidates]
                c = corner_c[candidates]
                determinant = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
                valid = np.abs(determinant) > tolerance
                safe_determinant = np.where(valid, determinant, 1.0)
                weight_0 = ((b[:, 1] - c[:, 1]) * (point[0] - c[:, 0])
                            + (c[:, 0] - b[:, 0]) * (point[1] - c[:, 1])) / safe_determinant
                weight_1 = ((c[:, 1] - a[:, 1]) * (point[0] - c[:, 0])
                            + (a[:, 0] - c[:, 0]) * (point[1] - c[:, 1])) / safe_determinant
                weight_2 = 1.0 - weight_0 - weight_1
                inside = (
                    valid
                    & (np.minimum(np.minimum(weight_0, weight_1), weight_2) >= -tolerance)
                    & (np.maximum(np.maximum(weight_0, weight_1), weight_2) <= 1.0 + tolerance)
                )
                if inside.any():
                    local = int(np.argmax(inside))
                    hit_triangle[point_index] = candidates[local]
                    hit_weights[point_index] = (weight_0[local], weight_1[local], weight_2[local])
                    found = True
                    break

            if not found:
                _position, nearest_index, _distance = fallback_tree.find(
                    Vector((float(point[0]), float(point[1]), 0.0)))
                fallback_vertex[point_index] = nearest_index

        # ---- 逐形态键整键采样(gather,零逐点循环) ----
        key_names = [key.name for key in target_mesh.shape_keys.key_blocks]
        hit_mask = hit_triangle >= 0
        vertex_0 = triangles[hit_triangle, 0]
        vertex_1 = triangles[hit_triangle, 1]
        vertex_2 = triangles[hit_triangle, 2]

        sampled_points = {}
        for key_name in key_names:
            values = self._shape_key_points(target, key_name).astype(np.float64)
            interpolated = (
                values[vertex_0] * hit_weights[:, 0:1]
                + values[vertex_1] * hit_weights[:, 1:2]
                + values[vertex_2] * hit_weights[:, 2:3]
            )
            interpolated[~hit_mask] = values[fallback_vertex[~hit_mask]]
            sampled_points[key_name] = interpolated.astype(np.float32)

        # ---- 用参考拓扑 + 采样坐标重建目标 ----
        source_faces = [list(polygon.vertices) for polygon in source.data.polygons]
        loose_mask = batch.read_bool(source.data.edges, "is_loose") if len(source.data.edges) else np.empty(0, np.bool_)
        source_edges = batch.read_int(source.data.edges, "vertices", 2) if len(source.data.edges) else np.empty((0, 2), np.int32)
        loose_edges = source_edges[loose_mask].tolist()

        old_mesh = target.data
        old_shape_keys = old_mesh.shape_keys
        old_materials = list(old_mesh.materials)
        old_name = old_mesh.name

        new_mesh = bpy.data.meshes.new(old_name + "_topology")
        new_mesh.from_pydata(sampled_points[key_names[0]].tolist(), loose_edges, source_faces)
        new_mesh.update()

        # UV 层整层复制(参考网格 → 新网格,loop 结构一致)
        self._copy_uv_layers(source.data, new_mesh)

        for material in old_materials:
            new_mesh.materials.append(material)

        target.data = new_mesh

        for key_name in key_names:
            new_key = target.shape_key_add(name=key_name, from_mix=False)
            batch.write_float(new_key.data, "co", sampled_points[key_name])

        if old_shape_keys:
            compat.copy_shape_key_settings(old_shape_keys, target)

        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

        self.report({'INFO'}, f"目标网格已重建为参考拓扑,共 {point_count} 个顶点")
        return {'FINISHED'}

    @staticmethod
    def _copy_uv_layers(source_mesh, new_mesh):
        if not source_mesh.uv_layers:
            return

        source_active_index = source_mesh.uv_layers.active_index
        source_render_index = next(
            (index for index, layer in enumerate(source_mesh.uv_layers) if layer.active_render),
            0,
        )

        for source_layer in source_mesh.uv_layers:
            new_layer = new_mesh.uv_layers.new(name=source_layer.name, do_init=False)
            if new_layer is None:
                continue
            batch.write_float(new_layer.data, "uv", batch.read_uvs(source_mesh, source_layer))

        if new_mesh.uv_layers:
            last_index = len(new_mesh.uv_layers) - 1
            new_mesh.uv_layers.active_index = min(source_active_index, last_index)
            for index, layer in enumerate(new_mesh.uv_layers):
                layer.active_render = index == min(source_render_index, last_index)


classes = (
    SHIYUME_OT_GridCut,
    SHIYUME_OT_TopologyCut,
)
