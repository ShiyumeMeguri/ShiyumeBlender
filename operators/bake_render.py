"""渲染 / 烘焙工具:UV 布局渲染贴图(双来源双引擎)、视口截屏、材质批量烘焙。"""

import os
import tempfile

import bpy


# ---------------------------------------------------------------------------
# 场景设置保存 / 恢复
# ---------------------------------------------------------------------------

def _save_scene_settings():
    scene = bpy.context.scene
    return {
        'camera': scene.camera,
        'engine': scene.render.engine,
        'dither': scene.render.dither_intensity,
        'light': scene.display.shading.light,
        'color': scene.display.shading.color_type,
        'res_x': scene.render.resolution_x,
        'res_y': scene.render.resolution_y,
        'transparent': scene.render.film_transparent,
        'samples': scene.cycles.samples if hasattr(scene, 'cycles') else None,
    }


def _restore_scene_settings(settings):
    if not settings:
        return
    scene = bpy.context.scene
    scene.camera = settings['camera']
    scene.render.engine = settings['engine']
    scene.render.dither_intensity = settings['dither']
    scene.display.shading.light = settings['light']
    scene.display.shading.color_type = settings['color']
    scene.render.resolution_x = settings['res_x']
    scene.render.resolution_y = settings['res_y']
    scene.render.film_transparent = settings['transparent']
    if settings['samples'] is not None and hasattr(scene, 'cycles'):
        scene.cycles.samples = settings['samples']


def _unique_output_path(directory, base_name):
    filename = f"{base_name}.png"
    count = 1
    while os.path.exists(os.path.join(directory, filename)):
        filename = f"{base_name}_{count}.png"
        count += 1
    return os.path.join(directory, filename)


def _texture_directory():
    """.blend 旁的 Textures/ 输出目录;未保存返回 None。"""
    blend_path = bpy.data.filepath
    if not blend_path:
        return None
    directory = os.path.join(os.path.dirname(blend_path), 'Textures')
    os.makedirs(directory, exist_ok=True)
    return directory


# ---------------------------------------------------------------------------
# Workbench 平面渲染路径
# ---------------------------------------------------------------------------

def _setup_uv_camera_and_workbench(resolution):
    """0..1 UV 平面正交相机 + Workbench 平光贴图渲染设置。"""
    scene = bpy.context.scene

    camera = bpy.data.objects.get('UV_Camera')
    if not camera:
        camera_data = bpy.data.cameras.new(name='UV_Camera')
        camera = bpy.data.objects.new('UV_Camera', camera_data)
        scene.collection.objects.link(camera)
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 1
    camera.location = (0.5, 0.5, 1)
    camera.rotation_euler = (0, 0, 0)
    scene.camera = camera

    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.dither_intensity = 0
    scene.display.shading.light = 'FLAT'
    scene.display.shading.color_type = 'TEXTURE'
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.film_transparent = True


def _prepare_duplicates(objects, join_into_one):
    """复制网格(固化形态键),可选合并为单体;去重顶点、下沉 0.1m、加双 Solidify。"""
    duplicates = []
    for obj in objects:
        if obj.type != 'MESH':
            continue
        new_obj = obj.copy()
        new_obj.data = obj.data.copy()
        new_obj.name = f"{obj.name}_duplicate"

        # 保证渲染采样用的是"渲染激活"UV
        for uv_layer in new_obj.data.uv_layers:
            if uv_layer.active_render:
                new_obj.data.uv_layers.active = uv_layer
                break

        bpy.context.collection.objects.link(new_obj)

        # 形态键必须先固化,否则去重顶点会报错或跑形
        if new_obj.data.shape_keys:
            bpy.ops.object.select_all(action='DESELECT')
            new_obj.select_set(True)
            bpy.context.view_layer.objects.active = new_obj
            bpy.ops.object.convert(target='MESH')

        duplicates.append(new_obj)

    if not duplicates:
        return []

    bpy.ops.object.select_all(action='DESELECT')
    for obj in duplicates:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = duplicates[0]

    if join_into_one and len(duplicates) > 1:
        bpy.ops.object.join()
        duplicates = [bpy.context.active_object]

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles()
    bpy.ops.object.mode_set(mode='OBJECT')

    for obj in duplicates:
        obj.location.z -= 0.1
        obj.modifiers.new(name="SOLIDIFY_1", type='SOLIDIFY')
        second = obj.modifiers.new(name="SOLIDIFY_2", type='SOLIDIFY')
        second.thickness = 0.002
        second.offset = 1

    return duplicates


