import bpy
import os

def modify_mesh(obj):
    # Check if a duplicate already exists
    duplicate_name = f"{obj.name}_duplicate"
    if bpy.data.objects.get(duplicate_name):
        print(f"Duplicate for {obj.name} already exists.")
        return

    # Duplicate the mesh
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj  # Ensure the object is active
    bpy.ops.object.duplicate()
    duplicate_obj = bpy.context.selected_objects[0]
    duplicate_obj.name = duplicate_name
    
    # Move the duplicate 0.1m downwards
    bpy.ops.transform.translate(value=(0, 0, -0.1))
    
    # Enter edit mode to merge vertices
    bpy.context.view_layer.objects.active = duplicate_obj  # Make the duplicate active
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Select all vertices
    bpy.ops.mesh.select_all(action='SELECT')
    
    # Remove doubles (merge vertices)
    bpy.ops.mesh.remove_doubles()
    
    # Return to object mode
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Add Solidify modifiers
    solidify_1 = duplicate_obj.modifiers.new(name="Solidify_1", type='SOLIDIFY')
    
    solidify_2 = duplicate_obj.modifiers.new(name="Solidify_2", type='SOLIDIFY')
    solidify_2.thickness = 0.002
    solidify_2.offset = 1

    # Keep the modifiers without applying them

def setup_camera_and_render_settings(resolution):
    # Record original settings
    original_camera = bpy.context.scene.camera
    original_render_engine = bpy.context.scene.render.engine
    original_dither_intensity = bpy.context.scene.render.dither_intensity
    original_light = bpy.context.scene.display.shading.light
    original_color_type = bpy.context.scene.display.shading.color_type
    original_resolution_x = bpy.context.scene.render.resolution_x
    original_resolution_y = bpy.context.scene.render.resolution_y
    original_film_transparent = bpy.context.scene.render.film_transparent

    # Ensure there's a camera, create if necessary
    camera = bpy.data.objects.get('UV_Camera')
    if not camera:
        camera_data = bpy.data.cameras.new(name='UV_Camera')
        camera = bpy.data.objects.new('UV_Camera', camera_data)
        bpy.context.scene.collection.objects.link(camera)
    
    # Set camera to orthographic projection
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 1

    # Set camera position
    camera.location = (0.5, 0.5, 1)
    camera.rotation_euler = (0, 0, 0)

    # Set as active camera
    bpy.context.scene.camera = camera

    # Set render engine to Workbench and adjust settings
    bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'
    bpy.context.scene.render.dither_intensity = 0
    bpy.context.scene.display.shading.light = 'FLAT'
    bpy.context.scene.display.shading.color_type = 'TEXTURE'

    # Set resolution and transparency
    bpy.context.scene.render.resolution_x = resolution
    bpy.context.scene.render.resolution_y = resolution
    bpy.context.scene.render.film_transparent = True
    
    # Return original settings as a dictionary
    return {
        "camera": original_camera,
        "render_engine": original_render_engine,
        "dither_intensity": original_dither_intensity,
        "light": original_light,
        "color_type": original_color_type,
        "resolution_x": original_resolution_x,
        "resolution_y": original_resolution_y,
        "film_transparent": original_film_transparent
    }

def restore_original_settings(original_settings):
    # Restore original settings
    bpy.context.scene.camera = original_settings["camera"]
    bpy.context.scene.render.engine = original_settings["render_engine"]
    bpy.context.scene.render.dither_intensity = original_settings["dither_intensity"]
    bpy.context.scene.display.shading.light = original_settings["light"]
    bpy.context.scene.display.shading.color_type = original_settings["color_type"]
    bpy.context.scene.render.resolution_x = original_settings["resolution_x"]
    bpy.context.scene.render.resolution_y = original_settings["resolution_y"]
    bpy.context.scene.render.film_transparent = original_settings["film_transparent"]

def render_uv_projections_to_texture(resolution=4096):
    # Create directory for textures
    blend_file_path = bpy.data.filepath
    directory = os.path.join(os.path.dirname(blend_file_path), "Textures")
    if not os.path.exists(directory):
        os.makedirs(directory)

    # Get or create the UVSync collection
    uv_sync_collection = bpy.data.collections.get("UVSync")
    if not uv_sync_collection:
        print("UVSync collection does not exist.")
        return

    # Setup camera and render settings
    original_settings = setup_camera_and_render_settings(resolution)

    # Hide all objects for rendering only UVSync objects
    for obj in bpy.data.objects:
        obj.hide_render = True

    # Modify each object in the UVSync collection
    for obj in uv_sync_collection.objects:
        if obj.type == 'MESH':
            modify_mesh(obj)
            obj.hide_render = False

    # Render to texture
    output_file = os.path.join(directory, "UVSync_Combined.png")
    bpy.context.scene.render.filepath = output_file

    # Execute rendering
    bpy.ops.render.render(write_still=True)

    print(f"Combined texture saved to '{output_file}'")

    # Restore original settings after rendering
    restore_original_settings(original_settings)

# Example usage
render_uv_projections_to_texture()