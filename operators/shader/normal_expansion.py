import bpy
import bmesh

class SHIYUME_OT_NormalExpansion(bpy.types.Operator):
    """法线膨胀覆写（描边预备）。
    复制物体，按法线膨胀顶点，获取其法线方向，然后将这些法线数据“写入”到原物体的自定义法线中。
    这是制作“背面法线外扩描边”的关键步骤，确保描边断裂最少。"""
    bl_idname = "shiyume.normal_expansion"
    bl_label = "法线膨胀覆写"
    bl_options = {'REGISTER', 'UNDO'}

    distance: bpy.props.FloatProperty(name="膨胀距离", default=0.001, precision=4, description="模拟膨胀的距离，用于计算平滑法线")

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        processed_meshes = set()
        for obj in context.selected_objects:
            if obj.type != 'MESH' or obj.data in processed_meshes: continue
            
            # Implementation from script
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            context.collection.objects.link(new_obj)
            
            # Edit new object
            context.view_layer.objects.active = new_obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm_new = bmesh.from_edit_mesh(new_obj.data)
            for v in bm_new.verts:
                v.co += v.normal * self.distance
            bmesh.update_edit_mesh(new_obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')

            # Update original
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm_orig = bmesh.from_edit_mesh(obj.data)
            bm_orig.verts.ensure_lookup_table()

            for i, v_orig in enumerate(bm_orig.verts):
                bpy.ops.mesh.select_all(action='DESELECT')
                bm_orig.verts[i].select = True
                bmesh.update_edit_mesh(obj.data)
                global_new_co = new_obj.matrix_world @ new_obj.data.vertices[i].co
                bpy.ops.mesh.point_normals(target_location=global_new_co)

            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(new_obj)
            processed_meshes.add(obj.data)

        return {'FINISHED'}
