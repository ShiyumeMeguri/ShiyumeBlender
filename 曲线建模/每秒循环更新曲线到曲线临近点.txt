import bpy
import time

def update_scene_handler(scene):
    current_frame = scene.frame_current  # 获取当前动画帧

    # 每10帧执行一次
    if current_frame % 60 == 0:
        print(f"当前帧: {current_frame}")  # 打印当前帧到控制台

        # 保存当前激活对象和选择状态
        active_object = bpy.context.view_layer.objects.active
        selected_objects = bpy.context.selected_objects.copy()

        # 检查是否已经存在名为'CurveSyncMesh'的对象
        target_object = bpy.data.objects.get('CurveSyncMesh')
        if not target_object:
            print("场景中缺少名为'CurveSyncMesh'的对象。")
            return

        # 获取名为'HairCurve'的集合
        curve_collection = bpy.data.collections.get('HairCurve')
        if not curve_collection:
            print("场景中缺少名为'HairCurve'的集合。")
            return

        for obj in curve_collection.objects:
            if obj.type == 'CURVE':
                # 检查是否已经存在名为"Shrinkwrap"的修改器
                mod = next((m for m in obj.modifiers if m.type == 'SHRINKWRAP' and m.name == "Shrinkwrap"), None)
                if not mod:
                    mod = obj.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
                mod.target = target_object
                mod.wrap_method = 'NEAREST_VERTEX'  # 设置为最近点
                mod.use_apply_on_spline = True
                # 激活对象并尝试应用修改器
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.modifier_apply(modifier=mod.name)
                
                # 取消选择所有对象，为下一次循环准备
                bpy.ops.object.select_all(action='DESELECT')

        # 恢复原始激活对象和选择状态
        bpy.context.view_layer.objects.active = active_object
        for obj in selected_objects:
            obj.select_set(True)

# 注册回调函数到场景更新中
bpy.app.handlers.frame_change_pre.append(update_scene_handler)
