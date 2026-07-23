import bpy
import tempfile


class SHIYUME_OT_ViewportSimpleRender(bpy.types.Operator):
    """简单地把当前 3D 视口渲染为一张贴图保存到临时文件。
    会临时关闭叠加层、按视口大小设置渲染分辨率，渲染完成后还原所有设置。
    渲染结果存到系统 tmp 文件夹，控制台打印路径。"""
    bl_idname = "shiyume.viewport_simple_render"
    bl_label = "渲染视口为贴图(简单)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        orig_res_x = context.scene.render.resolution_x
        orig_res_y = context.scene.render.resolution_y
        orig_filepath = context.scene.render.filepath
        orig_format = context.scene.render.image_settings.file_format

        view3d_spaces = []

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        context.scene.render.resolution_x = region.width
                        context.scene.render.resolution_y = region.height

                for space in area.spaces:
                    if space.type == 'VIEW_3D' and space.overlay.show_overlays:
                        view3d_spaces.append(space)
                        space.overlay.show_overlays = False

        temp_image_path = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
        context.scene.render.filepath = temp_image_path
        context.scene.render.image_settings.file_format = 'PNG'

        try:
            bpy.ops.render.opengl(write_still=True, view_context=True)
        except RuntimeError as e:
            # Restore state before bailing out
            for space in view3d_spaces:
                space.overlay.show_overlays = True
            context.scene.render.resolution_x = orig_res_x
            context.scene.render.resolution_y = orig_res_y
            context.scene.render.filepath = orig_filepath
            context.scene.render.image_settings.file_format = orig_format
            self.report({'ERROR'}, f"渲染失败 (需要 3D 视口与 OpenGL 上下文): {e}")
            return {'CANCELLED'}

        for space in view3d_spaces:
            space.overlay.show_overlays = True

        context.scene.render.resolution_x = orig_res_x
        context.scene.render.resolution_y = orig_res_y
        context.scene.render.filepath = orig_filepath
        context.scene.render.image_settings.file_format = orig_format

        print(f"Rendered image saved at: {temp_image_path}")
        self.report({'INFO'}, f"渲染已保存: {temp_image_path}")
        return {'FINISHED'}
