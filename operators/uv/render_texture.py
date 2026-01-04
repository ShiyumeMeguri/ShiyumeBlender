import bpy
import os

class SHIYUME_OT_UVRenderTexture(bpy.types.Operator):
    """将 'RT' 集合中的所有物体 UV 布局渲染为一张贴图。
    主要用于为手绘贴图制作 UV 参考底图。"""
    bl_idname = "shiyume.uv_render_texture"
    bl_label = "渲染UV布局到贴图"
    bl_options = {'REGISTER'}

    resolution: bpy.props.IntProperty(name="分辨率", default=4096, description="导出贴图的分辨率")

    def execute(self, context):
        rt_col = bpy.data.collections.get('RT')
        if not rt_col:
            rt_col = bpy.data.collections.new('RT')
            context.scene.collection.children.link(rt_col)
            self.report({'INFO'}, "Created 'RT' collection. Move objects there and run again.")
            return {'FINISHED'}

        if not rt_col.objects:
            self.report({'WARNING'}, "'RT' collection is empty")
            return {'CANCELLED'}

        # Get save path
        base_path = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        filepath = os.path.join(base_path, "RT_UV_Layout.png")

        # Select all objects in RT collection
        bpy.ops.object.select_all(action='DESELECT')
        for obj in rt_col.objects:
            if obj.type == 'MESH':
                obj.select_set(True)
        
        # Must be in edit mode for UV export
        context.view_layer.objects.active = [obj for obj in rt_col.objects if obj.type == 'MESH'][0]
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        try:
            bpy.ops.uv.export_layout(filepath=filepath, size=(self.resolution, self.resolution), opacity=1.0)
            self.report({'INFO'}, f"UV Layout exported to: {filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

        return {'FINISHED'}
