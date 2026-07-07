"""UV 布局工具:孤岛排列(排序/等距/对齐一体)与 UVPackmaster 锁定组预处理。"""

import math

import bmesh
import bpy

from ..core import batch, compat, uv_islands


class SHIYUME_OT_ArrangeUVIslands(bpy.types.Operator):
    """把 UV 编辑器中选中的孤岛沿指定轴依次排开:
    可保持原位置顺序(仅均匀间距)或按高度/宽度/面积重排序,
    垂直方向可选底对齐/顶对齐/居中。支持多物体编辑模式"""
    bl_idname = "shiyume.arrange_uv_islands"
    bl_label = "排列UV孤岛"
    bl_options = {'REGISTER', 'UNDO'}

    sort_mode: bpy.props.EnumProperty(
        name="排序",
        items=[
            ('POSITION', "保持位置顺序", "按当前位置顺序排列,只把间距调均匀"),
            ('HEIGHT', "按高度", "按孤岛 V 向尺寸排序"),
            ('WIDTH', "按宽度", "按孤岛 U 向尺寸排序"),
            ('AREA', "按包围盒面积", "按孤岛包围盒面积排序"),
        ],
        default='POSITION',
    )
    axis: bpy.props.EnumProperty(
        name="排列轴",
        items=[
            ('U', "U (横向)", "沿 U 方向依次排开"),
            ('V', "V (纵向)", "沿 V 方向依次排开"),
        ],
        default='U',
    )
    descending: bpy.props.BoolProperty(
        name="从大到小", default=True,
        description="排序模式下的方向(保持位置顺序时无效)",
    )
    spacing: bpy.props.FloatProperty(
        name="间距", default=0.01, min=0.0, soft_max=1.0,
        description="孤岛之间的间距(UV 单位)",
    )
    align: bpy.props.EnumProperty(
        name="对齐",
        items=[
            ('NONE', "保持", "不改变垂直于排列轴方向的位置"),
            ('MIN', "低边对齐", "垂直方向按最低边对齐"),
            ('MAX', "高边对齐", "垂直方向按最高边对齐"),
            ('CENTER', "居中", "垂直方向居中对齐"),
        ],
        default='NONE',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "sort_mode")
        if self.sort_mode != 'POSITION':
            layout.prop(self, "descending")
        layout.row().prop(self, "axis", expand=True)
        layout.prop(self, "spacing")
        layout.prop(self, "align")

    def execute(self, context):
        # 跨所有编辑中的物体收集有选中的孤岛
        entries = []
        touched = []
        for obj in context.objects_in_mode_unique_data:
            if obj.type != 'MESH':
                continue
            working = bmesh.from_edit_mesh(obj.data)
            uv_layer = working.loops.layers.uv.active
            if uv_layer is None:
                continue
            is_selected = compat.bm_uv_select_predicate(working, uv_layer, context.tool_settings)

            for loops in uv_islands.collect_islands(working, uv_layer):
                if not any(is_selected(loop) for loop in loops):
                    continue
                min_u, min_v, max_u, max_v = uv_islands.island_bounds(loops, uv_layer)
                entries.append({
                    'loops': loops,
                    'uv_layer': uv_layer,
                    'min_u': min_u, 'min_v': min_v,
                    'max_u': max_u, 'max_v': max_v,
                    'width': max_u - min_u,
                    'height': max_v - min_v,
                })
            touched.append(obj.data)

        if len(entries) < 2:
            self.report({'WARNING'}, "需要在 UV 编辑器中选中至少两个孤岛")
            return {'CANCELLED'}

        along_u = self.axis == 'U'
        main_min = 'min_u' if along_u else 'min_v'
        main_size = 'width' if along_u else 'height'
        cross_min = 'min_v' if along_u else 'min_u'
        cross_max = 'max_v' if along_u else 'max_u'
        cross_size = 'height' if along_u else 'width'

        if self.sort_mode == 'POSITION':
            entries.sort(key=lambda entry: entry[main_min] + entry[main_size] * 0.5)
        elif self.sort_mode == 'HEIGHT':
            entries.sort(key=lambda entry: entry['height'], reverse=self.descending)
        elif self.sort_mode == 'WIDTH':
            entries.sort(key=lambda entry: entry['width'], reverse=self.descending)
        else:
            entries.sort(key=lambda entry: entry['width'] * entry['height'], reverse=self.descending)

        # 对齐参考线(垂直于排列轴)
        if self.align == 'MIN':
            reference = min(entry[cross_min] for entry in entries)
        elif self.align == 'MAX':
            reference = max(entry[cross_max] for entry in entries)
        elif self.align == 'CENTER':
            reference = sum(
                entry[cross_min] + entry[cross_size] * 0.5 for entry in entries
            ) / len(entries)
        else:
            reference = 0.0

        cursor = entries[0][main_min]
        for entry in entries:
            main_offset = cursor - entry[main_min]

            if self.align == 'MIN':
                cross_offset = reference - entry[cross_min]
            elif self.align == 'MAX':
                cross_offset = reference - entry[cross_max]
            elif self.align == 'CENTER':
                cross_offset = reference - (entry[cross_min] + entry[cross_size] * 0.5)
            else:
                cross_offset = 0.0

            offset_u = main_offset if along_u else cross_offset
            offset_v = cross_offset if along_u else main_offset

            uv_layer = entry['uv_layer']
            for loop in entry['loops']:
                uv = loop[uv_layer].uv
                uv.x += offset_u
                uv.y += offset_v

            cursor += entry[main_size] + self.spacing

        for mesh in touched:
            bmesh.update_edit_mesh(mesh)

        self.report({'INFO'}, f"已沿 {self.axis} 轴排列 {len(entries)} 个孤岛")
        return {'FINISHED'}


