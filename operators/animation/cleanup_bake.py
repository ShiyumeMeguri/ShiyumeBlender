import bpy

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
