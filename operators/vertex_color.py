"""顶点色工具:顶点组权重映射 RGBA 通道 / 统一填色,全 NumPy 批量写入。"""

import bpy
import numpy as np

from ..core import batch, compat


class SHIYUME_OT_VertexColorFill(bpy.types.Operator):
    """写入顶点色:顶点组模式把四个顶点组的权重分别映射到 RGBA 通道
    (顶点没有该组条目时保留原值);统一颜色模式直接填充指定颜色。
    可限制仅作用于选中顶点。游戏资产遮罩/特效通道的标准做法"""
    bl_idname = "shiyume.vertex_color_fill"
    bl_label = "设置顶点色"
    bl_options = {'REGISTER', 'UNDO'}

    fill_mode: bpy.props.EnumProperty(
        name="模式",
        items=[
            ('GROUPS', "顶点组映射", "把顶点组权重写入对应颜色通道"),
            ('UNIFORM', "统一颜色", "直接填充指定颜色"),
        ],
        default='GROUPS',
    )
    uniform_color: bpy.props.FloatVectorProperty(
        name="颜色", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )
    map_red: bpy.props.StringProperty(name="R 通道顶点组", default="Red")
    map_green: bpy.props.StringProperty(name="G 通道顶点组", default="Green")
    map_blue: bpy.props.StringProperty(name="B 通道顶点组", default="Blue")
    map_alpha: bpy.props.StringProperty(name="A 通道顶点组", default="Alpha")
    selected_only: bpy.props.BoolProperty(
        name="仅选中顶点", default=False,
        description="只写入编辑模式下选中的顶点",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.row().prop(self, "fill_mode", expand=True)
        if self.fill_mode == 'UNIFORM':
            layout.prop(self, "uniform_color")
        else:
            column = layout.column(align=True)
            column.prop(self, "map_red")
            column.prop(self, "map_green")
            column.prop(self, "map_blue")
            column.prop(self, "map_alpha")
        layout.prop(self, "selected_only")

    def execute(self, context):
        # 颜色属性数据只能在物体模式下批量读写
        restore_mode = None
        if context.mode != 'OBJECT':
            restore_mode = context.active_object.mode
            bpy.ops.object.mode_set(mode='OBJECT')

        processed = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            self._fill_object(obj)
            processed += 1

        if restore_mode:
            try:
                bpy.ops.object.mode_set(mode=restore_mode)
            except RuntimeError:
                pass

        self.report({'INFO'}, f"已写入 {processed} 个网格的顶点色")
        return {'FINISHED'}

    def _fill_object(self, obj):
        mesh = obj.data
        attribute = compat.ensure_active_color_attribute(mesh)
        on_corner = attribute.domain == 'CORNER'

        element_count = len(attribute.data)
        colors = np.empty(element_count * 4, dtype=np.float32)
        attribute.data.foreach_get("color", colors)
        colors = colors.reshape(element_count, 4)

        vertex_count = len(mesh.vertices)
        loop_vertex = batch.read_int(mesh.loops, "vertex_index") if on_corner else None

        # 写入掩码:全部或仅选中顶点
        if self.selected_only:
            vertex_selected = batch.read_bool(mesh.vertices, "select")
            element_mask = vertex_selected[loop_vertex] if on_corner else vertex_selected
        else:
            element_mask = np.ones(element_count, dtype=np.bool_)

        if self.fill_mode == 'UNIFORM':
            colors[element_mask] = np.array(self.uniform_color, dtype=np.float32)
        else:
            channel_groups = [
                (0, self.map_red), (1, self.map_green),
                (2, self.map_blue), (3, self.map_alpha),
            ]
            group_to_channel = {}
            for channel, group_name in channel_groups:
                index = obj.vertex_groups.find(group_name)
                if index != -1:
                    group_to_channel[index] = channel

            if group_to_channel:
                # 一趟扫过全部形变条目,同时拿到四个通道的权重与"是否有条目"掩码
                weights = np.zeros((vertex_count, 4), dtype=np.float32)
                has_entry = np.zeros((vertex_count, 4), dtype=np.bool_)
                for vertex in mesh.vertices:
                    for entry in vertex.groups:
                        channel = group_to_channel.get(entry.group)
                        if channel is not None:
                            weights[vertex.index, channel] = entry.weight
                            has_entry[vertex.index, channel] = True

                if on_corner:
                    weights = weights[loop_vertex]
                    has_entry = has_entry[loop_vertex]

                write_mask = has_entry & element_mask[:, None]
                colors = np.where(write_mask, weights, colors)

        attribute.data.foreach_set("color", np.ascontiguousarray(colors).ravel())
        mesh.update()


classes = (
    SHIYUME_OT_VertexColorFill,
)
