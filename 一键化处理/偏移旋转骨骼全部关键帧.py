import bpy
from math import radians

# 设定偏移量（以度为单位，后面会转换为弧度）
location_offset = (0, 0, 0)  # 位置偏移
rotation_offset_degrees = (0, 0, 0)  # 旋转偏移
frame_range = [0, 0]  # 动画帧区间
offset_mode = 'constant'  # 可以是 'constant', 'linear_increase', 'linear_decrease', 'smoothstep_increase', 'smoothstep_decrease'

def smoothstep(x):
    # 三次Hermite插值 (smoothstep)
    return 3 * x ** 2 - 2 * x ** 3

def apply_transforms(pose_bone, loc_offset, rot_offset_degrees, frame_range, mode):
    # 转换角度为弧度
    rot_offset_radians = tuple(radians(rot) for rot in rot_offset_degrees)
    
    action = bpy.context.active_object.animation_data.action if bpy.context.active_object.animation_data else None
    if action:
        for fcurve in action.fcurves:
            if fcurve.data_path.startswith('pose.bones["{}"]'.format(pose_bone.name)):
                for keyframe_point in fcurve.keyframe_points:
                    if frame_range[0] <= keyframe_point.co.x <= frame_range[1] or frame_range == [0, 0]:
                        # 检查frame_range的范围
                        frame_start, frame_end = frame_range
                        if frame_start == frame_end:
                            t = 0  # 避免除以零
                        else:
                            t = (keyframe_point.co.x - frame_start) / (frame_end - frame_start)  # normalize time within the range
                        
                        if mode == 'linear_increase':
                            factor = t
                        elif mode == 'linear_decrease':
                            factor = 1 - t
                        elif mode == 'smoothstep_increase':
                            factor = smoothstep(t)
                        elif mode == 'smoothstep_decrease':
                            factor = 1 - smoothstep(t)
                        else:
                            factor = 1  # constant factor

                        offset_amount = tuple(o * factor for o in rot_offset_radians)
                        
                        if 'location' in fcurve.data_path:
                            idx = fcurve.array_index
                            keyframe_point.co[1] += loc_offset[idx] * factor
                        elif 'rotation_euler' in fcurve.data_path and pose_bone.rotation_mode == 'XYZ':
                            idx = fcurve.array_index
                            if idx < len(offset_amount):
                                keyframe_point.co[1] += offset_amount[idx]
                        elif 'rotation_quaternion' in fcurve.data_path and pose_bone.rotation_mode == 'QUATERNION':
                            idx = fcurve.array_index
                            if idx > 0 and idx < len(offset_amount) + 1:
                                keyframe_point.co[1] += offset_amount[idx - 1]

# 获取当前Armature对象
armature_object = bpy.context.active_object

# 确保是在Pose模式
bpy.ops.object.mode_set(mode='POSE')

# 遍历所有选中的骨骼
for pbone in bpy.context.selected_pose_bones:
    apply_transforms(pbone, location_offset, rotation_offset_degrees, frame_range, offset_mode)

print("应用偏移完成。")
