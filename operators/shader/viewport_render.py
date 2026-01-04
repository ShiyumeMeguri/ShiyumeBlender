import bpy
import tempfile

class SHIYUME_OT_RenderViewportAsTexture(bpy.types.Operator):
    """(Hack) 将当前的 3D 视图渲染为一张临时贴图。
    这通常用于快速获取当前视角的画面，作为投射纹理或参考图。"""
    bl_idname = "shiyume.render_viewport_texture"
    bl_label = "渲染视图为贴图"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        orig_res_x = scene.render.resolution_x
        orig_res_y = scene.render.resolution_y
        orig_filepath = scene.render.filepath
        orig_format = scene.render.image_settings.file_format
        
        view3d_spaces = []
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        scene.render.resolution_x = region.width
                        scene.render.resolution_y = region.height
                for space in area.spaces:
                    if space.type == 'VIEW_3D' and space.overlay.show_overlays:
                        view3d_spaces.append(space)
                        space.overlay.show_overlays = False

        temp_path = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
        scene.render.filepath = temp_path
        scene.render.image_settings.file_format = 'PNG'

        bpy.ops.render.opengl(write_still=True, view_context=True)

        for space in view3d_spaces:
            space.overlay.show_overlays = True

        scene.render.resolution_x = orig_res_x
        scene.render.resolution_y = orig_res_y
        scene.render.filepath = orig_filepath
        scene.render.image_settings.file_format = orig_format

        self.report({'INFO'}, f"Rendered to: {temp_path}")
        return {'FINISHED'}
