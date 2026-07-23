import bpy

from ._compat import list_action_fcurves, remove_fcurve, get_active_action


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
        action = get_active_action(obj)
        if not action:
            return {'CANCELLED'}

        for bone in context.selected_pose_bones:
            prefix = f'pose.bones["{bone.name}"]'
            for owner, fcurve in list_action_fcurves(action):
                if fcurve.data_path.startswith(prefix):
                    if "location" in fcurve.data_path or "scale" in fcurve.data_path:
                        remove_fcurve(owner, fcurve)
        return {'FINISHED'}
