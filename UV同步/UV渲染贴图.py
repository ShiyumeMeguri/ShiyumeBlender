import bpy
import os

def ModifyAndJoinMeshes(objects_to_process, resolution):
    """
    This function takes a list of objects, duplicates them,
    joins the duplicates, and then applies modifications.
    This is much more efficient than processing one by one.
    """
    duplicates = []
    
    # [优化] 1. 先复制所有对象，避免在循环中使用 bpy.ops
    for obj in objects_to_process:
        if obj.type == 'MESH':
            # 创建对象和数据的副本
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = f"{obj.name}_duplicate"
            bpy.context.collection.objects.link(new_obj)
            duplicates.append(new_obj)

    if not duplicates:
        return None

    # [优化] 2. 将所有副本合并成一个对象
    bpy.ops.object.select_all(action='DESELECT')
    
    # 选中所有副本，并设置一个为活动对象以进行合并
    for obj in duplicates:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = duplicates[0]
    
    bpy.ops.object.join()
    
    # join() 操作后，活动对象就是合并后的新对象
    combined_obj = bpy.context.active_object
    
    # [优化] 3. 对合并后的单个对象执行一次修改
    # Move the duplicate 0.1m downwards
    combined_obj.location.z -= 0.1
    
    # Enter edit mode to merge vertices
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Select all vertices and remove doubles
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles()
    
    # Return to object mode
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Add Solidify modifiers
    solidify1 = combined_obj.modifiers.new(name="SOLIDIFY_1", type='SOLIDIFY')
    solidify2 = combined_obj.modifiers.new(name="SOLIDIFY_2", type='SOLIDIFY')
    solidify2.thickness = 0.002
    solidify2.offset = 1

    return combined_obj


def SetupCameraAndRenderSettings(resolution):
    # This function is correct and does not need changes
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
        'transparent': original_transparent
    }


def RestoreOriginalSettings(settings):
    # This function is correct and does not need changes
    bpy.context.scene.camera = settings['camera']
    bpy.context.scene.render.engine = settings['engine']
    bpy.context.scene.render.dither_intensity = settings['dither']
    bpy.context.scene.display.shading.light = settings['light']
    bpy.context.scene.display.shading.color_type = settings['color']
    bpy.context.scene.render.resolution_x = settings['res_x']
    bpy.context.scene.render.resolution_y = settings['res_y']
    bpy.context.scene.render.film_transparent = settings['transparent']


def RenderUVProjectionsToTexture(resolution=2048):
    blend_path = bpy.data.filepath
    if not blend_path:
        print("请先保存 .blend 文件")
        return
    tex_dir = os.path.join(os.path.dirname(blend_path), 'Textures')
    os.makedirs(tex_dir, exist_ok=True)

    uv_sync_collection = bpy.data.collections.get('UVSync')
    if not uv_sync_collection:
        print('UVSync collection does not exist.')
        return

    orig_settings = None
    original_hide_states = {}
    object_to_delete = None

    try:
        orig_settings = SetupCameraAndRenderSettings(resolution)
        original_hide_states = {obj.name: obj.hide_render for obj in bpy.data.objects}

        # Hide all objects for rendering initially
        for obj in bpy.data.objects:
            obj.hide_render = True
            
        # Unhide original objects in the target collection
        for obj in uv_sync_collection.objects:
             obj.hide_render = False

        # [REWORKED LOGIC]
        # Process all meshes from the collection at once
        object_to_delete = ModifyAndJoinMeshes(list(uv_sync_collection.objects), resolution)
        
        if object_to_delete:
            # Make the new combined object visible for render
            object_to_delete.hide_render = False

            baseName = 'UVSync_Combined'
            filename = f"{baseName}.png"
            count = 1
            while os.path.exists(os.path.join(tex_dir, filename)):
                filename = f"{baseName}_{count}.png"
                count += 1
            output = os.path.join(tex_dir, filename)

            bpy.context.scene.render.filepath = output
            bpy.ops.render.render(write_still=True)
            print(f"Combined texture saved to '{output}'")
        else:
            print("No suitable mesh objects found in 'UVSync' collection to process.")

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        print("Restoring original scene state...")
        
        if orig_settings:
            RestoreOriginalSettings(orig_settings)

        for obj_name, is_hidden in original_hide_states.items():
            obj = bpy.data.objects.get(obj_name)
            if obj:
                obj.hide_render = is_hidden
        
        # [CLEANUP] Delete the single combined object we created
        if object_to_delete:
            # Your original fix is good practice, we'll keep a similar check
            if object_to_delete.name in bpy.data.objects:
                bpy.ops.object.select_all(action='DESELECT')
                object_to_delete.select_set(True)
                bpy.ops.object.delete(use_global=False)

        print("Restore complete.")

# Execute
RenderUVProjectionsToTexture()