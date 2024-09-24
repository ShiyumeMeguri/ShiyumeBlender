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
class ToCurve(Operator):
    bl_idname = "mesh.shiyumetools_tocurve"
    bl_label = "ToCurve"
    bl_description = "ToCurve the vertices in a regular distribution on the loop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob and ob.type == 'MESH' and context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        # 检查是否有对应的顶点组
        obj = bpy.context.active_object
        if "Radius" in obj.vertex_groups.keys() and "Tilt" in obj.vertex_groups.keys():
            radius_vg = obj.vertex_groups["Radius"]
            tilt_vg = obj.vertex_groups["Tilt"]
        else:
            return{'Mesh对象缺少必要的顶点组'}

        # 创建一个新的曲线数据块
        curveData = bpy.data.curves.new('VertexCurve', 'CURVE')
        curveData.dimensions = '3D'

        # 创建一个新的曲线对象，并将其添加到当前场景中
        curveObj = bpy.data.objects.new('VertexCurveObj', curveData)
        bpy.context.collection.objects.link(curveObj)

        # 创建一个新的曲线段
        polyline = curveData.splines.new('NURBS')
        polyline.points.add(len(obj.data.vertices) - 1)
        polyline.order_u = 5
        polyline.use_endpoint_u = True

        # 根据顶点位置设置曲线点
        for i, vertex in enumerate(obj.data.vertices):
            # 设置曲线点位置
            x, y, z = obj.matrix_world @ vertex.co  # 应用物体的世界变换
            polyline.points[i].co = (x, y, z, 1)
            
            # 获取radius和tilt值
            radius = radius_vg.weight(vertex.index)
            tilt = (tilt_vg.weight(vertex.index) * 2) - 1  # 将tilt的取值范围从[0, 1]转换回[-1, 1]
            
            # 设置radius和tilt
            polyline.points[i].radius = radius
            polyline.points[i].tilt = tilt
        
        bpy.context.view_layer.objects.active = curveObj
        bpy.ops.object.select_all(action='DESELECT')
        curveObj.select_set(True)
        
        return{'FINISHED'}