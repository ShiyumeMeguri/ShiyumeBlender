import bpy
import os

def ModifyMesh(obj):
    # Check if a duplicate already exists
    duplicate_name = f"{obj.name}_duplicate"
    if bpy.data.objects.get(duplicate_name):
        print(f"Duplicate for {obj.name} already exists.")
        return bpy.data.objects.get(duplicate_name)

    # Duplicate the mesh
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.duplicate()

    # Retrieve the newly duplicated object
    duplicate_obj = bpy.context.active_object
    duplicate_obj.name = duplicate_name
    
    # Move the duplicate 0.1m downwards
    bpy.ops.transform.translate(value=(0, 0, -0.1))
    
    # Enter edit mode to merge vertices
    bpy.context.view_layer.objects.active = duplicate_obj
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Select all vertices and remove doubles
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles()
    
    # Return to object mode
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Add Solidify modifiers
    solidify1 = duplicate_obj.modifiers.new(name="SOLIDIFY_1", type='SOLIDIFY')
    solidify2 = duplicate_obj.modifiers.new(name="SOLIDIFY_2", type='SOLIDIFY')
    solidify2.thickness = 0.002
    solidify2.offset = 1

    return duplicate_obj


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

    uv_sync = bpy.data.collections.get('UVSync')
    if not uv_sync:
        print('UVSync collection does not exist.')
        return

    orig_settings = None
    original_hide_states = {}
    duplicates_to_delete = []

    try:
        orig_settings = SetupCameraAndRenderSettings(resolution)
        original_hide_states = {obj.name: obj.hide_render for obj in bpy.data.objects}

        for obj in bpy.data.objects:
            obj.hide_render = True

        for obj in uv_sync.objects:
            if obj.type == 'MESH':
                duplicate_obj = ModifyMesh(obj)
                
                if duplicate_obj:
                    duplicates_to_delete.append(duplicate_obj)
                    obj.hide_render = False
                    duplicate_obj.hide_render = False

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
        
        if duplicates_to_delete:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in duplicates_to_delete:
                # [修复] 检查对象的名字(string)是否存在，而不是对象本身(object)
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True)
            if bpy.context.selected_objects:
                bpy.ops.object.delete()

        print("Restore complete.")

# Execute
RenderUVProjectionsToTexture()