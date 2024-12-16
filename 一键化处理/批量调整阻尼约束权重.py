import bpy

# 确保选择的是Armature对象
if bpy.context.object and bpy.context.object.type == 'ARMATURE':
    armature = bpy.context.object
    active_bone = armature.pose.bones.get(armature.data.bones.active.name)
    
    if active_bone:
        # 获取最后一次选中的骨骼的Influence值，假设它有一个'DAMPED_TRACK'约束
        active_influence = None
        for constraint in active_bone.constraints:
            if constraint.type == 'DAMPED_TRACK':
                active_influence = constraint.influence
                break

        if active_influence is not None:
            # 遍历所有选中的骨骼
            for bone in bpy.context.selected_pose_bones:
                # 遍历骨骼上的所有约束
                for constraint in bone.constraints:
                    # 检查约束类型是否为'DAMPED_TRACK'
                    if constraint.type == 'DAMPED_TRACK':
                        # 将约束的Influence设置为最后选中骨骼的Influence值
                        constraint.influence = active_influence
        else:
            print("激活骨骼没有'DAMPED_TRACK'约束")
    else:
        print("未能找到激活的骨骼")
else:
    print("请先选择一个Armature对象")
