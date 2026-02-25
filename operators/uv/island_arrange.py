import bpy
import bmesh


def _uv_connected(loop_a, loop_b, uv_layer, epsilon=1e-5):
    """Check if two loops share the same UV coordinate at their vertex."""
    uv_a = loop_a[uv_layer].uv
    uv_b = loop_b[uv_layer].uv
    return (uv_a - uv_b).length < epsilon


def _collect_islands(bm, uv_layer):
    """Collect ALL UV islands as lists of loops via flood-fill over UV connectivity.

    Returns a list of islands, where each island is a list of loops.
    """
    face_visited = set()
    islands = []

    for seed_face in bm.faces:
        if seed_face.index in face_visited:
            continue

        island_loops = []
        stack = [seed_face]

        while stack:
            face = stack.pop()
            if face.index in face_visited:
                continue
            face_visited.add(face.index)

            for loop in face.loops:
                island_loops.append(loop)

            # Find UV-connected neighbour faces
            for loop in face.loops:
                for other_loop in loop.vert.link_loops:
                    if other_loop.face.index in face_visited:
                        continue
                    if _uv_connected(loop, other_loop, uv_layer):
                        stack.append(other_loop.face)

        if island_loops:
            islands.append(island_loops)

    return islands


def _island_has_selection(loops, uv_layer, use_uv_select):
    """Check if an island has at least one selected UV vertex.

    When UV sync mode is ON, use_uv_select=False and we check face.select.
    When UV sync mode is OFF, use_uv_select=True and we check loop UV select.
    """
    if use_uv_select:
        return any(loop[uv_layer].select for loop in loops)
    else:
        return any(loop.face.select for loop in loops)


def _collect_selected_islands(bm, uv_layer, use_uv_select):
    """Collect only UV islands that contain at least one selected UV vertex.

    Returns a list of islands (each a list of loops) that have selection.
    """
    all_islands = _collect_islands(bm, uv_layer)
    return [
        loops for loops in all_islands
        if _island_has_selection(loops, uv_layer, use_uv_select)
    ]


def _island_bbox(loops, uv_layer):
    """Compute bounding box of an island.

    Returns (min_u, min_v, max_u, max_v).
    """
    us = []
    vs = []
    for loop in loops:
        uv = loop[uv_layer].uv
        us.append(uv.x)
        vs.append(uv.y)
    return min(us), min(vs), max(us), max(vs)


# --------------------------------------------------------------------------
# Operator 1: Equidistant Arrangement
# --------------------------------------------------------------------------


class SHIYUME_OT_UVIslandEquidistant(bpy.types.Operator):
    """将 UV 编辑器中选中的孤岛沿选定轴等距排列。
    严格保持原始位置顺序（例如 X 从小到大），仅调整间距使其均匀。
    需要在 UV 编辑器中选择要排列的孤岛。"""
    bl_idname = "shiyume.uv_island_equidistant"
    bl_label = "UV孤岛等距排列"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(
        name="排列轴",
        items=[
            ('X', "X (U)", "沿 U 方向排列"),
            ('Y', "Y (V)", "沿 V 方向排列"),
        ],
        default='X',
    )
    spacing: bpy.props.FloatProperty(
        name="间距",
        description="孤岛之间的间距 (UV 单位)",
        default=0.01,
        min=0.0,
        soft_max=1.0,
    )

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "请选择一个网格物体")
            return {'CANCELLED'}

        # 确保在编辑模式
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if not uv_layer:
            self.report({'ERROR'}, "没有活动的 UV 层")
            return {'CANCELLED'}

        # 检测 UV 同步选择模式
        use_uv_select = not context.tool_settings.use_uv_select_sync

        # 仅收集在 UV 编辑器中有选中顶点的孤岛
        islands = _collect_selected_islands(bm, uv_layer, use_uv_select)
        if len(islands) < 2:
            self.report({'WARNING'}, "需要在 UV 编辑器中选中至少两个孤岛")
            return {'CANCELLED'}

        # Compute bounding boxes
        island_data = []
        for loops in islands:
            min_u, min_v, max_u, max_v = _island_bbox(loops, uv_layer)
            center_u = (min_u + max_u) / 2.0
            center_v = (min_v + max_v) / 2.0
            width = max_u - min_u
            height = max_v - min_v
            island_data.append({
                'loops': loops,
                'min_u': min_u, 'min_v': min_v,
                'max_u': max_u, 'max_v': max_v,
                'center_u': center_u, 'center_v': center_v,
                'width': width, 'height': height,
            })

        # Sort by current position on the chosen axis (preserve original order)
        if self.axis == 'X':
            island_data.sort(key=lambda d: d['center_u'])
        else:
            island_data.sort(key=lambda d: d['center_v'])

        # Place islands sequentially with equal spacing
        if self.axis == 'X':
            # Start from the left edge of the first island
            cursor = island_data[0]['min_u']
            for data in island_data:
                offset = cursor - data['min_u']
                for loop in data['loops']:
                    loop[uv_layer].uv.x += offset
                cursor += data['width'] + self.spacing
        else:
            cursor = island_data[0]['min_v']
            for data in island_data:
                offset = cursor - data['min_v']
                for loop in data['loops']:
                    loop[uv_layer].uv.y += offset
                cursor += data['height'] + self.spacing

        bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'}, f"已沿 {self.axis} 轴等距排列 {len(islands)} 个孤岛")
        return {'FINISHED'}