def _delete_objects(objects):
    bpy.ops.object.select_all(action='DESELECT')
    alive = [obj for obj in objects if obj and obj.name in bpy.data.objects]
    for obj in alive:
        obj.select_set(True)
    if alive:
        bpy.ops.object.delete(use_global=False)


def _remove_uv_camera():
    camera = bpy.data.objects.get('UV_Camera')
    if camera:
        camera_data = camera.data
        bpy.data.objects.remove(camera, do_unlink=True)
        if camera_data and camera_data.users == 0:
            bpy.data.cameras.remove(camera_data)


# ---------------------------------------------------------------------------
# Cycles 烘焙路径
# ---------------------------------------------------------------------------

_BAKE_NODE_NAME = '_ShiyumeBakeTarget'


def _insert_bake_targets(obj, bake_image):
    """向物体每个启用节点的材质插入未连接的烘焙目标节点并设为激活。"""
    created_nodes = []
    if not obj.data.materials:
        return created_nodes

    for material in obj.data.materials:
        if not material or not material.use_nodes:
            continue
        tree = material.node_tree
        node = tree.nodes.new('ShaderNodeTexImage')
        node.name = _BAKE_NODE_NAME
        node.label = _BAKE_NODE_NAME
        node.image = bake_image
        node.location = (400, 400)
        for other in tree.nodes:
            other.select = False
        node.select = True
        tree.nodes.active = node
        created_nodes.append((material, node))

    return created_nodes


def _remove_bake_targets(created_nodes):
    for material, node in created_nodes:
        if material and material.use_nodes and node.name in material.node_tree.nodes:
            material.node_tree.nodes.remove(node)


# ---------------------------------------------------------------------------
# 算子:UV 布局渲染贴图
# ---------------------------------------------------------------------------

