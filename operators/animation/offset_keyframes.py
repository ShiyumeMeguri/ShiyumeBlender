import bpy
from math import radians

class SHIYUME_OT_AnimationOffset(bpy.types.Operator):
    """批量偏移除了选中的骨骼关键帧。
    支持位置和旋转的偏移，并提供多种插值模式（线性、平滑等）来控制偏移随时间的变化。
    常用于修正动作捕捉数据的局部偏差。"""
    bl_idname = "shiyume.animation_offset"
    bl_label = "偏移骨骼关键帧"
    bl_options = {'REGISTER', 'UNDO'}

    loc_offset: bpy.props.FloatVectorProperty(name="位置偏移", size=3)
    rot_offset: bpy.props.FloatVectorProperty(name="旋转偏移 (角度)", size=3)
    frame_start: bpy.props.IntProperty(name="开始帧", default=0)
    frame_end: bpy.props.IntProperty(name="结束帧", default=0)
    
    mode_items = [
        ('constant', '恒定', '整个时间段保持相同的偏移量'),
        ('linear_increase', '线性增加', '偏移量随时间线性增加'),
        ('linear_decrease', '线性减少', '偏移量随时间线性减少'),
        ('smoothstep_increase', '平滑增加', '偏移量随时间平滑增加 (S形曲线)'),
        ('smoothstep_decrease', '平滑减少', '偏移量随时间平滑减少 (S形曲线)')
    ]
    offset_mode: bpy.props.EnumProperty(name="插值模式", items=mode_items, default='constant')

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE' and context.mode == 'POSE'

    def smoothstep(self, x):
        return 3 * x ** 2 - 2 * x ** 3

    def execute(self, context):
        obj = context.active_object
        rot_offset_rad = tuple(radians(rot) for rot in self.rot_offset)
        action = obj.animation_data.action if obj.animation_data else None
        
        if not action:
            self.report({'WARNING'}, "No active action found")
            return {'CANCELLED'}

        for pbone in context.selected_pose_bones:
            for fcurve in action.fcurves:
                if fcurve.data_path.startswith(f'pose.bones["{pbone.name}"]'):
                    for kp in fcurve.keyframe_points:
                        if self.frame_start == 0 and self.frame_end == 0:
                            in_range = True
                        else:
                            in_range = self.frame_start <= kp.co.x <= self.frame_end
                        
                        if in_range:
                            t = 0
                            if self.frame_start != self.frame_end:
                                t = (kp.co.x - self.frame_start) / (self.frame_end - self.frame_start)
                            
                            if self.offset_mode == 'linear_increase': factor = t
                            elif self.offset_mode == 'linear_decrease': factor = 1 - t
                            elif self.offset_mode == 'smoothstep_increase': factor = self.smoothstep(t)
                            elif self.offset_mode == 'smoothstep_decrease': factor = 1 - self.smoothstep(t)
                            else: factor = 1

                            if 'location' in fcurve.data_path:
                                kp.co[1] += self.loc_offset[fcurve.array_index] * factor
                            elif 'rotation_euler' in fcurve.data_path and pbone.rotation_mode == 'XYZ':
                                if fcurve.array_index < 3:
                                    kp.co[1] += rot_offset_rad[fcurve.array_index] * factor
                            elif 'rotation_quaternion' in fcurve.data_path and pbone.rotation_mode == 'QUATERNION':
                                if 0 < fcurve.array_index < 4:
                                    kp.co[1] += rot_offset_rad[fcurve.array_index - 1] * factor
        
        return {'FINISHED'}
