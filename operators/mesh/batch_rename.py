import bpy
import re

class SHIYUME_OT_BatchRename(bpy.types.Operator):
    """按照 Kazaniwa 标准批量重命名物体和材质。
    1. 移除后缀的 .001 等数字。
    2. 为网格添加 'Mesh_' 前缀，为材质添加 'Mat_' 前缀。"""
    bl_idname = "shiyume.batch_rename"
    bl_label = "批量重命名 (规范化)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 1. Rename Objects
        for obj in context.selected_objects:
            # Remove .000 suffixes
            name = re.sub(r'\.\d+$', '', obj.name)
            if obj.type == 'MESH':
                if not name.startswith("Mesh_"):
                    obj.name = "Mesh_" + name
                else:
                    obj.name = name
            elif obj.type == 'ARMATURE':
                if not name.startswith("Arm_"):
                    obj.name = "Arm_" + name
                else:
                    obj.name = name
            
            # 2. Rename Materials
            if obj.type == 'MESH':
                for slot in obj.material_slots:
                    if slot.material:
                        mat = slot.material
                        mat_name = re.sub(r'\.\d+$', '', mat.name)
                        if not mat_name.startswith("Mat_"):
                            mat.name = "Mat_" + mat_name
                        else:
                            mat.name = mat_name
        
        self.report({'INFO'}, "Batch renamed objects and materials")
        return {'FINISHED'}
