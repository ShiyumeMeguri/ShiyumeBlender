import bpy

class SHIYUME_OT_MaterialLinkObject(bpy.types.Operator):
    """将选中物体的材质链接方式全部改为 'Object'。
    这意味着不同物体使用同一材质槽时，可以独立指定不同的材质实例，而不是共享 Mesh 数据的材质。"""
    bl_idname = "shiyume.mat_link_object"
    bl_label = "链接材质到对象"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type != 'MESH': continue
            for slot in obj.material_slots:
                mat = slot.material
                slot.link = 'OBJECT'
                if mat: slot.material = mat
        return {'FINISHED'}
