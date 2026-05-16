import bpy

from ._compat import list_action_fcurves, remove_fcurve


class SHIYUME_OT_CleanupBakeFrames(bpy.types.Operator):
    """Delete custom property fcurves (often hidden frames from baking)"""
    bl_idname = "shiyume.cleanup_bake_frames"
    bl_label = "Cleanup Baked Hidden Frames"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for action in bpy.data.actions:
            for owner, fcurve in list_action_fcurves(action):
                if '"]["' in fcurve.data_path:
                    remove_fcurve(owner, fcurve)
                    count += 1
        self.report({'INFO'}, f"Removed {count} custom property fcurves")
        return {'FINISHED'}
