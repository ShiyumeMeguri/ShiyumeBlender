import bpy
import tempfile

def render_viewport_as_texture():
    # Save the original render settings
    orig_res_x = bpy.context.scene.render.resolution_x
    orig_res_y = bpy.context.scene.render.resolution_y
    orig_filepath = bpy.context.scene.render.filepath
    orig_format = bpy.context.scene.render.image_settings.file_format
    
    # Prepare a list for 3D view spaces with overlays enabled
    view3d_spaces = []

    # Iterate through the screen areas to find the 3D view
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            # Temporarily change the render resolution to the 3D view size
            for region in area.regions:
                if region.type == 'WINDOW':
                    bpy.context.scene.render.resolution_x = region.width
                    bpy.context.scene.render.resolution_y = region.height
            
            # Disable overlays and collect 3D view spaces
            for space in area.spaces:
                if space.type == 'VIEW_3D' and space.overlay.show_overlays:
                    view3d_spaces.append(space)
                    space.overlay.show_overlays = False

    # Set up temporary render settings
    temp_image_path = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
    bpy.context.scene.render.filepath = temp_image_path
    bpy.context.scene.render.image_settings.file_format = 'PNG'

    # Render the viewport
    bpy.ops.render.opengl(write_still=True, view_context=True)

    # Restore the overlays in 3D view spaces
    for space in view3d_spaces:
        space.overlay.show_overlays = True

    # Restore the original settings
    bpy.context.scene.render.resolution_x = orig_res_x
    bpy.context.scene.render.resolution_y = orig_res_y
    bpy.context.scene.render.filepath = orig_filepath
    bpy.context.scene.render.image_settings.file_format = orig_format

    return temp_image_path

# Call the function and print the path of the rendered image
rendered_image_path = render_viewport_as_texture()
print(f"Rendered image saved at: {rendered_image_path}")
