"""法线与描边工具:平滑轮廓法线、UV 法线压缩(通用)、法线贴图正反向烘焙、一键描边。

shader 专属的法线功能(如 EndField 头发双法线)不放这里,进 endfield 模块。
"""

import bpy
import numpy as np

from ..core import batch, normal_map, smooth_normals

_WEIGHT_MODE_ITEMS = [
    ('ANGLE', "角度加权", "按每个角的张角加权平均(几何正确,推荐)"),
    ('UNIFORM', "算术平均", "所有角等权平均"),
]


# ---------------------------------------------------------------------------
# 平滑轮廓法线
# ---------------------------------------------------------------------------

class SHIYUME_OT_SmoothNormals(bpy.types.Operator):
    """平滑轮廓法线覆写:按空间位置聚合角法线(自动跨 UV 缝 / 硬边合并重合顶点),
    整体写入自定义拆分法线 —— 着色与描边方向立即变化,背面外扩描边的标准前置"""
    bl_idname = "shiyume.smooth_normals"
    bl_label = "平滑轮廓法线"
    bl_options = {'REGISTER', 'UNDO'}

    weight_mode: bpy.props.EnumProperty(
        name="加权方式", items=_WEIGHT_MODE_ITEMS, default='ANGLE',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "weight_mode")

    def execute(self, context):
        processed = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH' or len(obj.data.loops) == 0:
                continue
            mesh = obj.data
            smoothed = smooth_normals.smoothed_corner_normals(mesh, self.weight_mode)
            mesh.normals_split_custom_set(smoothed.tolist())
            mesh.update()
            processed += 1

        self.report({'INFO'}, f"已覆写 {processed} 个网格的自定义法线")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UV 法线压缩(通用机制)
# ---------------------------------------------------------------------------

