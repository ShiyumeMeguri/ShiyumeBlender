import bpy
import bmesh
from mathutils import Vector

class SHIYUME_OT_MeshUVSync(bpy.types.Operator):
    """创建一个 Shape Key，将顶点位置移动到其 UV 坐标的位置。
    这允许你在 3D 视图中以查看网格的方式直接查看和编辑 UV 布局（需要配合形态键使用）。"""
    bl_idname = "shiyume.mesh_uv_sync"
    bl_label = "网格UV同步 (ShapeKey)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}
        
        # 1. Shape Key setup
        if not obj.data.shape_keys:
            obj.shape_key_add(name="Basis")
        
        sk_name = "UV_Layout"
        sk = obj.data.shape_keys.key_blocks.get(sk_name)
        if not sk:
            sk = obj.shape_key_add(name=sk_name)
        
        # 2. Bmesh access
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if not uv_layer:
            self.report({'ERROR'}, "No active UV layer")
            bm.free()
            return {'CANCELLED'}
            
        sk_layer = bm.verts.layers.shape.get(sk_name)
        
        # Map vertex to UV (taking first loop's UV)
        for v in bm.verts:
            if v.link_loops:
                uv = v.link_loops[0][uv_layer].uv
                v[sk_layer] = Vector((uv.x, uv.y, 0.0))
            else:
                v[sk_layer] = v.co
                
        bm.to_mesh(obj.data)
        bm.free()
        
        sk.value = 1.0
        self.report({'INFO'}, "Setup UV Layout Shape Key")
        return {'FINISHED'}
