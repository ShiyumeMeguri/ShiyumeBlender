import bpy
from math import radians
from mathutils import Quaternion, Euler

# ============ 你可以在这里修改这些参数  ============
location_offset = (0, 0, 0)  # 位置偏移
rotation_offset_degrees = (0, -90, 0)  # 旋转偏移(度)
frame_range = [0, 0]       # 若 [0, 0] 表示全范围，否则只处理范围内的帧
offset_mode = 'constant'   # 'constant', 'linear_increase', 'linear_decrease',
                           # 'smoothstep_increase', 'smoothstep_decrease'
# ==================================================

def smoothstep(x):
    # 三次Hermite插值 (smoothstep)
    return 3 * x**2 - 2 * x**3

def get_factor(frame, frame_start, frame_end, mode):
    """
    根据 offset_mode 计算在给定帧时的插值因子 factor。
    """
    # 若 frame_range[0] == frame_range[1]，避免除零
    if frame_start == frame_end:
        return 1 if mode != 'constant' else 1

    t = (frame - frame_start) / (frame_end - frame_start)
    
    if mode == 'linear_increase':
        factor = t
    elif mode == 'linear_decrease':
        factor = 1 - t
    elif mode == 'smoothstep_increase':
        factor = smoothstep(t)
    elif mode == 'smoothstep_decrease':
        factor = 1 - smoothstep(t)
    else:
        factor = 1  # constant
    return factor

