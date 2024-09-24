import bpy
import bmesh
from bpy.types import (
        Operator,
        Menu,
        Panel,
        PropertyGroup,
        AddonPreferences,
        )

# tomesh operator
class ToMesh(Operator):
    bl_idname = "curve.shiyumetools_tomesh"
    bl_label = "ToMesh"
    bl_description = "ToMesh the vertices in a regular distribution on the loop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob and ob.type == 'CURVE' and context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        curve_obj = bpy.context.active_object
        curve_data = curve_obj.data
        
        bm = bmesh.new()
        verts = []
        for spline in curve_data.splines:
            verts.clear()  # 清空顶点列表以开始新的spline
            if spline.type == 'POLY' or spline.type == 'NURBS':
                for point in spline.points:
                    vert = bm.verts.new(point.co.xyz)  # 创建新顶点
                    verts.append(vert)
            
            # 在相邻顶点之间添加边
            for i in range(len(verts)-1):
                bm.edges.new((verts[i], verts[i+1]))
            
            # 如果spline是闭合的，添加一条从最后一个顶点到第一个顶点的边
            if spline.use_cyclic_u:
                bm.edges.new((verts[-1], verts[0]))
        
        # 创建新的网格数据和对象
        mesh_data = bpy.data.meshes.new(curve_obj.name + "_Mesh")
        mesh_obj = bpy.data.objects.new(mesh_data.name, mesh_data)
        bpy.context.collection.objects.link(mesh_obj)  # 将新网格对象添加到当前集合
        
        # 可选：复制原曲线对象的变换到新网格对象
        mesh_obj.matrix_world = curve_obj.matrix_world
        
        bm.to_mesh(mesh_data)
        bm.free()
        
        # 创建顶点组并赋值
        radius_vg = mesh_obj.vertex_groups.new(name="Radius")
        tilt_vg = mesh_obj.vertex_groups.new(name="Tilt")
        
        for i, vert in enumerate(mesh_obj.data.vertices):
            radius = curve_data.splines[0].points[i].radius if i < len(curve_data.splines[0].points) else 1.0
            tilt = curve_data.splines[0].points[i].tilt if i < len(curve_data.splines[0].points) else 0.0
            # tilt的取值范围是-1 - 1 需要转换
            tilt_normalized = (tilt + 1) / 2
            radius_vg.add([vert.index], radius, 'REPLACE')
            tilt_vg.add([vert.index], tilt_normalized, 'REPLACE')
        
        bpy.context.view_layer.objects.active = mesh_obj
        bpy.ops.object.select_all(action='DESELECT')
        mesh_obj.select_set(True)
        
        return{'FINISHED'}