# --------------------------------------------------------------------------
# Operator 2: Sort by Height
# --------------------------------------------------------------------------


class SHIYUME_OT_UVIslandSortByHeight(bpy.types.Operator):
    """将 UV 编辑器中选中的孤岛按高度 (V 方向尺寸) 排序并沿 X 轴并排放置。
    可选从高到矮或从矮到高。
    需要在 UV 编辑器中选择要排序的孤岛。"""
    bl_idname = "shiyume.uv_island_sort_height"
    bl_label = "UV孤岛按高度排序"
    bl_options = {'REGISTER', 'UNDO'}

    reverse: bpy.props.BoolProperty(
        name="从矮到高",
        description="勾选则从矮到高排列；不勾选则从高到矮",
        default=False,
    )
    spacing: bpy.props.FloatProperty(
        name="间距",
        description="孤岛之间的间距 (UV 单位)",
        default=0.01,
        min=0.0,
        soft_max=1.0,
    )
    align_bottom: bpy.props.BoolProperty(
        name="底部对齐",
        description="勾选则全部孤岛底部对齐；不勾选则保持原始 V 位置",
        default=True,
    )

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "请选择一个网格物体")
            return {'CANCELLED'}

        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if not uv_layer:
            self.report({'ERROR'}, "没有活动的 UV 层")
            return {'CANCELLED'}

        use_uv_select = not context.tool_settings.use_uv_select_sync

        islands = _collect_selected_islands(bm, uv_layer, use_uv_select)
        if len(islands) < 2:
            self.report({'WARNING'}, "需要在 UV 编辑器中选中至少两个孤岛")
            return {'CANCELLED'}

        # Compute bounding boxes
        island_data = []
        for loops in islands:
            min_u, min_v, max_u, max_v = _island_bbox(loops, uv_layer)
            width = max_u - min_u
            height = max_v - min_v
            island_data.append({
                'loops': loops,
                'min_u': min_u, 'min_v': min_v,
                'max_u': max_u, 'max_v': max_v,
                'width': width, 'height': height,
            })

        # Sort by height (V extent) — default high-to-low, reversed = low-to-high
        island_data.sort(key=lambda d: d['height'], reverse=not self.reverse)

        # Place along X axis from left to right
        cursor_x = island_data[0]['min_u']

        # Find common bottom if aligning
        if self.align_bottom:
            common_bottom = min(d['min_v'] for d in island_data)

        for data in island_data:
            # X offset
            offset_x = cursor_x - data['min_u']
            # Y offset (align bottom or keep original)
            offset_y = (common_bottom - data['min_v']) if self.align_bottom else 0.0

            for loop in data['loops']:
                loop[uv_layer].uv.x += offset_x
                loop[uv_layer].uv.y += offset_y

            cursor_x += data['width'] + self.spacing

        bmesh.update_edit_mesh(obj.data)
        order_text = "矮→高" if self.reverse else "高→矮"
        self.report({'INFO'}, f"已按高度 ({order_text}) 排列 {len(islands)} 个孤岛")
        return {'FINISHED'}

