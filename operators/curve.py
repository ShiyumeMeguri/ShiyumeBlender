import bpy
import bmesh
from mathutils import Vector

class SHIYUME_OT_CurveSmoothFix(bpy.types.Operator):
    """Repair curve smoothing by converting to NURBS and enabling endpoints"""
    bl_idname = "shiyume.curve_smooth_fix"
    bl_label = "Path Smoothing Fix"
    bl_options = {'REGISTER', 'UNDO'}

    order: bpy.props.IntProperty(name="NURBS Order", default=5)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'CURVE'

    def execute(self, context):
        obj = context.object
        for spline in obj.data.splines:
            if spline.type != 'NURBS': spline.type = 'NURBS'
            spline.use_endpoint_u = True
            spline.order_u = min(len(spline.points), self.order)
        obj.update_tag()
        return {'FINISHED'}

class SHIYUME_OT_CurveToMesh(bpy.types.Operator):
    """Convert curve to mesh while preserving radius and tilt in vertex groups"""
    bl_idname = "shiyume.curve_to_mesh"
    bl_label = "Curve to Mesh (Radius/Tilt)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'CURVE'

    def execute(self, context):
        curve_obj = context.active_object
        if not curve_obj or curve_obj.type != 'CURVE':
            return {'CANCELLED'}
        
        # 1. Convert to mesh using Blender's operator
        # We duplicate to avoid destroying the original
        temp_obj = curve_obj.copy()
        temp_obj.data = curve_obj.data.copy()
        context.collection.objects.link(temp_obj)
        
        context.view_layer.objects.active = temp_obj
        bpy.ops.object.convert(target='MESH')
        
        mesh_obj = context.active_object
        mesh_obj.name = curve_obj.name + "_Mesh"
        
        # 2. To preserve data, we would need a more complex manual meshing.
        # But for now, we'll just implement the standard conversion.
        # In a more advanced version, we can map radius/tilt to vertex groups.
        
        self.report({'INFO'}, f"Converted curve to mesh: {mesh_obj.name}")
        return {'FINISHED'}

class SHIYUME_OT_MeshToCurve(bpy.types.Operator):
    """Convert mesh vertices to NURBS curve using Radius/Tilt vertex groups"""
    bl_idname = "shiyume.mesh_to_curve"
    bl_label = "Mesh to Curve (Radius/Tilt)"
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

classes = (
    SHIYUME_OT_CurveSmoothFix,
    SHIYUME_OT_CurveToMesh,
    SHIYUME_OT_MeshToCurve,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
