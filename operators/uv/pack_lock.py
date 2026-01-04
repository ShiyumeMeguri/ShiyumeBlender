import bpy
import bmesh
import math

class SHIYUME_OT_UVPackLockGroup(bpy.types.Operator):
    """配合 UVPackmaster 使用的工具。
    将选中的多个物体，按顺序偏移 UV (为了避免重叠查看)，并分配递增的 Lock Group ID。
    这样在打包时可以保持物体间的相对位置或分组关系。"""
    bl_idname = "shiyume.uv_pack_lock_group"
    bl_label = "UV打包与锁定组"
    bl_options = {'REGISTER', 'UNDO'}

    offset: bpy.props.FloatProperty(name="UV 偏移量", default=2.0, description="每个物体UV块的偏移距离")

    def execute(self, context):
        current_offset = 0.0
        group_count = 1
        initial_selection = context.selected_objects.copy()
        
        objects = [obj for obj in initial_selection if obj.type == 'MESH']
        for obj in objects:
            context.view_layer.objects.active = obj
            
            dim = obj.dimensions
            length = math.sqrt(dim.x**2 + dim.y**2 + dim.z**2)
            scale = 1/length if length >= 1 else 1
            
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.verify()
            
            for face in bm.faces:
                for loop in face.loops:
                    loop[uv_layer].uv.x += current_offset
                    loop[uv_layer].uv *= scale
            
            bmesh.update_edit_mesh(obj.data)
            
            # Lock Group logic (depends on UVPackmaster 3)
            try:
                context.scene.uvpm3_props.numbered_groups_descriptors.lock_group.group_num = group_count
                bpy.ops.uvpackmaster3.numbered_group_set_iparam(groups_desc_id="lock_group")
            except:
                self.report({'WARNING'}, "UVPackmaster 3 props not found, skipped group locking")
            
            group_count += 1
            current_offset += self.offset
            bpy.ops.object.mode_set(mode='OBJECT')

        return {'FINISHED'}
