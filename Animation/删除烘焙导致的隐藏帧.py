import bpy

# 获取当前时间线的结束帧
timeline_end_frame = bpy.context.scene.frame_end

# 获取场景中所有动作
actions = bpy.data.actions

# 删除动作中超出时间线结束帧的关键帧
for action in actions:
    print(f"Checking action: {action.name}")
    
    for fcurve in action.fcurves:
        # 倒序遍历关键帧，以避免删除时影响索引
        for i in range(len(fcurve.keyframe_points)-1, -1, -1):
            keyframe = fcurve.keyframe_points[i]
            if keyframe.co.x > timeline_end_frame:
                print(f"  Removing keyframe at frame {keyframe.co.x} on fcurve {fcurve.data_path}")
                fcurve.keyframe_points.remove(keyframe)

print(f"Finished cleaning up keyframes beyond frame {timeline_end_frame}.")
