import bpy
import os

def ModifyAndJoinMeshes(objects_to_process, resolution):
    """
    此函数与您提供的版本完全相同，以确保渲染逻辑等价。
    它获取对象列表，复制它们，合并副本，然后应用修改。
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
    # 确保至少有一个副本以避免错误
    if duplicates:
        bpy.context.view_layer.objects.active = duplicates[0]
    
    bpy.ops.object.join()
    
    # join() 操作后，活动对象就是合并后的新对象
    combined_obj = bpy.context.active_object
    
    # [优化] 3. 对合并后的单个对象执行一次修改
    # 将副本向下移动0.1m
    combined_obj.location.z -= 0.1
    
    # 进入编辑模式合并顶点
    bpy.ops.object.mode_set(mode='EDIT')
    
    # 全选顶点并移除重复点
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles()
    
    # 返回物体模式
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # 添加实体化修改器
    solidify1 = combined_obj.modifiers.new(name="SOLIDIFY_1", type='SOLIDIFY')
    solidify2 = combined_obj.modifiers.new(name="SOLIDIFY_2", type='SOLIDIFY')
    solidify2.thickness = 0.002
    solidify2.offset = 1

    return combined_obj


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


def RenderUVProjectionsToTexture(resolution=4096):
    blend_path = bpy.data.filepath
    if not blend_path:
        print("请先保存 .blend 文件")
        return
    tex_dir = os.path.join(os.path.dirname(blend_path), 'Textures')
    os.makedirs(tex_dir, exist_ok=True)

    # --- [逻辑修改] ---
    # 1. 定义目标集合名称为 'RT'
    collection_name = 'RT'
    rt_collection = bpy.data.collections.get(collection_name)
    
    # 2. 如果集合不存在，则创建它并提示用户
    if not rt_collection:
        rt_collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(rt_collection)
        print(f"已创建新的集合 '{collection_name}'。请将需要渲染的网格对象放入此集合中，然后重新运行脚本。")
        return 

    # 3. 如果集合为空，则提示用户
    if not rt_collection.objects:
        print(f"集合 '{collection_name}' 为空。请将需要渲染的网格对象放入此集合中。")
        return
    # --- [修改结束] ---

    orig_settings = None
    original_hide_states = {}
    object_to_delete = None

    try:
        orig_settings = SetupCameraAndRenderSettings(resolution)
        original_hide_states = {obj.name: obj.hide_render for obj in bpy.data.objects}

        # [原始逻辑] 初始时隐藏所有对象以进行渲染
        for obj in bpy.data.objects:
            obj.hide_render = True
            
        # [原始逻辑] 仅取消隐藏目标集合中的原始对象
        for obj in rt_collection.objects:
             obj.hide_render = False

        # [原始逻辑] 一次性处理集合中的所有网格
        object_to_delete = ModifyAndJoinMeshes(list(rt_collection.objects), resolution)
        
        if object_to_delete:
            # [原始逻辑] 使新合并的对象在渲染中可见
            object_to_delete.hide_render = False

            # 使用新的集合名称作为基础文件名
            baseName = f'{collection_name}_Combined'
            filename = f"{baseName}.png"
            count = 1
            while os.path.exists(os.path.join(tex_dir, filename)):
                filename = f"{baseName}_{count}.png"
                count += 1
            output = os.path.join(tex_dir, filename)

            bpy.context.scene.render.filepath = output
            bpy.ops.render.render(write_still=True)
            print(f"合并后的纹理已保存至 '{output}'")
        else:
            print(f"在 '{collection_name}' 集合中没有找到合适的网格对象进行处理。")

    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("正在恢复原始场景状态...")
        
        if orig_settings:
            RestoreOriginalSettings(orig_settings)

        for obj_name, is_hidden in original_hide_states.items():
            obj = bpy.data.objects.get(obj_name)
            if obj:
                obj.hide_render = is_hidden
        
        # [原始逻辑] 清理我们创建的单个合并对象
        if object_to_delete:
            if object_to_delete.name in bpy.data.objects:
                bpy.ops.object.select_all(action='DESELECT')
                object_to_delete.select_set(True)
                bpy.ops.object.delete(use_global=False)

        print("恢复完成。")

# 执行脚本
RenderUVProjectionsToTexture()