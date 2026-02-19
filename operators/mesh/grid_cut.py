import bpy
import bmesh
import math
from mathutils import Vector

class SHIYUME_OT_GridCut(bpy.types.Operator):
    """按指定间隔对选中面片进行等距切割，然后溶解旧的内部分割边。
    专为发片等距工作流设计：配合 mesh_to_uv 生成的 UV 网格使用，
    可将不均匀的发片重新切割为等距条带，同时保持轮廓完整。"""
    bl_idname = "shiyume.grid_cut"
    bl_label = "网格切割"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(
        name="轴向",
        items=[
            ('X', "X", "沿X轴方向切割（生成竖向切线）"),
            ('Y', "Y", "沿Y轴方向切割（生成横向切线）"),
        ],
        default='X',
        description="切割方向"
    )
    interval: bpy.props.FloatProperty(
        name="间隔 (m)",
        default=0.01,
        min=0.0001,
        description="切割的间距（米）"
    )
    dissolve_old: bpy.props.BoolProperty(
        name="溶解旧边",
        default=True,
        description="切割后自动溶解对应轴向上的旧内部边（保留轮廓和UV接缝）"
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH'
                and context.mode == 'EDIT_MESH')

    def _process_object(self, obj, axis_idx):
        """处理单个物体：标记旧边 → 切割 → 溶解旧边。返回 (切割数, 溶解边数)。"""
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        # ---- 收集选中面 ----
        sel_faces = [f for f in bm.faces if f.select]
        if not sel_faces:
            return 0, 0

        # ---- 世界矩阵 ----
        mat = obj.matrix_world
        mat_inv = mat.inverted()

        # ---- 创建临时标记层 ----
        tag_key = "_grid_cut_old"
        tag_layer = bm.edges.layers.int.get(tag_key)
        if tag_layer is None:
            tag_layer = bm.edges.layers.int.new(tag_key)
        # 确保所有边初始值为 0
        for edge in bm.edges:
            edge[tag_layer] = 0

        # ---- 切割前：将垂直于切割轴的旧内部边标记为 1 ----
        marked_count = 0
        if self.dissolve_old:
            for edge in bm.edges:
                # 跳过边界边（轮廓）
                if edge.is_boundary:
                    continue
                # 跳过非流形边
                if not edge.is_manifold:
                    continue
                # 跳过UV接缝
                if edge.seam:
                    continue
                # 至少一端的顶点要在选中面的区域内
                if not (edge.verts[0].select or edge.verts[1].select):
                    continue
                # 正交网格判定：两端顶点在切割轴上坐标相同 → 边垂直于切割轴
                v0_axis = (mat @ edge.verts[0].co)[axis_idx]
                v1_axis = (mat @ edge.verts[1].co)[axis_idx]
                if abs(v1_axis - v0_axis) < 1e-5:
                    edge[tag_layer] = 1
                    marked_count += 1

        # ---- 计算选中面在目标轴方向上的范围（世界坐标） ----
        all_coords = []
        for f in sel_faces:
            for v in f.verts:
                all_coords.append((mat @ v.co)[axis_idx])

        min_val = min(all_coords)
        max_val = max(all_coords)

        # ---- 对齐到全局网格 ----
        start = math.ceil(min_val / self.interval) * self.interval
        if abs(start - min_val) < 1e-6:
            start += self.interval

        # ---- 构造切割位置 ----
        cut_positions = []
        pos = start
        while pos < max_val - 1e-6:
            cut_positions.append(pos)
            pos += self.interval

        if not cut_positions and marked_count == 0:
            # 清理临时层
            bm.edges.layers.int.remove(tag_layer)
            return 0, 0

        # ---- 切割平面法线（局部空间） ----
        normal_world = Vector((0, 0, 0))
        normal_world[axis_idx] = 1.0
        normal_local = (mat_inv.to_3x3() @ normal_world).normalized()

        # ---- 执行逐条切割 ----
        cut_count = 0
        for cut_pos in cut_positions:
            point_world = Vector((0, 0, 0))
            point_world[axis_idx] = cut_pos
            point_local = mat_inv @ point_world

            sel_geom = [f for f in bm.faces if f.select]
            sel_edges = [e for e in bm.edges if e.select]
            sel_verts = [v for v in bm.verts if v.select]
            geom = sel_verts + sel_edges + sel_geom

            if not geom:
                break

            result = bmesh.ops.bisect_plane(
                bm,
                geom=geom,
                dist=0.0001,
                plane_co=point_local,
                plane_no=normal_local,
                clear_outer=False,
                clear_inner=False,
            )

            # ---- 清除切割平面上所有边的标记 ----
            cut_verts = set()
            for elem in result['geom_cut']:
                if isinstance(elem, bmesh.types.BMVert):
                    cut_verts.add(elem)
                elif isinstance(elem, bmesh.types.BMEdge):
                    elem[tag_layer] = 0
                    cut_verts.add(elem.verts[0])
                    cut_verts.add(elem.verts[1])

            # 两端都在切割平面上的边 → 清除标记（已有边在切割位置的情况）
            for v in cut_verts:
                for edge in v.link_edges:
                    if edge.verts[0] in cut_verts and edge.verts[1] in cut_verts:
                        edge[tag_layer] = 0

            # ---- 确保切割线及相邻面保持选中 ----
            # bisect_plane 分割面后，新面可能失去选中状态，
            # 导致后续切割跳过这些区域
            for elem in result['geom_cut']:
                elem.select = True
                if isinstance(elem, bmesh.types.BMVert):
                    for face in elem.link_faces:
                        face.select = True
                    for edge in elem.link_edges:
                        edge.select = True

            cut_count += 1

        # ---- 溶解仍带标记的旧边 ----
        dissolved_count = 0
        if self.dissolve_old and marked_count > 0:
            edges_to_dissolve = [e for e in bm.edges
                                 if e.is_valid and e[tag_layer] == 1]
            if edges_to_dissolve:
                bmesh.ops.dissolve_edges(bm, edges=edges_to_dissolve, use_verts=True)
                dissolved_count = len(edges_to_dissolve)

        # ---- 清理临时标记层 ----
        tag_layer_ref = bm.edges.layers.int.get(tag_key)
        if tag_layer_ref is not None:
            bm.edges.layers.int.remove(tag_layer_ref)

        bmesh.update_edit_mesh(me)
        return cut_count, dissolved_count

    def execute(self, context):
        axis_idx = 0 if self.axis == 'X' else 1
        total_cuts = 0
        total_dissolved = 0
        obj_count = 0

        for obj in context.objects_in_mode:
            if obj.type != 'MESH':
                continue

            cuts, dissolved = self._process_object(obj, axis_idx)
            if cuts > 0 or dissolved > 0:
                total_cuts += cuts
                total_dissolved += dissolved
                obj_count += 1

        if obj_count == 0:
            self.report({'WARNING'}, "未选中任何面")
            return {'CANCELLED'}

        msg = f"沿 {self.axis} 轴对 {obj_count} 个物体完成 {total_cuts} 次切割"
        if self.dissolve_old:
            msg += f"，溶解 {total_dissolved} 条旧边"
        self.report({'INFO'}, msg)
        return {'FINISHED'}
