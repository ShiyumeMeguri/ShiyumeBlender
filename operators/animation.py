import bpy
from math import radians

class SHIYUME_OT_AnimationOffset(bpy.types.Operator):
    """Offset location and rotation keyframes for selected bones"""
    bl_idname = "shiyume.animation_offset"
    bl_label = "Offset Bone Keyframes"
    bl_options = {'REGISTER', 'UNDO'}

    loc_offset: bpy.props.FloatVectorProperty(name="Location Offset", size=3)
    rot_offset: bpy.props.FloatVectorProperty(name="Rotation Offset (Deg)", size=3)
    frame_start: bpy.props.IntProperty(name="Frame Start", default=0)
    frame_end: bpy.props.IntProperty(name="Frame End", default=0)
    
    mode_items = [
        ('constant', 'Constant', ''),
        ('linear_increase', 'Linear Increase', ''),
        ('linear_decrease', 'Linear Decrease', ''),
        ('smoothstep_increase', 'Smoothstep Increase', ''),
        ('smoothstep_decrease', 'Smoothstep Decrease', '')
    ]
    offset_mode: bpy.props.EnumProperty(name="Mode", items=mode_items, default='constant')

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

class SHIYUME_OT_CleanupBakeFrames(bpy.types.Operator):
    """Delete custom property fcurves (often hidden frames from baking)"""
    bl_idname = "shiyume.cleanup_bake_frames"
    bl_label = "Cleanup Baked Hidden Frames"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for action in bpy.data.actions:
            for i in range(len(action.fcurves)-1, -1, -1):
                fcurve = action.fcurves[i]
                if '"]["' in fcurve.data_path:
                    action.fcurves.remove(fcurve)
                    count += 1
        self.report({'INFO'}, f"Removed {count} custom property fcurves")
        return {'FINISHED'}

class SHIYUME_OT_CleanupSelectedBoneLocScale(bpy.types.Operator):
    """Delete location and scale keyframes for selected bones"""
    bl_idname = "shiyume.cleanup_bone_loc_scale"
    bl_label = "Cleanup Bone Loc/Scale Keys"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE' and context.mode == 'POSE'

    def execute(self, context):
        obj = context.object
        action = obj.animation_data.action if obj.animation_data else None
        if not action: return {'CANCELLED'}

        for bone in context.selected_pose_bones:
            to_remove = []
            for fcurve in action.fcurves:
                if fcurve.data_path.startswith(f'pose.bones["{bone.name}"]'):
                    if "location" in fcurve.data_path or "scale" in fcurve.data_path:
                        to_remove.append(fcurve)
            for fcurve in to_remove:
                action.fcurves.remove(fcurve)
        return {'FINISHED'}

class SHIYUME_OT_FixInvalidAnimPaths(bpy.types.Operator):
    """Fix animation paths for bones that no longer exist or were renamed"""
    bl_idname = "shiyume.fix_invalid_anim_paths"
    bl_label = "Fix Invalid Animation Paths"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        armature = context.object
        for action in bpy.data.actions:
            to_remove = []
            for fcurve in action.fcurves:
                if fcurve.data_path.startswith('pose.bones[') and ']' in fcurve.data_path:
                    bone_name = fcurve.data_path.split('[')[1].split(']')[0].strip('"')
                    if bone_name not in armature.pose.bones:
                        to_remove.append(fcurve)
            for fcurve in to_remove:
                action.fcurves.remove(fcurve)
        return {'FINISHED'}

class SHIYUME_OT_CleanBoneCollections(bpy.types.Operator):
    """Cleanup location and scale transformations for specific bone collections"""
    bl_idname = "shiyume.clean_bone_collections"
    bl_label = "Clean Bone Collections Transforms"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        col_names = ["Body", "Skirt", "BackHair", "FrontHair"]
        bones_to_clean = set()
        
        for name in col_names:
            if name in armature.data.collections:
                for bone in armature.data.collections[name].bones:
                    bones_to_clean.add(bone.name)
        
        if not bones_to_clean:
            self.report({'WARNING'}, "No bones found in specified collections")
            return {'CANCELLED'}

        for action in bpy.data.actions:
            to_remove = []
            for fcurve in action.fcurves:
                try:
                    path_to_bone, transform_type = fcurve.data_path.rsplit('.', 1)
                    if not path_to_bone.startswith('pose.bones["'): continue
                    bone_name = path_to_bone.split('"')[1]
                    if bone_name in bones_to_clean and transform_type in ["location", "scale"]:
                        to_remove.append(fcurve)
                except: continue
            for fcurve in to_remove:
                action.fcurves.remove(fcurve)
        return {'FINISHED'}

classes = (
    SHIYUME_OT_AnimationOffset,
    SHIYUME_OT_CleanupBakeFrames,
    SHIYUME_OT_CleanupSelectedBoneLocScale,
    SHIYUME_OT_FixInvalidAnimPaths,
    SHIYUME_OT_CleanBoneCollections,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
