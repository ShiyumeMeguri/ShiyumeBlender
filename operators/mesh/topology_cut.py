import math

import bpy


class SHIYUME_OT_TopologyCut(bpy.types.Operator):
    """使用参考网格的拓扑重建目标网格，并按 UVSync 平面插值所有形态键。
    约定：活动物体为目标网格 B，另一个选中的网格为参考网格 A。
    适用于通过 MeshToUV 生成的网格：在 UVSync 平面上轮廓一致，但布线不同。"""

    bl_idname = "shiyume.topology_cut"
    bl_label = "参考拓扑切割"
    bl_options = {"REGISTER", "UNDO"}

    flat_key_name: bpy.props.StringProperty(
        name="平面 Shape Key",
        default="UVSync",
        description="用于定义二维采样平面的 Shape Key 名称",
    )
    tolerance: bpy.props.FloatProperty(
        name="容差",
        default=0.000001,
        min=0.000000001,
        description="二维点落在三角形内的判断容差",
    )
    grid_size: bpy.props.IntProperty(
        name="网格加速",
        default=64,
        min=8,
        max=512,
        description="二维三角查找使用的加速网格分辨率",
    )

    @classmethod
    def poll(cls, context):
        active = context.active_object
        if context.mode != "OBJECT":
            return False
        if active is None or active.type != "MESH":
            return False

        selected_meshes = [
            obj for obj in context.selected_objects if obj.type == "MESH"
        ]
        return len(selected_meshes) == 2 and active in selected_meshes

    def _get_source_and_target(self, context):
        target = context.active_object
        others = [
            obj
            for obj in context.selected_objects
            if obj.type == "MESH" and obj != target
        ]
        if len(others) != 1:
            return None, None
        return others[0], target

    def _get_key_points_local(self, obj, key_name):
        mesh = obj.data
        if mesh.shape_keys and key_name in mesh.shape_keys.key_blocks:
            key = mesh.shape_keys.key_blocks[key_name]
            return [key.data[i].co.copy() for i in range(len(mesh.vertices))]
        return [vert.co.copy() for vert in mesh.vertices]

    def _has_shape_key(self, obj, key_name):
        return bool(obj.data.shape_keys and key_name in obj.data.shape_keys.key_blocks)

    def _get_all_shape_key_names(self, obj):
        if not obj.data.shape_keys:
            return []
        return [key.name for key in obj.data.shape_keys.key_blocks]

    def _world_points(self, obj, local_points):
        mat = obj.matrix_world
        return [mat @ point for point in local_points]

    def _xy_tuple(self, vec):
        return (vec.x, vec.y)

    def _triangle_weights(self, point, a, b, c):
        px, py = point
        ax, ay = a
        bx, by = b
        cx, cy = c

        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) <= self.tolerance:
            return None

        w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / det
        w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / det
        w2 = 1.0 - w0 - w1

        if min(w0, w1, w2) < -self.tolerance:
            return None
        if max(w0, w1, w2) > 1.0 + self.tolerance:
            return None
        return (w0, w1, w2)

    def _build_triangle_index(self, plane_points, triangles):
        xs = [point[0] for point in plane_points]
        ys = [point[1] for point in plane_points]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        size_x = max(max_x - min_x, self.tolerance)
        size_y = max(max_y - min_y, self.tolerance)
        cell_size_x = size_x / self.grid_size
        cell_size_y = size_y / self.grid_size

        cells = {}
        tri_boxes = []

        for tri_index, tri in enumerate(triangles):
            tri_points = [
                plane_points[tri[0]],
                plane_points[tri[1]],
                plane_points[tri[2]],
            ]
            tri_min_x = min(point[0] for point in tri_points)
            tri_max_x = max(point[0] for point in tri_points)
            tri_min_y = min(point[1] for point in tri_points)
            tri_max_y = max(point[1] for point in tri_points)
            tri_boxes.append((tri_min_x, tri_max_x, tri_min_y, tri_max_y))

            start_x = max(
                0, min(self.grid_size - 1, int((tri_min_x - min_x) / cell_size_x))
            )
            end_x = max(
                0, min(self.grid_size - 1, int((tri_max_x - min_x) / cell_size_x))
            )
            start_y = max(
                0, min(self.grid_size - 1, int((tri_min_y - min_y) / cell_size_y))
            )
            end_y = max(
                0, min(self.grid_size - 1, int((tri_max_y - min_y) / cell_size_y))
            )

            for gx in range(start_x, end_x + 1):
                for gy in range(start_y, end_y + 1):
                    cells.setdefault((gx, gy), []).append(tri_index)

        return {
            "min_x": min_x,
            "min_y": min_y,
            "cell_x": cell_size_x,
            "cell_y": cell_size_y,
            "cells": cells,
            "tri_boxes": tri_boxes,
        }

    def _candidate_triangles(self, point, index_data, triangle_count):
        px, py = point
        gx = int((px - index_data["min_x"]) / index_data["cell_x"])
        gy = int((py - index_data["min_y"]) / index_data["cell_y"])
        gx = max(0, min(self.grid_size - 1, gx))
        gy = max(0, min(self.grid_size - 1, gy))

        candidates = []
        seen = set()
        for radius in range(3):
            found_any = False
            for ix in range(
                max(0, gx - radius), min(self.grid_size - 1, gx + radius) + 1
            ):
                for iy in range(
                    max(0, gy - radius), min(self.grid_size - 1, gy + radius) + 1
                ):
                    for tri_index in index_data["cells"].get((ix, iy), []):
                        if tri_index in seen:
                            continue
                        seen.add(tri_index)
                        candidates.append(tri_index)
                        found_any = True
            if found_any:
                return candidates

        return list(range(triangle_count))

    def _nearest_vertex_index(self, point, plane_points):
        px, py = point
        nearest_index = 0
        nearest_dist = math.inf
        for index, (vx, vy) in enumerate(plane_points):
            dist = (vx - px) * (vx - px) + (vy - py) * (vy - py)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_index = index
        return nearest_index

    def _build_sampler(self, target):
        mesh = target.data
        mesh.calc_loop_triangles()
        if not mesh.loop_triangles:
            return None, "目标网格没有面，无法重建参考拓扑"
        if not self._has_shape_key(target, self.flat_key_name):
            return None, f"目标网格缺少 Shape Key: {self.flat_key_name}"

        flat_local = self._get_key_points_local(target, self.flat_key_name)
        flat_world = self._world_points(target, flat_local)
        flat_plane = [self._xy_tuple(point) for point in flat_world]

        triangles = [tuple(loop_tri.vertices) for loop_tri in mesh.loop_triangles]
        triangle_index = self._build_triangle_index(flat_plane, triangles)

        key_names = self._get_all_shape_key_names(target)
        if not key_names:
            key_names = ["__mesh__"]

        key_values = {}
        for key_name in key_names:
            local_points = self._get_key_points_local(
                target, key_name if key_name != "__mesh__" else self.flat_key_name
            )
            if key_name == "__mesh__":
                local_points = [vert.co.copy() for vert in mesh.vertices]
            key_values[key_name] = local_points

        def sample(point_2d, key_name):
            candidates = self._candidate_triangles(
                point_2d, triangle_index, len(triangles)
            )
            values = key_values[key_name]

            for tri_index in candidates:
                tri = triangles[tri_index]
                tri_box = triangle_index["tri_boxes"][tri_index]
                if (
                    point_2d[0] < tri_box[0] - self.tolerance
                    or point_2d[0] > tri_box[1] + self.tolerance
                ):
                    continue
                if (
                    point_2d[1] < tri_box[2] - self.tolerance
                    or point_2d[1] > tri_box[3] + self.tolerance
                ):
                    continue

                a = flat_plane[tri[0]]
                b = flat_plane[tri[1]]
                c = flat_plane[tri[2]]
                weights = self._triangle_weights(point_2d, a, b, c)
                if weights is None:
                    continue

                return (
                    values[tri[0]] * weights[0]
                    + values[tri[1]] * weights[1]
                    + values[tri[2]] * weights[2]
                )

            nearest_index = self._nearest_vertex_index(point_2d, flat_plane)
            return values[nearest_index].copy()

        return (
            sample,
            key_names,
        ), None

    def _copy_shape_key_settings(self, old_shape_keys, new_obj):
        new_shape_keys = new_obj.data.shape_keys
        if not old_shape_keys or not new_shape_keys:
            return

        old_blocks = old_shape_keys.key_blocks
        new_blocks = new_shape_keys.key_blocks
        relative_names = {}

        for old_key in old_blocks:
            relative_names[old_key.name] = (
                old_key.relative_key.name if old_key.relative_key else None
            )

        for old_key in old_blocks:
            new_key = new_blocks.get(old_key.name)
            if new_key is None:
                continue
            new_key.value = old_key.value
            new_key.slider_min = old_key.slider_min
            new_key.slider_max = old_key.slider_max
            new_key.mute = old_key.mute
            new_key.interpolation = old_key.interpolation
            new_key.vertex_group = old_key.vertex_group

        for old_key in old_blocks:
            new_key = new_blocks.get(old_key.name)
            relative_name = relative_names.get(old_key.name)
            if new_key is None or relative_name is None:
                continue
            relative_key = new_blocks.get(relative_name)
            if relative_key is not None:
                new_key.relative_key = relative_key

    def _copy_uv_layers(self, source_mesh, new_mesh):
        if not source_mesh.uv_layers:
            return

        source_active_index = source_mesh.uv_layers.active_index
        source_render_index = next(
            (
                index
                for index, uv_layer in enumerate(source_mesh.uv_layers)
                if uv_layer.active_render
            ),
            0,
        )

        for source_layer in source_mesh.uv_layers:
            new_layer = new_mesh.uv_layers.new(name=source_layer.name)
            for loop_index, source_uv in enumerate(source_layer.uv):
                new_uv = new_layer.uv[loop_index]
                new_uv.vector = source_uv.vector.copy()
                if hasattr(new_uv, "pin") and hasattr(source_uv, "pin"):
                    new_uv.pin = source_uv.pin
                if hasattr(new_uv, "vertex_selection") and hasattr(
                    source_uv, "vertex_selection"
                ):
                    new_uv.vertex_selection = source_uv.vertex_selection
                if hasattr(new_uv, "edge_selection") and hasattr(
                    source_uv, "edge_selection"
                ):
                    new_uv.edge_selection = source_uv.edge_selection

        if new_mesh.uv_layers:
            new_mesh.uv_layers.active_index = min(
                source_active_index, len(new_mesh.uv_layers) - 1
            )
            for index, uv_layer in enumerate(new_mesh.uv_layers):
                uv_layer.active_render = index == min(
                    source_render_index, len(new_mesh.uv_layers) - 1
                )

    def _rebuild_target(self, source, target):
        if not self._has_shape_key(source, self.flat_key_name):
            return None, f"参考网格缺少 Shape Key: {self.flat_key_name}"

        sampler_data, error = self._build_sampler(target)
        if error is not None:
            return None, error

        sample, key_names = sampler_data

        source_flat_local = self._get_key_points_local(source, self.flat_key_name)
        source_flat_world = self._world_points(source, source_flat_local)
        source_plane = [self._xy_tuple(point) for point in source_flat_world]

        source_faces = [list(poly.vertices) for poly in source.data.polygons]
        source_loose_edges = [
            list(edge.vertices) for edge in source.data.edges if edge.is_loose
        ]

        sampled_points = {}
        for key_name in key_names:
            sampled_points[key_name] = [
                sample(point_2d, key_name) for point_2d in source_plane
            ]

        old_mesh = target.data
        old_shape_keys = old_mesh.shape_keys
        old_materials = list(old_mesh.materials)
        old_name = old_mesh.name

        basis_name = (
            key_names[0] if key_names and key_names[0] != "__mesh__" else "Basis"
        )
        basis_points = sampled_points.get(basis_name)
        if basis_points is None:
            basis_points = sampled_points[key_names[0]]

        new_mesh = bpy.data.meshes.new(old_name + "_topology")
        new_mesh.from_pydata(basis_points, source_loose_edges, source_faces)
        new_mesh.update()
        self._copy_uv_layers(source.data, new_mesh)

        for material in old_materials:
            new_mesh.materials.append(material)

        target.data = new_mesh

        if key_names and key_names[0] != "__mesh__":
            created_basis = target.shape_key_add(name=key_names[0], from_mix=False)
            for index, coord in enumerate(sampled_points[key_names[0]]):
                created_basis.data[index].co = coord

            for key_name in key_names[1:]:
                new_key = target.shape_key_add(name=key_name, from_mix=False)
                for index, coord in enumerate(sampled_points[key_name]):
                    new_key.data[index].co = coord

            if old_shape_keys:
                self._copy_shape_key_settings(old_shape_keys, target)

        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

        return len(source.data.vertices), None

    def execute(self, context):
        source, target = self._get_source_and_target(context)
        if source is None or target is None:
            self.report({"ERROR"}, "请选择 2 个网格，并将目标网格设为活动物体")
            return {"CANCELLED"}

        count, error = self._rebuild_target(source, target)
        if error is not None:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        self.report({"INFO"}, f"目标网格已重建为参考拓扑，共 {count} 个顶点")
        return {"FINISHED"}
