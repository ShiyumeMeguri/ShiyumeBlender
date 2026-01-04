import bpy

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
