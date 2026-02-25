import bpy
import os


def PrepareMeshesForRender(objects_to_process, resolution):
    """
    此函数与您提供的版本类似的逻辑，但改为处理多个对象而不合并，以支持各自独立的 UV 贴图。
    它获取对象列表，复制它们，然后批量应用修改。
    """
    duplicates = []
    
    # [优化] 1. 先复制所有对象
    for obj in objects_to_process:
        if obj.type == 'MESH':
            # 创建对象和数据的副本
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = f"{obj.name}_duplicate"
            
            # [修正] 确保使用被标记为"渲染激活"的 UV 贴图作为激活贴图
            render_uv = None
            for uv in new_obj.data.uv_layers:
                if uv.active_render:
                    render_uv = uv
                    break
            
            if render_uv:
                new_obj.data.uv_layers.active = render_uv
            
            bpy.context.collection.objects.link(new_obj)
            
            # [修正] 如果有形态键，需要先应用它们，否则 remove_doubles 会出错或导致形状错乱
            if new_obj.data.shape_keys:
                bpy.ops.object.select_all(action='DESELECT')
                new_obj.select_set(True)
                bpy.context.view_layer.objects.active = new_obj
                bpy.ops.object.convert(target='MESH')
            
            duplicates.append(new_obj)

    if not duplicates:
        return []

    # [优化] 2. 选中所有副本进行批量编辑
    bpy.ops.object.select_all(action='DESELECT')
    for obj in duplicates:
        obj.select_set(True)
    
    if duplicates:
        bpy.context.view_layer.objects.active = duplicates[0]
    
    # 进入编辑模式合并顶点 (多对象编辑)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles()
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # [优化] 3. 对每个对象应用修改器和位移
    for obj in duplicates:
        # 将副本向下移动0.1m
        obj.location.z -= 0.1
        
        # 添加实体化修改器
        solidify1 = obj.modifiers.new(name="SOLIDIFY_1", type='SOLIDIFY')
        solidify2 = obj.modifiers.new(name="SOLIDIFY_2", type='SOLIDIFY')
        solidify2.thickness = 0.002
        solidify2.offset = 1

    return duplicates


# ---------------------------------------------------------------------------
# Settings save / restore helpers
# ---------------------------------------------------------------------------

def _save_scene_settings():
    """Save all scene settings that may be modified by either render mode."""
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
        # Cycles-specific
        'samples': scene.cycles.samples if hasattr(scene, 'cycles') else None,
    }


def _restore_scene_settings(settings):
    """Restore all scene settings saved by _save_scene_settings."""
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


# ---------------------------------------------------------------------------
# Workbench render path (original behaviour)
# ---------------------------------------------------------------------------

def _setup_workbench(resolution):
    """Configure scene for Workbench flat-texture render and create UV camera."""
    scene = bpy.context.scene

    # Camera
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

    # Workbench settings
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.dither_intensity = 0
    scene.display.shading.light = 'FLAT'
    scene.display.shading.color_type = 'TEXTURE'
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.film_transparent = True


def _render_workbench(operator, context, selected_meshes, tex_dir, resolution, keep_temp):
    """Execute the Workbench (flat texture) render path."""
    orig_settings = _save_scene_settings()
    original_hide_states = {}
    objects_to_delete = []

    try:
        _setup_workbench(resolution)
        original_hide_states = {obj.name: obj.hide_render for obj in bpy.data.objects}

        for obj in bpy.data.objects:
            obj.hide_render = True

        objects_to_delete = PrepareMeshesForRender(selected_meshes, resolution)

        if objects_to_delete:
            for obj in objects_to_delete:
                obj.hide_render = False

            active_obj = context.active_object
            baseName = active_obj.name if active_obj and active_obj in selected_meshes else "Selected_Combined"
            filename = f"{baseName}_UVRender.png"
            count = 1
            while os.path.exists(os.path.join(tex_dir, filename)):
                filename = f"{baseName}_UVRender_{count}.png"
                count += 1
            output = os.path.join(tex_dir, filename)

            bpy.context.scene.render.filepath = output
            bpy.ops.render.render(write_still=True)
            operator.report({'INFO'}, f"纹理已保存至 '{output}'")
        else:
            operator.report({'WARNING'}, "处理对象失败。")

    except Exception as e:
        import traceback
        traceback.print_exc()
        operator.report({'ERROR'}, f"发生错误: {e}")
        return {'CANCELLED'}

    finally:
        _restore_scene_settings(orig_settings)

        for obj_name, is_hidden in original_hide_states.items():
            obj = bpy.data.objects.get(obj_name)
            if obj:
                obj.hide_render = is_hidden

        if not keep_temp:
            if objects_to_delete:
                bpy.ops.object.select_all(action='DESELECT')
                for obj in objects_to_delete:
                    if obj.name in bpy.data.objects:
                        obj.select_set(True)
                bpy.ops.object.delete(use_global=False)
            uv_cam = bpy.data.objects.get('UV_Camera')
            if uv_cam:
                cam_data = uv_cam.data
                bpy.data.objects.remove(uv_cam, do_unlink=True)
                if cam_data and cam_data.users == 0:
                    bpy.data.cameras.remove(cam_data)
        else:
            if objects_to_delete:
                bpy.ops.object.select_all(action='DESELECT')
                for obj in objects_to_delete:
                    if obj.name in bpy.data.objects:
                        obj.select_set(True)
                bpy.ops.object.delete(use_global=False)

        _restore_selection(selected_meshes, context)

    return {'FINISHED'}


