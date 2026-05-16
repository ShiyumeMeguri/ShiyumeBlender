import bpy
import math


class SHIYUME_OT_MeshToCurve(bpy.types.Operator):
    """将网格的顶点链转换为 NURBS 曲线（保留 Radius/Tilt）。
    若网格上存在 'Radius' 和 'Tilt' 顶点组，会写入到曲线控制点。
    Tilt 从 [0, 1] 反归一化回 [-1, 1]。适合把网格化的头发或线条还原为可编辑曲线。"""
    bl_idname = "shiyume.mesh_to_curve"
    bl_label = "网格转曲线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.object

        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}

        if "Radius" in obj.vertex_groups.keys() and "Tilt" in obj.vertex_groups.keys():
            radius_vg = obj.vertex_groups["Radius"]
            tilt_vg = obj.vertex_groups["Tilt"]
        else:
            radius_vg = None
            tilt_vg = None
            self.report({'WARNING'}, "Mesh对象缺少必要的顶点组 (Radius/Tilt)")

        curveData = bpy.data.curves.new('VertexCurve', 'CURVE')
        curveData.dimensions = '3D'

        curveObj = bpy.data.objects.new('VertexCurveObj', curveData)
        context.collection.objects.link(curveObj)

        polyline = curveData.splines.new('NURBS')
        polyline.points.add(len(obj.data.vertices) - 1)
        polyline.order_u = 5
        polyline.use_endpoint_u = True

        for i, vertex in enumerate(obj.data.vertices):
            x, y, z = obj.matrix_world @ vertex.co
            polyline.points[i].co = (x, y, z, 1)

            if radius_vg and tilt_vg:
                try:
                    radius = radius_vg.weight(vertex.index)
                except Exception:
                    radius = 1.0
                try:
                    tilt = (tilt_vg.weight(vertex.index) * 2) - 1
                except Exception:
                    tilt = 0.0
                polyline.points[i].radius = radius
                polyline.points[i].tilt = tilt

        return {'FINISHED'}
