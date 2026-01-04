import bpy

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