class SHIYUME_OT_RenderUVTexture(bpy.types.Operator):
    """把网格按 UV 布局渲染成贴图,输出到 .blend 旁的 Textures/ 文件夹。
    来源可选"选中物体"或指定集合;引擎可选 Workbench 平光(所见即所得)
    或 Cycles 烘焙(自发光/漫反射/综合/法线)"""
    bl_idname = "shiyume.render_uv_texture"
    bl_label = "UV渲染贴图"
    bl_options = {'REGISTER', 'UNDO'}

    source: bpy.props.EnumProperty(
        name="来源",
        items=[
            ('SELECTED', "选中物体", "渲染当前选中的网格,各自保留独立 UV"),
            ('COLLECTION', "指定集合", "渲染集合内全部网格,合并为单体后渲染"),
        ],
        default='SELECTED',
    )
    collection_name: bpy.props.StringProperty(
        name="集合名", default="RT",
        description="来源为指定集合时使用;不存在会自动创建并提示",
    )
    engine: bpy.props.EnumProperty(
        name="引擎",
        items=[
            ('WORKBENCH', "Workbench 平光", "平光贴图正交渲染,速度最快"),
            ('CYCLES', "Cycles 烘焙", "按烘焙类型烘焙到新贴图"),
        ],
        default='WORKBENCH',
    )
    resolution: bpy.props.IntProperty(
        name="分辨率", default=2048, min=128, max=8192,
    )
    bake_type: bpy.props.EnumProperty(
        name="烘焙类型",
        items=[
            ('EMIT', "Emit (自发光/纯色)", "烘焙材质表面颜色,适合贴图直连输出的着色器"),
            ('COMBINED', "Combined (综合)", "烘焙综合渲染结果,含光照"),
            ('DIFFUSE', "Diffuse (漫反射)", "仅烘焙漫反射颜色"),
            ('NORMAL', "Normal (法线)", "烘焙法线贴图"),
        ],
        default='EMIT',
    )
    bake_samples: bpy.props.IntProperty(
        name="烘焙采样数", default=32, min=1, max=4096,
    )
    keep_temp: bpy.props.BoolProperty(
        name="保留临时对象", default=False,
        description="保留渲染用的副本与相机,便于排查(仅 Workbench)",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.row().prop(self, "source", expand=True)
        if self.source == 'COLLECTION':
            layout.prop(self, "collection_name")
        layout.prop(self, "engine")
        layout.prop(self, "resolution")
        if self.engine == 'CYCLES':
            layout.prop(self, "bake_type")
            layout.prop(self, "bake_samples")
        else:
            layout.prop(self, "keep_temp")

    def _gather_objects(self, context):
        if self.source == 'SELECTED':
            meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
            if not meshes:
                self.report({'WARNING'}, "未选中任何网格对象")
            return meshes

        collection = bpy.data.collections.get(self.collection_name)
        if not collection:
            collection = bpy.data.collections.new(self.collection_name)
            context.scene.collection.children.link(collection)
            self.report({'WARNING'}, f"已创建集合 '{self.collection_name}',请放入网格后再次运行")
            return []
        meshes = [obj for obj in collection.objects if obj.type == 'MESH']
        if not meshes:
            self.report({'WARNING'}, f"集合 '{self.collection_name}' 中没有网格")
        return meshes

    def _base_name(self, context, meshes):
        if self.source == 'COLLECTION':
            return f"{self.collection_name}_Combined"
        active = context.active_object
        prefix = active.name if active and active in meshes else "Selected_Combined"
        return f"{prefix}_UVRender"

    def execute(self, context):
        texture_directory = _texture_directory()
        if texture_directory is None:
            self.report({'ERROR'}, "请先保存 .blend 文件")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        meshes = self._gather_objects(context)
        if not meshes:
            return {'CANCELLED'}

        if self.engine == 'WORKBENCH':
            return self._render_workbench(context, meshes, texture_directory)
        return self._render_cycles_bake(context, meshes, texture_directory)

    # ------------------------------------------------------------------

    def _render_workbench(self, context, meshes, texture_directory):
        settings = _save_scene_settings()
        hide_states = {}
        duplicates = []

        try:
            _setup_uv_camera_and_workbench(self.resolution)
            hide_states = {obj.name: obj.hide_render for obj in bpy.data.objects}
            for obj in bpy.data.objects:
                obj.hide_render = True

            duplicates = _prepare_duplicates(meshes, join_into_one=self.source == 'COLLECTION')
            if not duplicates:
                self.report({'WARNING'}, "处理对象失败")
                return {'CANCELLED'}

            for obj in duplicates:
                obj.hide_render = False

            output = _unique_output_path(texture_directory, self._base_name(context, meshes))
            context.scene.render.filepath = output
            bpy.ops.render.render(write_still=True)
            self.report({'INFO'}, f"纹理已保存至 '{output}'")

        except Exception as error:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"发生错误: {error}")
            return {'CANCELLED'}

        finally:
            _restore_scene_settings(settings)
            for name, hidden in hide_states.items():
                obj = bpy.data.objects.get(name)
                if obj:
                    obj.hide_render = hidden
            if not self.keep_temp:
                _delete_objects(duplicates)
                _remove_uv_camera()
            self._restore_selection(context, meshes)

        return {'FINISHED'}

    # ------------------------------------------------------------------

    def _render_cycles_bake(self, context, meshes, texture_directory):
        settings = _save_scene_settings()
        created_nodes = []
        scene = context.scene
        bake = scene.render.bake
        bake_backup = {
            'direct': bake.use_pass_direct,
            'indirect': bake.use_pass_indirect,
            'color': getattr(bake, 'use_pass_color', None),
            'margin': bake.margin,
            'clear': bake.use_clear,
            'target': getattr(bake, 'target', None),
        }

        try:
            scene.render.engine = 'CYCLES'
            scene.render.resolution_x = self.resolution
            scene.render.resolution_y = self.resolution
            scene.render.film_transparent = True
            if hasattr(scene, 'cycles'):
                scene.cycles.samples = self.bake_samples

            base_name = self._base_name(context, meshes)
            image_name = f"{base_name}_Bake"
            existing = bpy.data.images.get(image_name)
            if existing:
                bpy.data.images.remove(existing)
            bake_image = bpy.data.images.new(image_name, width=self.resolution,
                                             height=self.resolution, alpha=True)
            bake_image.generated_color = (0, 0, 0, 0)

            for obj in meshes:
                created_nodes.extend(_insert_bake_targets(obj, bake_image))

            bpy.ops.object.select_all(action='DESELECT')
            for obj in meshes:
                obj.select_set(True)
            active = context.active_object
            context.view_layer.objects.active = active if active in meshes else meshes[0]

            bake.use_clear = True
            bake.margin = 16
            if hasattr(bake, 'target'):
                bake.target = 'IMAGE_TEXTURES'

            if self.bake_type == 'DIFFUSE':
                bake.use_pass_direct = False
                bake.use_pass_indirect = False
                if hasattr(bake, 'use_pass_color'):
                    bake.use_pass_color = True
            bpy.ops.object.bake(type=self.bake_type)

            output = _unique_output_path(texture_directory, f"{base_name}_Bake")
            bake_image.filepath_raw = output
            bake_image.file_format = 'PNG'
            bake_image.save()
            self.report({'INFO'}, f"烘焙贴图已保存至 '{output}'")

        except Exception as error:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Cycles 烘焙失败: {error}")
            return {'CANCELLED'}

        finally:
            _remove_bake_targets(created_nodes)
            _restore_scene_settings(settings)
            bake.use_pass_direct = bake_backup['direct']
            bake.use_pass_indirect = bake_backup['indirect']
            if bake_backup['color'] is not None and hasattr(bake, 'use_pass_color'):
                bake.use_pass_color = bake_backup['color']
            bake.margin = bake_backup['margin']
            bake.use_clear = bake_backup['clear']
            if bake_backup['target'] is not None and hasattr(bake, 'target'):
                bake.target = bake_backup['target']
            self._restore_selection(context, meshes)

        return {'FINISHED'}

    @staticmethod
    def _restore_selection(context, meshes):
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            try:
                obj.select_set(True)
            except Exception:
                pass
        if context.active_object in meshes:
            context.view_layer.objects.active = context.active_object


