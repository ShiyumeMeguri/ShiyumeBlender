import bpy
import os


def _modify_and_join_meshes(objects_to_process, resolution):
    duplicates = []

    for obj in objects_to_process:
        if obj.type == 'MESH':
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = f"{obj.name}_duplicate"
            bpy.context.collection.objects.link(new_obj)
            duplicates.append(new_obj)

    if not duplicates:
        return None

    bpy.ops.object.select_all(action='DESELECT')

    for obj in duplicates:
        obj.select_set(True)
    if duplicates:
        bpy.context.view_layer.objects.active = duplicates[0]

    bpy.ops.object.join()

    combined_obj = bpy.context.active_object

    combined_obj.location.z -= 0.1

    bpy.ops.object.mode_set(mode='EDIT')

    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles()

    bpy.ops.object.mode_set(mode='OBJECT')

    solidify1 = combined_obj.modifiers.new(name="SOLIDIFY_1", type='SOLIDIFY')
    solidify2 = combined_obj.modifiers.new(name="SOLIDIFY_2", type='SOLIDIFY')
    solidify2.thickness = 0.002
    solidify2.offset = 1

    return combined_obj


def _setup_camera_and_render_settings(resolution):
    original_camera = bpy.context.scene.camera
    original_engine = bpy.context.scene.render.engine
    original_dither = bpy.context.scene.render.dither_intensity
    original_light = bpy.context.scene.display.shading.light
    original_color = bpy.context.scene.display.shading.color_type
    original_res_x = bpy.context.scene.render.resolution_x
    original_res_y = bpy.context.scene.render.resolution_y
    original_transparent = bpy.context.scene.render.film_transparent

    camera = bpy.data.objects.get('UV_Camera')
    if not camera:
        camera_data = bpy.data.cameras.new(name='UV_Camera')
        camera = bpy.data.objects.new('UV_Camera', camera_data)
        bpy.context.scene.collection.objects.link(camera)

    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 1
    camera.location = (0.5, 0.5, 1)
    camera.rotation_euler = (0, 0, 0)
    bpy.context.scene.camera = camera

    bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'
    bpy.context.scene.render.dither_intensity = 0
    bpy.context.scene.display.shading.light = 'FLAT'
    bpy.context.scene.display.shading.color_type = 'TEXTURE'

    bpy.context.scene.render.resolution_x = resolution
    bpy.context.scene.render.resolution_y = resolution
    bpy.context.scene.render.film_transparent = True

    return {
        'camera': original_camera,
        'engine': original_engine,
        'dither': original_dither,
        'light': original_light,
        'color': original_color,
        'res_x': original_res_x,
        'res_y': original_res_y,
        'transparent': original_transparent,
    }


def _restore_original_settings(settings):
    if not settings:
        return
    bpy.context.scene.camera = settings['camera']
    bpy.context.scene.render.engine = settings['engine']
    bpy.context.scene.render.dither_intensity = settings['dither']
    bpy.context.scene.display.shading.light = settings['light']
    bpy.context.scene.display.shading.color_type = settings['color']
    bpy.context.scene.render.resolution_x = settings['res_x']
    bpy.context.scene.render.resolution_y = settings['res_y']
    bpy.context.scene.render.film_transparent = settings['transparent']


class SHIYUME_OT_UVRenderRT(bpy.types.Operator):
    """渲染 'RT' 集合中所有网格的 UV 投影到一张贴图。
    流程：复制 RT 集合中的所有对象 -> 合并 -> 去重顶点 -> 加 Solidify -> Workbench 正交渲染。
    输出到 .blend 旁的 Textures/ 文件夹。第一次运行若 'RT' 集合不存在会自动创建并提示用户。"""
    bl_idname = "shiyume.uv_render_rt"
    bl_label = "UV渲染贴图 (RT集合)"
    bl_options = {'REGISTER'}

    resolution: bpy.props.IntProperty(name="分辨率", default=4096, min=128, max=8192)

    def execute(self, context):
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({'ERROR'}, "请先保存 .blend 文件")
            return {'CANCELLED'}
        tex_dir = os.path.join(os.path.dirname(blend_path), 'Textures')
        os.makedirs(tex_dir, exist_ok=True)

        collection_name = 'RT'
        rt_collection = bpy.data.collections.get(collection_name)

        if not rt_collection:
            rt_collection = bpy.data.collections.new(collection_name)
            context.scene.collection.children.link(rt_collection)
            self.report({'WARNING'}, f"已创建新集合 '{collection_name}'。请把网格放入后再次运行。")
            return {'CANCELLED'}

        if not rt_collection.objects:
            self.report({'WARNING'}, f"集合 '{collection_name}' 为空。")
            return {'CANCELLED'}

        orig_settings = None
        original_hide_states = {}
        object_to_delete = None

        try:
            orig_settings = _setup_camera_and_render_settings(self.resolution)
            original_hide_states = {obj.name: obj.hide_render for obj in bpy.data.objects}

            for obj in bpy.data.objects:
                obj.hide_render = True

            for obj in rt_collection.objects:
                obj.hide_render = False

            object_to_delete = _modify_and_join_meshes(list(rt_collection.objects), self.resolution)

            if object_to_delete:
                object_to_delete.hide_render = False

                baseName = f'{collection_name}_Combined'
                filename = f"{baseName}.png"
                count = 1
                while os.path.exists(os.path.join(tex_dir, filename)):
                    filename = f"{baseName}_{count}.png"
                    count += 1
                output = os.path.join(tex_dir, filename)

                bpy.context.scene.render.filepath = output
                bpy.ops.render.render(write_still=True)
                self.report({'INFO'}, f"合并后的纹理已保存至 '{output}'")
            else:
                self.report({'WARNING'}, f"在 '{collection_name}' 集合中没有合适的网格对象。")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"发生错误: {e}")
            return {'CANCELLED'}

        finally:
            if orig_settings:
                _restore_original_settings(orig_settings)

            for obj_name, is_hidden in original_hide_states.items():
                obj = bpy.data.objects.get(obj_name)
                if obj:
                    obj.hide_render = is_hidden

            if object_to_delete:
                if object_to_delete.name in bpy.data.objects:
                    bpy.ops.object.select_all(action='DESELECT')
                    object_to_delete.select_set(True)
                    bpy.ops.object.delete(use_global=False)

        return {'FINISHED'}
