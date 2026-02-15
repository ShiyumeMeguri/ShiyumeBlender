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
                # 只有当有形态键时才进行转换，避免不必要的开销
                # 必须选中并设为活动才能转换
                bpy.ops.object.select_all(action='DESELECT')
                new_obj.select_set(True)
                bpy.context.view_layer.objects.active = new_obj
                # 转换为 Mesh 会应用所有修改器和形态键
                bpy.ops.object.convert(target='MESH')
            
            duplicates.append(new_obj)

    if not duplicates:
        return []

    # [优化] 2. 选中所有副本进行批量编辑
    bpy.ops.object.select_all(action='DESELECT')
    for obj in duplicates:
        obj.select_set(True)
    
    # 设置一个活动对象以进行编辑模式切换
    if duplicates: # Check if list is not empty
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


def SetupCameraAndRenderSettings(resolution):
    # 此函数是正确的，无需更改
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
    # 此函数是正确的，无需更改
    if not settings: return
    bpy.context.scene.camera = settings['camera']
    bpy.context.scene.render.engine = settings['engine']
    bpy.context.scene.render.dither_intensity = settings['dither']
    bpy.context.scene.display.shading.light = settings['light']
    bpy.context.scene.display.shading.color_type = settings['color']
    bpy.context.scene.render.resolution_x = settings['res_x']
    bpy.context.scene.render.resolution_y = settings['res_y']
    bpy.context.scene.render.film_transparent = settings['transparent']


class SHIYUME_OT_RenderViewportAsTexture(bpy.types.Operator):
    """(Fix) 渲染选中网格为 UV 贴图"""
    bl_idname = "shiyume.render_viewport_texture"
    bl_label = "渲染视图为贴图"
    bl_options = {'REGISTER', 'UNDO'}

    resolution: bpy.props.IntProperty(
        name="分辨率",
        default=2048,
        min=128,
        max=8192,
        description="渲染纹理的分辨率"
    )

    def execute(self, context):
        resolution = self.resolution
        
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({'ERROR'}, "请先保存 .blend 文件")
            return {'CANCELLED'}
            
        tex_dir = os.path.join(os.path.dirname(blend_path), 'Textures')
        os.makedirs(tex_dir, exist_ok=True)

        # 获取选中的网格对象
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_meshes:
            self.report({'WARNING'}, "未选中任何网格对象。")
            return {'CANCELLED'}

        orig_settings = None
        original_hide_states = {}
        objects_to_delete = []

        try:
            orig_settings = SetupCameraAndRenderSettings(resolution)
            original_hide_states = {obj.name: obj.hide_render for obj in bpy.data.objects}

            # [原始逻辑] 初始时隐藏所有对象以进行渲染
            for obj in bpy.data.objects:
                obj.hide_render = True
                
            # [修正] 直接处理选中的对象，不再合并
            objects_to_delete = PrepareMeshesForRender(selected_meshes, resolution)
            
            if objects_to_delete:
                # [修正] 使新创建的所有对象在渲染中可见
                for obj in objects_to_delete:
                    obj.hide_render = False

                # 使用活动对象名称或者通用名称作为基础文件名
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
                self.report({'INFO'}, f"纹理已保存至 '{output}'")
            else:
                self.report({'WARNING'}, "处理对象失败。")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"发生错误: {e}")
            return {'CANCELLED'}

        finally:
            print("正在恢复原始场景状态...")
            
            if orig_settings:
                RestoreOriginalSettings(orig_settings)

            for obj_name, is_hidden in original_hide_states.items():
                obj = bpy.data.objects.get(obj_name)
                if obj:
                    obj.hide_render = is_hidden
            
            # [修正] 清理所有创建的临时对象
            if objects_to_delete:
                bpy.ops.object.select_all(action='DESELECT')
                for obj in objects_to_delete:
                    if obj.name in bpy.data.objects:
                        obj.select_set(True)
                bpy.ops.object.delete(use_global=False)
            
            # 恢复之前的选择状态
            bpy.ops.object.select_all(action='DESELECT')
            for obj in selected_meshes:
                try:
                    obj.select_set(True)
                except:
                    pass
            if context.active_object in selected_meshes:
                context.view_layer.objects.active = context.active_object

            print("恢复完成。")
            
        return {'FINISHED'}
