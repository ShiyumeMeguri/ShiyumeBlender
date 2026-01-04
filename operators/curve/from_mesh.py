import bpy
import bmesh

class SHIYUME_OT_MeshToCurve(bpy.types.Operator):
    """将网格的顶点链转换为 NURBS 曲线。
    如果网格中有radius和tilt顶点组，会尝试将其应用到曲线控制点上。
    适用于将网格化的头发或线条还原为可编辑的曲线。"""
    bl_idname = "shiyume.mesh_to_curve"
    bl_label = "网格转曲线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}
            
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        
        # Create a new curve
        curve_data = bpy.data.curves.new(name=obj.name + "_Curve", type='CURVE')
        curve_data.dimensions = '3D'
        curve_obj = bpy.data.objects.new(name=obj.name + "_Curve", object_data=curve_data)
        context.collection.objects.link(curve_obj)
        
        # We'll treat the mesh as a single path for now (ordered by vertex index)
        # This is the simplest "Mesh to Curve" implementation.
        spline = curve_data.splines.new('NURBS')
        spline.points.add(len(bm.verts) - 1)
        
        v_radius = obj.vertex_groups.get("radius")
        v_tilt = obj.vertex_groups.get("tilt")
        
        for i, v in enumerate(bm.verts):
            p = spline.points[i]
            p.co = (v.co.x, v.co.y, v.co.z, 1.0) # W=1.0 for NURBS
            
            if v_radius:
                try: p.radius = v_radius.weight(v.index)
                except: p.radius = 1.0
            if v_tilt:
                try: p.tilt = v_tilt.weight(v.index)
                except: p.tilt = 0.0
                
        spline.use_endpoint_u = True
        bm.free()
        
        curve_obj.matrix_world = obj.matrix_world
        self.report({'INFO'}, f"Created curve from mesh: {curve_obj.name}")
        return {'FINISHED'}