# ---------------------------------------------------------------------------
# Cycles bake path (new)
# ---------------------------------------------------------------------------

_BAKE_NODE_NAME = '_ShiyumeBakeTarget'


def _setup_cycles_bake(resolution, bake_samples):
    """Configure scene for Cycles bake."""
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    # 使用 CPU 以确保兼容性；如果用户有 GPU 则可手动切换
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.film_transparent = True
    scene.cycles.samples = bake_samples


def _create_bake_image(name, resolution):
    """Create or reuse a blank image for bake target."""
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, width=resolution, height=resolution, alpha=True)
    img.generated_color = (0, 0, 0, 0)
    return img


def _prepare_materials_for_bake(obj, bake_image):
    """Insert a bake-target Image Texture node into every material that uses nodes.

    Does NOT modify the shader graph or create default materials.
    Only adds an unconnected Image Texture node and selects it as active
    (required by Cycles to know which image to bake into).

    Returns a list of (material, node) pairs for cleanup.
    """
    created_nodes = []

    if not obj.data.materials:
        return created_nodes

    for mat in obj.data.materials:
        if not mat or not mat.use_nodes:
            continue

        tree = mat.node_tree
        # Add an unconnected Image Texture node as the bake target
        node = tree.nodes.new('ShaderNodeTexImage')
        node.name = _BAKE_NODE_NAME
        node.label = _BAKE_NODE_NAME
        node.image = bake_image
        node.location = (400, 400)
        # Select ONLY this node (Cycles bakes into the active image texture node)
        for n in tree.nodes:
            n.select = False
        node.select = True
        tree.nodes.active = node
        created_nodes.append((mat, node))

    return created_nodes


def _cleanup_bake_nodes(created_nodes):
    """Remove the temporary bake-target image texture nodes."""
    for mat, node in created_nodes:
        if mat and mat.use_nodes and node.name in mat.node_tree.nodes:
            mat.node_tree.nodes.remove(node)


