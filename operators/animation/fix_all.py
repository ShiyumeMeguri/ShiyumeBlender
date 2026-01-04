import bpy

class SHIYUME_OT_FixAllAnimationIssues(bpy.types.Operator):
    """一键修复常见的动画问题：
    1. 移除烘焙产生的隐藏自定义属性关键帧
    2. 清理选中骨骼的位置/缩放关键帧（保留旋转）
    3. 清理无效的骨骼路径（如骨骼被重命名或删除后遗留的动画数据）
    4. 清理特定骨骼集合（Body, Skirt, BackHair, FrontHair）中的位置/缩放数据"""
    bl_idname = "shiyume.fix_all_anim_issues"
    bl_label = "一键修复动画问题"
    bl_options = {'REGISTER', 'UNDO'}

    fix_bake: bpy.props.BoolProperty(name="清除烘焙残留", default=True, description="清除烘焙产生的隐藏属性关键帧")
    fix_transforms: bpy.props.BoolProperty(name="清除位移/缩放", default=True, description="清除选中骨骼的位移和缩放(仅保留旋转)")
    fix_paths: bpy.props.BoolProperty(name="清除无效路径", default=True, description="清除指向不存在骨骼的动画路径")
    fix_collections: bpy.props.BoolProperty(name="清除指定集合变换", default=False, description="清除Body/Skirt/Hair等特定集合的位移缩放")

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        action = armature.animation_data.action if armature.animation_data else None
        
        # 1. Cleanup Bake Frames (Hidden Properties)
        if self.fix_bake:
            count = 0
            for act in bpy.data.actions:
                for i in range(len(act.fcurves)-1, -1, -1):
                    fcurve = act.fcurves[i]
                    if '"]["' in fcurve.data_path:
                        act.fcurves.remove(fcurve)
                        count += 1
            if count > 0:
                self.report({'INFO'}, f"已清除 {count} 个烘焙残留曲线")

        # 2. Cleanup Selected Bone Loc/Scale
        if self.fix_transforms and action and context.mode == 'POSE':
            for bone in context.selected_pose_bones:
                to_remove = []
                for fcurve in action.fcurves:
                    if fcurve.data_path.startswith(f'pose.bones["{bone.name}"]'):
                        if "location" in fcurve.data_path or "scale" in fcurve.data_path:
                            to_remove.append(fcurve)
                for fcurve in to_remove:
                    action.fcurves.remove(fcurve)
            self.report({'INFO'}, "已清除选中骨骼的位移/缩放关键帧")

        # 3. Fix Invalid Anim Paths
        if self.fix_paths:
            for act in bpy.data.actions:
                to_remove = []
                for fcurve in act.fcurves:
                    if fcurve.data_path.startswith('pose.bones[') and ']' in fcurve.data_path:
                        # Extract bone name carefully
                        try:
                            # format: pose.bones["BoneName"].property
                            bone_name = fcurve.data_path.split('[')[1].split(']')[0].strip('"')
                            if bone_name not in armature.pose.bones:
                                to_remove.append(fcurve)
                        except: pass
                for fcurve in to_remove:
                    act.fcurves.remove(fcurve)
            self.report({'INFO'}, "已清理无效骨骼路径")

        # 4. Clean Bone Collections
        if self.fix_collections:
            col_names = ["Body", "Skirt", "BackHair", "FrontHair"]
            bones_to_clean = set()
            for name in col_names:
                if name in armature.data.collections:
                    for bone in armature.data.collections[name].bones:
                        bones_to_clean.add(bone.name)
            
            if bones_to_clean:
                for act in bpy.data.actions:
                    to_remove = []
                    for fcurve in act.fcurves:
                        try:
                            path_to_bone, transform_type = fcurve.data_path.rsplit('.', 1)
                            if not path_to_bone.startswith('pose.bones["'): continue
                            bone_name = path_to_bone.split('"')[1]
                            if bone_name in bones_to_clean and transform_type in ["location", "scale"]:
                                to_remove.append(fcurve)
                        except: continue
                    for fcurve in to_remove:
                        act.fcurves.remove(fcurve)
                self.report({'INFO'}, "已清除特定集合的变换数据")

        return {'FINISHED'}
