import bpy

# 无法导出动画的原因是 比如骨骼改名了 骨骼删除了 但是动画Action对应的骨骼曲线没有删除 
# 导致无法导出动画也不会有任何错误提示 这么蠢的错误blender这么多年居然不修复
if bpy.context.object and bpy.context.object.type == 'ARMATURE':
    armature = bpy.context.object

    # Iterate through all actions in the Blender file
    for action in bpy.data.actions:
        # Keep track of fcurves to remove
        fcurves_to_remove = []

        # Iterate through fcurves in the action
        for fcurve in action.fcurves:
            # Check if the path is related to pose bones (usually 'pose.bones[BoneName]...')
            if fcurve.data_path.startswith('pose.bones[') and ']' in fcurve.data_path:
                # Extract the bone name from the fcurve's data path
                bone_name = fcurve.data_path.split('[')[1].split(']')[0].strip('"')

                # Check if the bone is still in the armature's pose bones
                if bone_name not in armature.pose.bones:
                    print(bone_name)
                    # Add to the list of fcurves to remove if the bone doesn't exist
                    fcurves_to_remove.append(fcurve)

        # Remove invalid fcurves (those pointing to nonexistent bones)
        for fcurve in fcurves_to_remove:
            action.fcurves.remove(fcurve)

    print("Invalid bone animation paths have been cleaned up.")
else:
    print("No active object or the active object is not an armature.")
