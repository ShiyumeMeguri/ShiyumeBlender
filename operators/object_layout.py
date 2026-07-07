"""物体级工具:按尺寸选择、批量排列、清理空物体、规范化重命名。"""

import math
import re

import bpy


def _diagonal(obj):
    dimensions = obj.dimensions
    return math.sqrt(dimensions.x ** 2 + dimensions.y ** 2 + dimensions.z ** 2)


class SHIYUME_OT_SelectBySize(bpy.types.Operator):
    """按包围盒尺寸选择物体:
    阈值模式在全场景内按对角线长度筛选;均值减半模式在当前选择中
    取消较小的一半(连带取消共享同一网格数据的实例)"""
    bl_idname = "shiyume.select_by_size"
    bl_label = "按尺寸选择"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="模式",
        items=[
            ('THRESHOLD', "阈值", "全场景:按对角线长度与阈值比较决定选择状态"),
            ('MEDIAN', "均值减半", "当前选择:按尺寸排序后取消较小的一半(含同网格实例)"),
        ],
        default='THRESHOLD',
    )
    compare: bpy.props.EnumProperty(
        name="比较",
        items=[
            ('LESS', "小于阈值", "选中对角线长度小于阈值的物体"),
            ('GREATER', "大于阈值", "选中对角线长度大于阈值的物体"),
        ],
        default='LESS',
    )
    threshold: bpy.props.FloatProperty(
        name="尺寸阈值", default=1.0, min=0.0, unit='LENGTH',
        description="包围盒对角线长度阈值",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.row().prop(self, "mode", expand=True)
        if self.mode == 'THRESHOLD':
            layout.prop(self, "compare")
            layout.prop(self, "threshold")

    def execute(self, context):
        if self.mode == 'THRESHOLD':
            selected_count = 0
            for obj in context.scene.objects:
                length = _diagonal(obj)
                hit = length < self.threshold if self.compare == 'LESS' else length > self.threshold
                try:
                    obj.select_set(hit)
                except RuntimeError:
                    continue  # 不在当前视图层的物体无法改选择状态
                selected_count += hit
            self.report({'INFO'}, f"已选中 {selected_count} 个物体")
            return {'FINISHED'}

        measured = sorted(
            ((obj, _diagonal(obj)) for obj in context.selected_objects),
            key=lambda pair: pair[1],
        )
        if len(measured) < 2:
            self.report({'WARNING'}, "选中的物体不足 2 个")
            return {'CANCELLED'}

        # 网格数据 → 全部使用者,较小一半连带其所有实例一起取消
        data_users = {}
        for obj, _length in measured:
            if obj.data:
                data_users.setdefault(obj.data, []).append(obj)

        to_deselect = set()
        for obj, _length in measured[:len(measured) // 2]:
            if obj.data:
                to_deselect.update(data_users[obj.data])
            else:
                to_deselect.add(obj)

        for obj in to_deselect:
            obj.select_set(False)

        self.report({'INFO'}, f"已取消选择 {len(to_deselect)} 个较小物体")
        return {'FINISHED'}


class SHIYUME_OT_ArrangeObjects(bpy.types.Operator):
    """排列选中物体:网格模式按尺寸排序铺成二维阵列(整理散件资产),
    直线模式沿指定轴按当前坐标顺序等距排开"""
    bl_idname = "shiyume.arrange_objects"
    bl_label = "排列物体"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="模式",
        items=[
            ('GRID', "网格", "按尺寸排序,在 XY 平面铺成方阵"),
            ('LINE', "直线", "沿指定轴按当前坐标顺序等距排开"),
        ],
        default='GRID',
    )
    margin: bpy.props.FloatProperty(
        name="间距", default=0.1, min=0.0, unit='LENGTH',
        description="相邻物体之间的间隔距离",
    )
    axis: bpy.props.EnumProperty(
        name="排列轴",
        items=[('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", "")],
        default='X',
    )
    spacing: bpy.props.FloatProperty(
        name="步距", default=1.0, min=0.0, unit='LENGTH',
        description="直线模式下相邻物体锚点的间隔",
    )
    roots_only: bpy.props.BoolProperty(
        name="仅根物体",
        default=True,
        description="只移动无父级的物体,避免层级内的子物体被重复挪动",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.row().prop(self, "mode", expand=True)
        if self.mode == 'GRID':
            layout.prop(self, "margin")
        else:
            layout.prop(self, "axis")
            layout.prop(self, "spacing")
        layout.prop(self, "roots_only")

    def execute(self, context):
        objects = [
            obj for obj in context.selected_objects
            if not self.roots_only or obj.parent is None
        ]
        if not objects:
            self.report({'WARNING'}, "没有可排列的物体")
            return {'CANCELLED'}

        if self.mode == 'GRID':
            objects.sort(key=_diagonal)
            grid_size = math.ceil(math.sqrt(len(objects)))
            cursor_x = 0.0
            cursor_y = 0.0
            row_height = 0.0
            for index, obj in enumerate(objects):
                footprint = max(obj.dimensions.x, obj.dimensions.y)
                if index % grid_size == 0 and index != 0:
                    cursor_x = 0.0
                    cursor_y += row_height + self.margin
                    row_height = 0.0
                obj.location.x = cursor_x + footprint / 2.0
                obj.location.y = cursor_y + footprint / 2.0
                row_height = max(row_height, footprint)
                cursor_x += footprint + self.margin
        else:
            axis_index = 'XYZ'.index(self.axis)
            objects.sort(key=lambda obj: obj.location[axis_index])
            for index, obj in enumerate(objects):
                obj.location[axis_index] = index * self.spacing

        self.report({'INFO'}, f"已排列 {len(objects)} 个物体")
        return {'FINISHED'}


class SHIYUME_OT_ClearEmpty(bpy.types.Operator):
    """删除没有任何网格后代的空物体(只有其他空物体或空无一物的层级)"""
    bl_idname = "shiyume.clear_empty"
    bl_label = "清理空物体"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 从每个网格向上游走标记祖先,一趟 O(N·深度);未被标记的空物体即无网格后代
        keep = set()
        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            ancestor = obj.parent
            while ancestor is not None and ancestor not in keep:
                keep.add(ancestor)
                ancestor = ancestor.parent

        to_remove = [
            obj for obj in context.scene.objects
            if obj.type == 'EMPTY' and obj not in keep
        ]
        if not to_remove:
            self.report({'INFO'}, "没有可清理的空物体")
            return {'CANCELLED'}

        for obj in to_remove:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except ReferenceError:
                pass

        self.report({'INFO'}, f"已删除 {len(to_remove)} 个空物体")
        return {'FINISHED'}


class SHIYUME_OT_BatchRename(bpy.types.Operator):
    """规范化批量重命名:去掉 .001 之类的数字后缀,
    并按类型补前缀(网格/骨架/材质前缀均可自定义)"""
    bl_idname = "shiyume.batch_rename"
    bl_label = "批量重命名"
    bl_options = {'REGISTER', 'UNDO'}

    strip_suffix: bpy.props.BoolProperty(
        name="去除数字后缀", default=True,
        description="去掉名字末尾的 .001 / .002 等重名后缀",
    )
    mesh_prefix: bpy.props.StringProperty(name="网格前缀", default="Mesh_")
    armature_prefix: bpy.props.StringProperty(name="骨架前缀", default="Arm_")
    material_prefix: bpy.props.StringProperty(name="材质前缀", default="Mat_")
    rename_materials: bpy.props.BoolProperty(
        name="连带材质", default=True,
        description="同时规范化选中网格所用材质的名字",
    )

    _NUMBER_SUFFIX = re.compile(r'\.\d+$')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "strip_suffix")
        column = layout.column(align=True)
        column.prop(self, "mesh_prefix")
        column.prop(self, "armature_prefix")
        column.prop(self, "material_prefix")
        layout.prop(self, "rename_materials")

    def _normalize(self, name, prefix):
        if self.strip_suffix:
            name = self._NUMBER_SUFFIX.sub('', name)
        if prefix and not name.startswith(prefix):
            name = prefix + name
        return name

    def execute(self, context):
        renamed = 0
        seen_materials = set()
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                obj.name = self._normalize(obj.name, self.mesh_prefix)
                renamed += 1
                if self.rename_materials:
                    for slot in obj.material_slots:
                        material = slot.material
                        if material and material.name not in seen_materials:
                            material.name = self._normalize(material.name, self.material_prefix)
                            seen_materials.add(material.name)
            elif obj.type == 'ARMATURE':
                obj.name = self._normalize(obj.name, self.armature_prefix)
                renamed += 1

        self.report({'INFO'}, f"已重命名 {renamed} 个物体 / {len(seen_materials)} 个材质")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_SelectBySize,
    SHIYUME_OT_ArrangeObjects,
    SHIYUME_OT_ClearEmpty,
    SHIYUME_OT_BatchRename,
)
