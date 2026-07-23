import bpy
import bmesh


class SHIYUME_OT_CurveToMesh(bpy.types.Operator):
    """将曲线对象转换为网格（手动 bmesh 实现，保留 Radius/Tilt 到顶点组）。
    每条样条会创建一连串顶点+边；闭合样条会闭合首尾。
    将曲线点的 radius 写入 'Radius' 顶点组，tilt 归一化(0..1)写入 'Tilt' 顶点组。"""
    bl_idname = "shiyume.curve_to_mesh"
    bl_label = "曲线转网格 (保留 R/T)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'CURVE'

    def execute(self, context):
        curve_obj = context.active_object
        if not curve_obj or curve_obj.type != 'CURVE':
            return {'CANCELLED'}

        curve_data = curve_obj.data

        bm = bmesh.new()

        verts = []

        for spline in curve_data.splines:
            verts.clear()
            if spline.type == 'POLY' or spline.type == 'NURBS':
                for point in spline.points:
                    vert = bm.verts.new(point.co.xyz)
                    verts.append(vert)
            elif spline.type == 'BEZIER':
                for point in spline.bezier_points:
                    vert = bm.verts.new(point.co)
                    verts.append(vert)

            for i in range(len(verts) - 1):
                bm.edges.new((verts[i], verts[i + 1]))

            if spline.use_cyclic_u:
                bm.edges.new((verts[-1], verts[0]))

        mesh_data = bpy.data.meshes.new(curve_obj.name + "_Mesh")
        mesh_obj = bpy.data.objects.new(mesh_data.name, mesh_data)
        context.collection.objects.link(mesh_obj)

        mesh_obj.matrix_world = curve_obj.matrix_world

        bm.to_mesh(mesh_data)
        bm.free()

        radius_vg = mesh_obj.vertex_groups.new(name="Radius")
        tilt_vg = mesh_obj.vertex_groups.new(name="Tilt")

        for i, vert in enumerate(mesh_obj.data.vertices):
            radius = curve_data.splines[0].points[i].radius if i < len(curve_data.splines[0].points) else 1.0
            tilt = curve_data.splines[0].points[i].tilt if i < len(curve_data.splines[0].points) else 0.0
            tilt_normalized = (tilt + 1) / 2
            radius_vg.add([vert.index], radius, 'REPLACE')
            tilt_vg.add([vert.index], tilt_normalized, 'REPLACE')

        self.report({'INFO'}, f"Converted curve to mesh: {mesh_obj.name}")
        return {'FINISHED'}
