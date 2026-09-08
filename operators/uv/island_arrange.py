import bpy
import bmesh

from . import uv_islands


def _island_layout(island, uv_layer):
    min_u, min_v, max_u, max_v = uv_islands.bounds(island.faces, uv_layer)
    return {
        'faces': island.faces,
        'min_u': min_u, 'min_v': min_v,
        'max_u': max_u, 'max_v': max_v,
        'center_u': (min_u + max_u) / 2.0,
        'center_v': (min_v + max_v) / 2.0,
        'width': max_u - min_u,
        'height': max_v - min_v,
    }


def _offset_island(data, uv_layer, offset_u, offset_v):
    for loop in uv_islands.loops(data['faces']):
        loop[uv_layer].uv.x += offset_u
        loop[uv_layer].uv.y += offset_v


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

        islands = uv_islands.collect_selected_islands(
            bm, uv_layer, context.tool_settings)
        if len(islands) < 2:
            self.report({'WARNING'}, "需要在 UV 编辑器中选中至少两个孤岛")
            return {'CANCELLED'}

        island_data = [_island_layout(island, uv_layer) for island in islands]

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
                _offset_island(data, uv_layer, cursor - data['min_u'], 0.0)
                cursor += data['width'] + self.spacing
        else:
            cursor = island_data[0]['min_v']
            for data in island_data:
                _offset_island(data, uv_layer, 0.0, cursor - data['min_v'])
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

        islands = uv_islands.collect_selected_islands(
            bm, uv_layer, context.tool_settings)
        if len(islands) < 2:
            self.report({'WARNING'}, "需要在 UV 编辑器中选中至少两个孤岛")
            return {'CANCELLED'}

        island_data = [_island_layout(island, uv_layer) for island in islands]

        # Sort by height (V extent) — default high-to-low, reversed = low-to-high
        island_data.sort(key=lambda d: d['height'], reverse=not self.reverse)

        # Place along X axis from left to right
        cursor_x = island_data[0]['min_u']
        common_bottom = min(d['min_v'] for d in island_data)

        for data in island_data:
            offset_y = (common_bottom - data['min_v']) if self.align_bottom else 0.0
            _offset_island(data, uv_layer, cursor_x - data['min_u'], offset_y)
            cursor_x += data['width'] + self.spacing

        bmesh.update_edit_mesh(obj.data)
        order_text = "矮→高" if self.reverse else "高→矮"
        self.report({'INFO'}, f"已按高度 ({order_text}) 排列 {len(islands)} 个孤岛")
        return {'FINISHED'}
