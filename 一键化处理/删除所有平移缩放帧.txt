import bpy

# 确保在姿势模式下运行脚本
bpy.ops.object.mode_set(mode='POSE')

# 获取当前活动的动画数据
action = bpy.context.object.animation_data.action if bpy.context.object.animation_data else None

if action:
    # 遍历所有选中的骨骼
    for bone in bpy.context.selected_pose_bones:
        # 遍历所有的FCurve
        fcurves = action.fcurves
        to_remove = []
        for fcurve in fcurves:
            # 检查FCurve是否属于当前骨骼
            if fcurve.data_path.startswith("pose.bones[\"{}\"]".format(bone.name)):
                # 只删除位置和缩放关键帧
                if "location" in fcurve.data_path or "scale" in fcurve.data_path:
                    to_remove.append(fcurve)
                    
        # 移除选定的FCurve
        for fcurve in to_remove:
            action.fcurves.remove(fcurve)

