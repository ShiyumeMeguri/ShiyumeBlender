import bpy

# 获取活动对象，确认是骨架
armature = bpy.context.object
if armature is None or armature.type != 'ARMATURE':
    raise Exception("请选择一个骨架对象")

# 确保处于POSE模式
bpy.ops.object.mode_set(mode='POSE')

# 获取选中的骨骼名称列表
selected_bones = [bone.name for bone in armature.pose.bones if bone.bone.select]
if not selected_bones:
    raise Exception("请至少选中一个骨骼")

# 获取动作
action = armature.animation_data.action if armature.animation_data else None
if not action:
    raise Exception("当前骨架没有动画数据")

# 过滤掉位置和缩放通道
fcurves_to_remove = []
for fcurve in action.fcurves:
    # 数据路径示例：pose.bones["Bone"].location / .scale / .rotation_quaternion 等
    data_path = fcurve.data_path

    for bone_name in selected_bones:
        if f'pose.bones["{bone_name}"]' in data_path:
            if ".location" in data_path or ".scale" in data_path:
                fcurves_to_remove.append(fcurve)
                break

# 删除无用的 fcurves
for fcurve in fcurves_to_remove:
    action.fcurves.remove(fcurve)