# ---------------------------------------------------------------------------
# 算子:视口截屏
# ---------------------------------------------------------------------------

class SHIYUME_OT_ViewportScreenshot(bpy.types.Operator):
    """把当前 3D 视口按其像素尺寸 OpenGL 渲染为 PNG 存到系统临时目录。
    自动临时关闭叠加层,渲染完成后还原全部设置"""
    bl_idname = "shiyume.viewport_screenshot"
    bl_label = "视口截屏"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        backup = {
            'res_x': scene.render.resolution_x,
            'res_y': scene.render.resolution_y,
            'filepath': scene.render.filepath,
            'format': scene.render.image_settings.file_format,
        }

        overlay_spaces = []
        for area in context.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    scene.render.resolution_x = region.width
                    scene.render.resolution_y = region.height
            for space in area.spaces:
                if space.type == 'VIEW_3D' and space.overlay.show_overlays:
                    overlay_spaces.append(space)
                    space.overlay.show_overlays = False

        output_path = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
        scene.render.filepath = output_path
        scene.render.image_settings.file_format = 'PNG'

        try:
            bpy.ops.render.opengl(write_still=True, view_context=True)
        except RuntimeError as error:
            self.report({'ERROR'}, f"渲染失败(需要 3D 视口与 OpenGL 上下文): {error}")
            return {'CANCELLED'}
        finally:
            for space in overlay_spaces:
                space.overlay.show_overlays = True
            scene.render.resolution_x = backup['res_x']
            scene.render.resolution_y = backup['res_y']
            scene.render.filepath = backup['filepath']
            scene.render.image_settings.file_format = backup['format']

        print(f"视口截屏已保存: {output_path}")
        self.report({'INFO'}, f"已保存: {output_path}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# 算子:材质批量烘焙
# ---------------------------------------------------------------------------

class SHIYUME_OT_BatchBakeTextures(bpy.types.Operator):
    """把所有启用节点且带贴图的材质逐个烘焙到 .blend 旁的 BakeTex/ 文件夹。
    自动创建临时平面与烘焙节点,结束后全部清理"""
    bl_idname = "shiyume.batch_bake_textures"
    bl_label = "批量烘焙所有材质"
    bl_options = {'REGISTER'}

    bake_type: bpy.props.EnumProperty(
        name="烘焙类型",
        items=[
            ('COMBINED', "Combined (综合)", ""),
            ('DIFFUSE', "Diffuse (漫反射)", ""),
            ('EMIT', "Emit (自发光)", ""),
        ],
        default='COMBINED',
    )
    skip_existing: bpy.props.BoolProperty(
        name="跳过已存在", default=True,
        description="输出文件已存在时跳过该材质",
    )

    def execute(self, context):
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({'ERROR'}, "请先保存 .blend 文件")
            return {'CANCELLED'}
        output_directory = os.path.join(os.path.dirname(blend_path), "BakeTex")
        os.makedirs(output_directory, exist_ok=True)

        original_engine = context.scene.render.engine
        bpy.ops.mesh.primitive_plane_add(size=2)
        plane = context.active_object
        context.scene.render.engine = 'CYCLES'

        baked = 0
        try:
            for material in bpy.data.materials:
                if not material.use_nodes:
                    continue
                texture_node = next(
                    (node for node in material.node_tree.nodes
                     if node.type == 'TEX_IMAGE' and node.image),
                    None,
                )
                if not texture_node:
                    continue

                source_image = texture_node.image
                output_path = os.path.join(output_directory, source_image.name + ".png")
                if self.skip_existing and os.path.exists(output_path):
                    continue

                bake_image = bpy.data.images.new(
                    name=source_image.name + "_Bake",
                    width=source_image.size[0], height=source_image.size[1],
                )
                if not plane.data.materials:
                    plane.data.materials.append(material)
                else:
                    plane.data.materials[0] = material

                node = material.node_tree.nodes.new(type='ShaderNodeTexImage')
                node.image = bake_image
                material.node_tree.nodes.active = node

                try:
                    bpy.ops.object.bake(type=self.bake_type)
                    bake_image.filepath_raw = output_path
                    bake_image.file_format = 'PNG'
                    bake_image.save()
                    baked += 1
                finally:
                    material.node_tree.nodes.remove(node)
                    bpy.data.images.remove(bake_image)
        finally:
            if plane and plane.name in bpy.data.objects:
                plane_mesh = plane.data
                bpy.data.objects.remove(plane, do_unlink=True)
                if plane_mesh.users == 0:
                    bpy.data.meshes.remove(plane_mesh)
            context.scene.render.engine = original_engine

        self.report({'INFO'}, f"已烘焙 {baked} 个材质到 {output_directory}")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_RenderUVTexture,
    SHIYUME_OT_ViewportScreenshot,
    SHIYUME_OT_BatchBakeTextures,
)