def _render_cycles_bake(operator, context, selected_meshes, tex_dir, resolution,
                        bake_type, bake_samples):
    """Execute the Cycles bake path."""
    orig_settings = _save_scene_settings()
    created_nodes_all = []

    # Save bake pass settings to restore later
    scene = bpy.context.scene
    bake = scene.render.bake
    orig_bake_pass_direct = bake.use_pass_direct
    orig_bake_pass_indirect = bake.use_pass_indirect
    orig_bake_pass_color = getattr(bake, 'use_pass_color', None)
    orig_bake_margin = bake.margin
    orig_bake_clear = bake.use_clear
    orig_bake_target = getattr(bake, 'target', None)

    try:
        _setup_cycles_bake(resolution, bake_samples)

        active_obj = context.active_object
        baseName = active_obj.name if active_obj and active_obj in selected_meshes else "Selected_Combined"
        img_name = f"{baseName}_Bake"
        bake_image = _create_bake_image(img_name, resolution)

        # Prepare materials on every selected mesh
        for obj in selected_meshes:
            nodes = _prepare_materials_for_bake(obj, bake_image)
            created_nodes_all.extend(nodes)

        # Select only the meshes to bake
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_meshes:
            obj.select_set(True)
        if active_obj and active_obj in selected_meshes:
            context.view_layer.objects.active = active_obj
        else:
            context.view_layer.objects.active = selected_meshes[0]

        # Configure bake settings
        bake.use_clear = True
        bake.margin = 16

        # Ensure bake target is IMAGE_TEXTURES (Blender 4.x)
        if hasattr(bake, 'target'):
            bake.target = 'IMAGE_TEXTURES'

        # Perform bake
        if bake_type == 'DIFFUSE':
            bake.use_pass_direct = False
            bake.use_pass_indirect = False
            if hasattr(bake, 'use_pass_color'):
                bake.use_pass_color = True
            bpy.ops.object.bake(type='DIFFUSE')
        elif bake_type == 'COMBINED':
            bpy.ops.object.bake(type='COMBINED')
        elif bake_type == 'EMIT':
            bpy.ops.object.bake(type='EMIT')
        elif bake_type == 'NORMAL':
            bpy.ops.object.bake(type='NORMAL')
        else:
            bpy.ops.object.bake(type=bake_type)

        # Save image
        filename = f"{baseName}_Bake.png"
        count = 1
        while os.path.exists(os.path.join(tex_dir, filename)):
            filename = f"{baseName}_Bake_{count}.png"
            count += 1
        output = os.path.join(tex_dir, filename)

        bake_image.filepath_raw = output
        bake_image.file_format = 'PNG'
        bake_image.save()

        operator.report({'INFO'}, f"烘焙贴图已保存至 '{output}'")

    except Exception as e:
        import traceback
        traceback.print_exc()
        operator.report({'ERROR'}, f"Cycles 烘焙失败: {e}")
        return {'CANCELLED'}

    finally:
        _cleanup_bake_nodes(created_nodes_all)
        _restore_scene_settings(orig_settings)
        # Restore bake settings
        bake.use_pass_direct = orig_bake_pass_direct
        bake.use_pass_indirect = orig_bake_pass_indirect
        if orig_bake_pass_color is not None and hasattr(bake, 'use_pass_color'):
            bake.use_pass_color = orig_bake_pass_color
        bake.margin = orig_bake_margin
        bake.use_clear = orig_bake_clear
        if orig_bake_target is not None and hasattr(bake, 'target'):
            bake.target = orig_bake_target
        _restore_selection(selected_meshes, context)

    return {'FINISHED'}


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def _restore_selection(selected_meshes, context):
    """Restore the original selection state."""
    bpy.ops.object.select_all(action='DESELECT')
    for obj in selected_meshes:
        try:
            obj.select_set(True)
        except Exception:
            pass
    if context.active_object in selected_meshes:
        context.view_layer.objects.active = context.active_object


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class SHIYUME_OT_RenderViewportAsTexture(bpy.types.Operator):
    """渲染选中网格为 UV 贴图（支持 Workbench 纯色 与 Cycles 烘焙 两种模式）"""
    bl_idname = "shiyume.render_viewport_texture"
    bl_label = "渲染视图为贴图"
    bl_options = {'REGISTER', 'UNDO'}

    render_mode: bpy.props.EnumProperty(
        name="渲染模式",
        items=[
            ('WORKBENCH', "Workbench (纯色)", "使用 Workbench 引擎平光纹理渲染（原始行为）"),
            ('CYCLES', "Cycles (烘焙)", "使用 Cycles 引擎烘焙贴图"),
        ],
        default='WORKBENCH',
    )

    resolution: bpy.props.IntProperty(
        name="分辨率",
        default=2048,
        min=128,
        max=8192,
        description="渲染纹理的分辨率"
    )

    keep_temp: bpy.props.BoolProperty(
        name="保留临时对象",
        default=False,
        description="是否保留渲染过程中创建的临时对象(相机、副本等)。仅 Workbench 模式使用。"
    )

    bake_type: bpy.props.EnumProperty(
        name="烘焙类型",
        items=[
            ('EMIT', "Emit (自发光/纯色)", "烘焙材质表面颜色。适合贴图直连输出的着色器"),
            ('COMBINED', "Combined (综合)", "烘焙综合渲染结果，含光照"),
            ('DIFFUSE', "Diffuse (漫反射)", "仅烘焙漫反射颜色（需要 Principled/Diffuse BSDF）"),
            ('NORMAL', "Normal (法线)", "烘焙法线贴图"),
        ],
        default='EMIT',
        description="Cycles 烘焙类型。仅在 Cycles 模式下生效。"
    )

    bake_samples: bpy.props.IntProperty(
        name="烘焙采样数",
        default=32,
        min=1,
        max=4096,
        description="Cycles 烘焙的采样数量。仅在 Cycles 模式下生效。"
    )

    def execute(self, context):
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({'ERROR'}, "请先保存 .blend 文件")
            return {'CANCELLED'}

        tex_dir = os.path.join(os.path.dirname(blend_path), 'Textures')
        os.makedirs(tex_dir, exist_ok=True)

        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_meshes:
            self.report({'WARNING'}, "未选中任何网格对象。")
            return {'CANCELLED'}

        if self.render_mode == 'WORKBENCH':
            return _render_workbench(self, context, selected_meshes, tex_dir,
                                     self.resolution, self.keep_temp)
        else:
            return _render_cycles_bake(self, context, selected_meshes, tex_dir,
                                       self.resolution, self.bake_type,
                                       self.bake_samples)