def apply_transforms(pose_bone, loc_offset, rot_offset_deg, frame_range, mode):
    """
    对单个骨骼执行位置偏移 & 旋转偏移。
    若骨骼是 Euler 模式，则直接在旋转欧拉角上加减。
    若骨骼是四元数模式，则需要做四元数的乘法（或者 slerp）。
    """
    action = bpy.context.active_object.animation_data.action if bpy.context.active_object.animation_data else None
    if not action:
        return

    frame_start, frame_end = frame_range
    # 如果用户给出的 frame_range 是 [0,0]，我们就理解为全范围，所以先找一下 Action 的整体范围
    if frame_start == 0 and frame_end == 0:
        all_frames = set()
        for fcurve in action.fcurves:
            if fcurve.data_path.startswith('pose.bones["{}"]'.format(pose_bone.name)):
                for kp in fcurve.keyframe_points:
                    all_frames.add(kp.co.x)
        if all_frames:
            frame_start = min(all_frames)
            frame_end   = max(all_frames)

    # 首先构造一个欧拉转四元的偏移，用于骨骼若是四元数模式时做乘法
    # 即 offset_quat = Euler( rot_offset_deg, 'XYZ' ).to_quaternion()
    # 但注意骨骼有 rotation_mode，若是 'XYZ' 以外，需要你自己根据骨骼的具体模式来转换。
    # 这里为了示例，假设都是 'XYZ' 。
    offset_euler = Euler((radians(rot_offset_deg[0]),
                          radians(rot_offset_deg[1]),
                          radians(rot_offset_deg[2])), 'XYZ')
    offset_quat  = offset_euler.to_quaternion()

    # ========== 先把所有与该骨骼相关的 fcurves 按类型收集起来  ==========
    # location: x, y, z 三条曲线
    loc_fcurves = [None, None, None]
    # euler: x, y, z 三条曲线
    euler_fcurves = [None, None, None]
    # quaternion: w, x, y, z 四条曲线
    quat_fcurves = [None, None, None, None]

    for fcurve in action.fcurves:
        if not fcurve.data_path.startswith('pose.bones["{}"]'.format(pose_bone.name)):
            continue

        if 'location' in fcurve.data_path:
            loc_fcurves[fcurve.array_index] = fcurve
        elif 'rotation_euler' in fcurve.data_path and pose_bone.rotation_mode == 'XYZ':
            euler_fcurves[fcurve.array_index] = fcurve
        elif 'rotation_quaternion' in fcurve.data_path and pose_bone.rotation_mode == 'QUATERNION':
            quat_fcurves[fcurve.array_index] = fcurve

    # ========== 再把关键帧按帧号分组，并读取/修改后再写回  ==========
    # 我们要保证同一帧下的 x, y, z（以及 w, x, y, z）一起处理

    # 1) 收集所有相关 fcurves 的所有帧
    frames_set = set()
    for fc in (loc_fcurves + euler_fcurves + quat_fcurves):
        if fc:
            for kp in fc.keyframe_points:
                frames_set.add(kp.co.x)
    all_frames = sorted(frames_set)

    for frame in all_frames:
        # 如果不在范围内就跳过
        if not (frame_start <= frame <= frame_end):
            continue

        factor = get_factor(frame, frame_start, frame_end, mode)

        # ------ 处理 location ------
        loc_original = [0.0, 0.0, 0.0]
        for i in range(3):
            fc = loc_fcurves[i]
            if fc:
                loc_original[i] = fc.evaluate(frame)
        
        # 加上偏移 (offset * factor)
        loc_new = [loc_original[i] + loc_offset[i] * factor for i in range(3)]
        
        # 写回关键帧
        for i in range(3):
            fc = loc_fcurves[i]
            if fc:
                # 找到此 frame 对应的 keyframe_point 并改值
                for kp in fc.keyframe_points:
                    if kp.co.x == frame:
                        kp.co[1] = loc_new[i]
                        break

        # ------ 处理 rotation_euler (如果骨骼是 Euler) ------
        if pose_bone.rotation_mode == 'XYZ' and any(euler_fcurves):
            euler_original = [0.0, 0.0, 0.0]
            for i in range(3):
                fc = euler_fcurves[i]
                if fc:
                    euler_original[i] = fc.evaluate(frame)
            
            # 直接在欧拉角上加 (offset * factor)，
            # 注意原先是度，现在 evaluate 到的也是弧度制，所以要把 rot_offset_deg 转弧度后再乘以 factor
            rot_offset_rad = [radians(deg) for deg in rot_offset_deg]
            euler_new = [euler_original[i] + rot_offset_rad[i] * factor for i in range(3)]

            # 写回关键帧
            for i in range(3):
                fc = euler_fcurves[i]
                if fc:
                    for kp in fc.keyframe_points:
                        if kp.co.x == frame:
                            kp.co[1] = euler_new[i]
                            break

        # ------ 处理 rotation_quaternion (如果骨骼是 QUATERNION) ------
        elif pose_bone.rotation_mode == 'QUATERNION' and any(quat_fcurves):
            # 把四元数的 w, x, y, z evaluate 出来
            wxyz_original = [1.0, 0.0, 0.0, 0.0]
            for i in range(4):
                fc = quat_fcurves[i]
                if fc:
                    wxyz_original[i] = fc.evaluate(frame)

            old_quat = Quaternion((wxyz_original[0],
                                   wxyz_original[1],
                                   wxyz_original[2],
                                   wxyz_original[3]))

            # 如果只是想做简单的「加一点旋转」效果，我们应该做 quaternion 乘法
            # 但若想实现 linear_increase/smoothstep_increase 的渐变，
            # 则可以对 offset_quat 做插值: new_quat = old_quat.slerp(old_quat * offset_quat, factor)
            
            full_offset = old_quat @ offset_quat  # old_quat * offset_quat
            if factor < 1.0:
                # 球面插值，让 offset 可以慢慢「叠加」进来
                new_quat = old_quat.slerp(full_offset, factor)
            else:
                new_quat = full_offset

            wxyz_new = (new_quat.w, new_quat.x, new_quat.y, new_quat.z)

            # 写回关键帧
            for i in range(4):
                fc = quat_fcurves[i]
                if fc:
                    for kp in fc.keyframe_points:
                        if kp.co.x == frame:
                            kp.co[1] = wxyz_new[i]
                            break

def main_apply_offset():
    armature_object = bpy.context.active_object
    if not armature_object or armature_object.type != 'ARMATURE':
        print("请先选中一个 Armature 对象，并进入 Pose 模式。")
        return

    # 确保是在Pose模式
    bpy.ops.object.mode_set(mode='POSE')

    for pbone in bpy.context.selected_pose_bones:
        apply_transforms(pbone, location_offset, rotation_offset_degrees, frame_range, offset_mode)

    print("应用偏移完成。")

# 运行脚本的入口
main_apply_offset()
