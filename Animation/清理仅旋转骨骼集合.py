import bpy

def clean_bone_transforms_revised():
    """
    清理指定骨骼集合中骨骼在所有动作中的位置和缩放 F-Curve。
    此方法通过直接移除对应的 F-Curve 来实现，比逐个删除关键帧更稳定。
    脚本会排除 'Face' 和 'Vaginal' 这两个集合下的骨骼。
    """
    # 1. 获取活动骨架对象
    armature = bpy.context.active_object
    if not armature or armature.type != 'ARMATURE':
        print("错误：请先在3D视图中选择一个骨架对象。")
        return

    # 2. 定义需要清理其骨骼变换的“骨骼集合”名称列表
    #    请根据您的模型来修改这个列表
    collections_to_clean_names = [
        "Body",
        "Skirt",
        "BackHair",
        "FrontHair"
    ]

    # 3. 从指定的集合中收集所有需要清理的骨骼名称
    #    使用集合(set)可以提高后续的查找效率
    bones_to_clean = set()
    for collection_name in collections_to_clean_names:
        # 检查骨骼集合是否存在于骨架中
        if collection_name in armature.data.collections:
            collection = armature.data.collections[collection_name]
            for bone in collection.bones:
                bones_to_clean.add(bone.name)
        else:
            print(f"警告：骨骼集合 '{collection_name}' 在骨架中未找到，已跳过。")

    if not bones_to_clean:
        print("错误：没有找到任何需要清理的骨骼。请检查 'collections_to_clean_names' 列表中的名称是否正确。")
        return

    print(f"准备清理以下骨骼的位置(location)和缩放(scale)变换: {list(bones_to_clean)}")

    actions_cleaned_count = 0
    fcurves_removed_count = 0

    # 4. 遍历Blender数据中的所有动作(Actions)
    for action in bpy.data.actions:
        # 创建一个临时的列表，用于存放需要被删除的F-Curve
        fcurves_to_remove = []
        
        # 遍历当前动作中的所有F-Curve
        for fcurve in action.fcurves:
            # F-Curve的data_path格式通常是 'pose.bones["骨骼名称"].location'
            # 我们需要从中安全地解析出骨骼名称和变换类型
            try:
                # 使用rsplit从右侧分割，更准确地获取变换类型
                path_to_bone, transform_type = fcurve.data_path.rsplit('.', 1)
                
                # 检查路径是否指向一个骨骼姿态
                if not path_to_bone.startswith('pose.bones["'):
                    continue
                    
                bone_name = path_to_bone.split('"')[1]
            except (IndexError, ValueError):
                # 如果解析失败，说明这不是我们关心的F-Curve，跳过
                continue

            # 5. 检查骨骼是否在清理列表内，并且变换类型是位置或缩放
            if bone_name in bones_to_clean and transform_type in ["location", "scale"]:
                # 如果满足条件，就将这个F-Curve添加到待删除列表
                fcurves_to_remove.append(fcurve)

        # 6. 在检查完一个动作的所有F-Curve后，再统一执行删除操作
        if fcurves_to_remove:
            actions_cleaned_count += 1
            print(f"正在清理动作: '{action.name}'...")
            for fcurve in fcurves_to_remove:
                action.fcurves.remove(fcurve)
                fcurves_removed_count += 1
    
    print("\n--------------------")
    print("脚本执行完毕！")
    print(f"总共在 {actions_cleaned_count} 个动作中执行了清理。")
    print(f"总共移除了 {fcurves_removed_count} 条位置/缩放的函数曲线 (F-Curve)。")


# --- 如何使用 ---
# 1. 在Blender中打开您的 .blend 文件。
# 2. 切换到 "Scripting" 工作区。
# 3. 点击 "New" 创建一个新的文本块。
# 4. 将上面的代码粘贴到文本编辑器中。
# 5. 在3D视图中，确保您想要操作的骨架是活动对象 (被选中状态)。
# 6. 在文本编辑器中点击 "Run Script" 按钮 (或按 Alt+P)。
# 7. 您可以在系统控制台 (Window -> Toggle System Console) 中看到脚本的详细输出信息。

clean_bone_transforms_revised()