class SHIYUME_OT_UVPackLockGroup(bpy.types.Operator):
    """UVPackmaster 打包预处理:把选中的多个物体按顺序横向偏移 UV(避免重叠),
    按物体包围盒对角线归一化缩放,并分配递增的 Lock Group ID"""
    bl_idname = "shiyume.uv_pack_lock_group"
    bl_label = "UV打包锁定组"
    bl_options = {'REGISTER', 'UNDO'}

    offset: bpy.props.FloatProperty(
        name="UV 偏移量", default=2.0,
        description="每个物体 UV 块的横向偏移距离",
    )
    assign_lock_groups: bpy.props.BoolProperty(
        name="分配锁定组", default=True,
        description="为每个物体分配递增的 UVPackmaster 3 Lock Group(未安装则自动跳过)",
    )

    def execute(self, context):
        meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not meshes:
            self.report({'WARNING'}, "未选中网格物体")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # UV 偏移 + 归一化缩放:直接批量改数据,不进编辑模式
        current_offset = 0.0
        for obj in meshes:
            mesh = obj.data
            uv_layer = mesh.uv_layers.active
            if uv_layer is None:
                uv_layer = mesh.uv_layers.new()

            dimensions = obj.dimensions
            length = math.sqrt(dimensions.x ** 2 + dimensions.y ** 2 + dimensions.z ** 2)
            scale = 1.0 / length if length >= 1.0 else 1.0

            uvs = batch.read_uvs(mesh, uv_layer)
            uvs[:, 0] += current_offset
            uvs *= scale
            batch.write_float(uv_layer.data, "uv", uvs)
            mesh.update()

            current_offset += self.offset

        # Lock Group 分配依赖 UVPackmaster 3 的算子,需要逐物体进编辑模式
        if self.assign_lock_groups:
            if hasattr(context.scene, "uvpm3_props") and hasattr(bpy.ops, "uvpackmaster3"):
                group_number = 1
                for obj in meshes:
                    context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode='EDIT')
                    try:
                        context.scene.uvpm3_props.numbered_groups_descriptors.lock_group.group_num = group_number
                        bpy.ops.uvpackmaster3.numbered_group_set_iparam(groups_desc_id="lock_group")
                    except Exception:
                        self.report({'WARNING'}, "UVPackmaster 3 锁定组分配失败,已跳过")
                        bpy.ops.object.mode_set(mode='OBJECT')
                        break
                    bpy.ops.object.mode_set(mode='OBJECT')
                    group_number += 1
            else:
                self.report({'WARNING'}, "未检测到 UVPackmaster 3,跳过锁定组分配")

        return {'FINISHED'}


classes = (
    SHIYUME_OT_ArrangeUVIslands,
    SHIYUME_OT_UVPackLockGroup,
)