class SHIYUME_OT_UVNormalCompress(bpy.types.Operator):
    """UV 法线压缩(通用):把法线场切线空间八面体编码后压进指定 UV 层,
    两个分量即可在引擎侧无损重建方向。来源可选当前显示法线(含自定义法线)
    或按空间位置聚合的平滑法线"""
    bl_idname = "shiyume.uv_normal_compress"
    bl_label = "UV法线压缩"
    bl_options = {'REGISTER', 'UNDO'}

    source: bpy.props.EnumProperty(
        name="法线来源",
        items=[
            ('CURRENT', "当前法线", "当前实际着色用的角法线(含自定义法线 / 硬边结果)"),
            ('SMOOTH', "平滑法线", "按空间位置聚合的平滑法线(跨缝合并重合顶点)"),
        ],
        default='CURRENT',
    )
    weight_mode: bpy.props.EnumProperty(
        name="加权方式", items=_WEIGHT_MODE_ITEMS, default='ANGLE',
        description="仅平滑法线来源使用",
    )
    uv_layer_name: bpy.props.StringProperty(
        name="UV 层名", default="UV2",
        description="写入目标 UV 层的名字,不存在则新建",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.row().prop(self, "source", expand=True)
        row = layout.row()
        row.active = self.source == 'SMOOTH'
        row.prop(self, "weight_mode")
        layout.prop(self, "uv_layer_name")

    def execute(self, context):
        processed = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH' or len(obj.data.loops) == 0:
                continue
            mesh = obj.data

            if self.source == 'SMOOTH':
                normals = smooth_normals.smoothed_corner_normals(mesh, self.weight_mode)
            else:
                normals = batch.read_corner_normals(mesh)

            error = smooth_normals.pack_octahedral_into_uv(mesh, normals, self.uv_layer_name)
            if error is not None:
                self.report({'WARNING'}, f"'{obj.name}' {error},跳过")
                continue
            processed += 1

        self.report({'INFO'}, f"已把 {processed} 个网格的法线压缩进 UV '{self.uv_layer_name}'")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# 法线贴图 → 网格
# ---------------------------------------------------------------------------

class SHIYUME_OT_NormalMapToMesh(bpy.types.Operator):
    """法线贴图烘焙到网格(纯净覆写自定义法线)。
    先剥离现有自定义法线、强制全平滑得到纯净几何基准面,再按切线空间把材质里的
    法线贴图解算成物体空间法线,整体覆盖写入网格的自定义法线 —— 结果 100% 由法线
    贴图接管。与"网格法线烘焙到贴图"互为逆操作"""
    bl_idname = "shiyume.normal_map_to_mesh"
    bl_label = "法线贴图烘焙到网格"
    bl_options = {'REGISTER', 'UNDO'}

    flip_green: bpy.props.BoolProperty(
        name="翻转绿色通道",
        default=False,
        description="按 DirectX 约定翻转 Y 分量;关闭则用 OpenGL 约定(须与贴图一致)",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object

        material = obj.active_material
        if not material or not material.use_nodes:
            self.report({'ERROR'}, "没有激活的材质或未启用节点")
            return {'CANCELLED'}

        node = normal_map.find_normal_image_node(material)
        if not node or not node.image:
            self.report({'ERROR'}, "未在材质中找到法线贴图")
            return {'CANCELLED'}

        mesh = obj.data
        if mesh.uv_layers.active is None:
            self.report({'ERROR'}, "网格缺少 UV,无法解算切线空间")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        image = node.image
        width, height = image.size
        pixel_matrix = normal_map.read_image_pixels(image)

        # 剥离旧自定义法线并强制平滑,得到与"反向烘焙"完全一致的纯净基准面。
        normal_map.clear_custom_split_normals(context, obj)
        normal_map.force_all_smooth(mesh)

        normals, tangents, bitangents = normal_map.read_loop_tangent_basis(mesh)
        uvs = batch.read_uvs(mesh)

        # 采样:UV → 像素行列(与反向烘焙共用同一取整约定)。
        column = np.clip((np.mod(uvs[:, 0], 1.0) * width).astype(np.int32), 0, width - 1)
        row = np.clip((np.mod(uvs[:, 1], 1.0) * height).astype(np.int32), 0, height - 1)
        sampled = pixel_matrix[row, column]

        # 解码切线空间法线(OpenGL;可选翻转绿色通道)。
        tangent_space = sampled[:, :3] * 2.0 - 1.0
        if self.flip_green:
            tangent_space[:, 1] = -tangent_space[:, 1]
        tangent_space = batch.normalize_rows(tangent_space)

        # 切线空间 → 物体空间:os = tx·T + ty·B + tz·N。
        object_space = (
            tangent_space[:, 0:1] * tangents
            + tangent_space[:, 1:2] * bitangents
            + tangent_space[:, 2:3] * normals
        )
        object_space = batch.normalize_rows(object_space)

        # 完全覆盖写入全新的自定义法线。
        mesh.normals_split_custom_set(object_space.tolist())
        mesh.update()

        self.report({'INFO'}, f"已从 {image.name} 覆写 {len(mesh.loops)} 条自定义法线")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# 网格 → 法线贴图
# ---------------------------------------------------------------------------

class SHIYUME_OT_MeshToNormalMap(bpy.types.Operator):
    """网格法线烘焙到贴图(反向:自定义法线 → 切线空间法线贴图)。
    对每个选中的网格,以其"清掉自定义法线、全平滑"的原始几何法线作为 base,读取当前
    自定义法线相对该 base 的差值,逐三角形 barycentric 光栅化进 UV。多个对象一起烘焙到
    同一张新建贴图(按名字复用,use_fake_user 保活),绝不覆盖材质里已有的任何贴图。
    与"法线贴图烘焙到网格"互为逆操作;全程在临时副本上取 base,不破坏原网格"""
    bl_idname = "shiyume.mesh_to_normal_map"
    bl_label = "网格法线烘焙到贴图"
    bl_options = {'REGISTER', 'UNDO'}

    image_name: bpy.props.StringProperty(
        name="贴图名",
        default="Baked_Normal",
        description="烘焙目标贴图的数据块名;已存在同名贴图则复用并覆盖其内容",
    )
    image_size: bpy.props.IntProperty(
        name="贴图尺寸",
        default=2048, min=16, max=8192,
        description="新建贴图的边长(复用已存在贴图时若尺寸不符则缩放到此值)",
    )
    margin: bpy.props.IntProperty(
        name="边缘外扩",
        default=8, min=0, max=64,
        description="向 UV 岛外扩张的像素圈数,消除采样 / mipmap 接缝",
    )
    flip_green: bpy.props.BoolProperty(
        name="翻转绿色通道",
        default=False,
        description="按 DirectX 约定翻转 Y 分量;关闭则用 OpenGL 约定",
    )

    @classmethod
    def poll(cls, context):
        active = context.active_object
        if active is not None and active.type == 'MESH':
            return True
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "image_name")
        layout.prop(self, "image_size")
        layout.prop(self, "margin")
        layout.prop(self, "flip_green")

    def execute(self, context):
        objects = self._gather_target_objects(context)
        if not objects:
            self.report({'ERROR'}, "没有带 UV 的网格被选中")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        image = self._resolve_new_image()
        width, height = image.size

        # 所有对象共享同一缓冲,逐个累加进去(后写覆盖先写,UV 重叠时以最后一个为准)。
        pixel_matrix = normal_map.new_flat_buffer(width, height)
        coverage = np.zeros((height, width), dtype=np.bool_)

        total_loops = 0
        for obj in objects:
            total_loops += self._bake_object(context, obj, pixel_matrix, coverage, width, height)

        # 边缘外扩,把已覆盖像素往 UV 岛外推,消除接缝。
        if self.margin > 0:
            normal_map.dilate(pixel_matrix, coverage, self.margin)

        # 写回贴图(法线贴图必须是 Non-Color)。
        image.colorspace_settings.name = 'Non-Color'
        normal_map.write_image_pixels(image, pixel_matrix)

        self.report(
            {'INFO'},
            f"已把 {len(objects)} 个对象 / {total_loops} 条法线烘焙到 {image.name} ({width}x{height})",
        )
        return {'FINISHED'}

    def _gather_target_objects(self, context):
        """收集所有带激活 UV 的选中网格;选区为空时退回活动对象。"""
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
        """取烘焙目标贴图:按名字新建,已存在同名则复用(尺寸不符则缩放),绝不碰材质。"""
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
        """把单个对象的自定义法线差值光栅化进共享缓冲,返回该对象的 loop 数。"""
        mesh = obj.data

        # 1. 当前实际角法线(含自定义法线),从原网格无损读取。
        current_normals = batch.read_corner_normals(mesh)

        # 2. base 切线基底:在临时副本上清自定义法线 + 全平滑,绝不污染原网格。
        normals, tangents, bitangents = self._base_tangent_basis(context, obj)

        # 3. 物体空间法线 → 切线空间:tx = T·os, ty = B·os, tz = N·os。
        tangent_space = np.stack(
            (
                np.sum(tangents * current_normals, axis=1),
                np.sum(bitangents * current_normals, axis=1),
                np.sum(normals * current_normals, axis=1),
            ),
            axis=1,
        )
        tangent_space = batch.normalize_rows(tangent_space)

        # 4. 逐 loop 的像素坐标(纹素中心落在整数坐标,故 -0.5 对齐)。
        uvs = batch.read_uvs(mesh)
        pixel_x = uvs[:, 0] * width - 0.5
        pixel_y = uvs[:, 1] * height - 0.5

        # 5. 三角形 → 像素:barycentric 插值 + 光栅化进共享缓冲。
        normal_map.rasterize_into(
            mesh, tangent_space, pixel_x, pixel_y, width, height, self.flip_green,
            pixel_matrix, coverage,
        )
        return len(mesh.loops)

    def _base_tangent_basis(self, context, obj):
        """在临时副本上构造 base(清自定义法线 + 全平滑),返回切线基底数组。

        副本与原网格拓扑完全一致(loop 序号一一对应),用完即删,原网格毫发无损。
        """
        temp_obj = obj.copy()
        temp_obj.data = obj.data.copy()
        context.collection.objects.link(temp_obj)
        try:
            normal_map.clear_custom_split_normals(context, temp_obj)
            normal_map.force_all_smooth(temp_obj.data)
            return normal_map.read_loop_tangent_basis(temp_obj.data)
        finally:
            temp_mesh = temp_obj.data
            bpy.data.objects.remove(temp_obj)
            bpy.data.meshes.remove(temp_mesh)


# ---------------------------------------------------------------------------
# 一键描边
# ---------------------------------------------------------------------------

class SHIYUME_OT_Outline(bpy.types.Operator):
    """一键描边(切换式):为网格追加背面剔除的描边材质 + 翻转法线的 Solidify;
    已有描边的物体再次执行会移除。忽略指定集合内的物体"""
    bl_idname = "shiyume.outline"
    bl_label = "一键描边"
    bl_options = {'REGISTER', 'UNDO'}

    thickness: bpy.props.FloatProperty(
        name="描边厚度", default=0.001, min=0.0, precision=4, unit='LENGTH',
    )
    color: bpy.props.FloatVectorProperty(
        name="描边颜色", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0),
        description="仅在首次创建描边材质时生效",
    )
    material_name: bpy.props.StringProperty(name="材质名", default="Outline")
    vertex_group: bpy.props.StringProperty(
        name="厚度顶点组", default="Alpha",
        description="Solidify 的厚度权重顶点组(留空则不使用)",
    )
    only_selected: bpy.props.BoolProperty(
        name="仅选中物体", default=False,
        description="关闭时处理场景内全部网格",
    )
    ignore_collection: bpy.props.StringProperty(
        name="忽略集合", default="IgnoreExport",
        description="该集合(含子集合)内的物体不参与描边",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        column = layout.column(align=True)
        column.prop(self, "thickness")
        column.prop(self, "color")
        layout.prop(self, "material_name")
        layout.prop(self, "vertex_group")
        layout.prop(self, "only_selected")
        layout.prop(self, "ignore_collection")

    def _resolve_material(self):
        material = bpy.data.materials.get(self.material_name)
        if material is None:
            material = bpy.data.materials.new(name=self.material_name)
            material.use_nodes = True
            bsdf = material.node_tree.nodes.get('Principled BSDF')
            if bsdf:
                bsdf.inputs['Base Color'].default_value = tuple(self.color)
                roughness = bsdf.inputs.get('Roughness')
                if roughness:
                    roughness.default_value = 1.0
            material.use_backface_culling = True
        return material

    @staticmethod
    def _collection_members(collection):
        members = set(collection.objects)
        for child in collection.children_recursive:
            members.update(child.objects)
        return members

    def _toggle(self, obj, material):
        has_material = any(
            slot.material and slot.material.name == material.name
            for slot in obj.material_slots
        )
        has_solidify = any(
            modifier.type == 'SOLIDIFY' and modifier.name == 'Solidify'
            for modifier in obj.modifiers
        )

        if has_material and has_solidify:
            for modifier in obj.modifiers:
                if modifier.type == 'SOLIDIFY' and modifier.name == 'Solidify':
                    obj.modifiers.remove(modifier)
                    break
            for index, slot in enumerate(obj.material_slots):
                if slot.material and slot.material.name == material.name:
                    obj.data.materials.pop(index=index)
                    break
            return False

        if not has_material:
            obj.data.materials.append(material)
        if not has_solidify:
            modifier = obj.modifiers.new(name='Solidify', type='SOLIDIFY')
            modifier.thickness = self.thickness
            modifier.use_flip_normals = True
            modifier.use_quality_normals = True
            modifier.vertex_group = self.vertex_group
            modifier.material_offset = len(obj.material_slots) - 1
        return True

    def execute(self, context):
        ignored = set()
        collection = bpy.data.collections.get(self.ignore_collection)
        if collection:
            ignored = self._collection_members(collection)

        material = self._resolve_material()
        targets = context.selected_objects if self.only_selected else bpy.data.objects

        added = 0
        removed = 0
        for obj in targets:
            if obj.type != 'MESH' or obj in ignored:
                continue
            if self._toggle(obj, material):
                added += 1
            else:
                removed += 1

        self.report({'INFO'}, f"描边:新增 {added} / 移除 {removed}")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_SmoothNormals,
    SHIYUME_OT_UVNormalCompress,
    SHIYUME_OT_NormalMapToMesh,
    SHIYUME_OT_MeshToNormalMap,
    SHIYUME_OT_Outline,
)
