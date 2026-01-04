import bpy

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
