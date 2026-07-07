"""曲线工具:平滑修复、曲线↔网格互转(Radius/Tilt 经顶点组无损往返)。"""

import bmesh
import bpy


class SHIYUME_OT_CurveSmoothFix(bpy.types.Operator):
    """修复曲线平滑度:样条转 NURBS 并启用 Endpoint U,
    端点正确贴合控制点。适合外部导入的发丝曲线显示不平滑的情况"""
    bl_idname = "shiyume.curve_smooth_fix"
    bl_label = "曲线平滑修复"
    bl_options = {'REGISTER', 'UNDO'}

    order: bpy.props.IntProperty(
        name="NURBS 阶数", default=5, min=2, max=6,
        description="阶数越高越平滑(受控制点数限制)",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        fixed = 0
        for obj in context.selected_objects:
            if obj.type != 'CURVE':
                continue
            for spline in obj.data.splines:
                if spline.type != 'NURBS':
                    spline.type = 'NURBS'
                spline.use_endpoint_u = True
                spline.order_u = min(len(spline.points), self.order)
            obj.update_tag()
            fixed += 1
        self.report({'INFO'}, f"已修复 {fixed} 条曲线")
        return {'FINISHED'}


class SHIYUME_OT_CurveToMesh(bpy.types.Operator):
    """曲线转网格(顶点链),radius 写入 'Radius' 顶点组、
    tilt 归一化到 0..1 写入 'Tilt' 顶点组,供「网格转曲线」无损还原。
    闭合样条首尾相接;多样条逐条正确取值"""
    bl_idname = "shiyume.curve_to_mesh"
    bl_label = "曲线转网格"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        curve_obj = context.active_object
        curve_data = curve_obj.data

        mesh_data = bpy.data.meshes.new(curve_obj.name + "_Mesh")
        mesh_obj = bpy.data.objects.new(mesh_data.name, mesh_data)
        context.collection.objects.link(mesh_obj)
        mesh_obj.matrix_world = curve_obj.matrix_world

        # 顶点组先建好,bmesh 形变层按同序对应
        mesh_obj.vertex_groups.new(name="Radius")
        mesh_obj.vertex_groups.new(name="Tilt")

        working = bmesh.new()
        deform_layer = working.verts.layers.deform.verify()

        for spline in curve_data.splines:
            if spline.type == 'BEZIER':
                points = [(point.co, point.radius, point.tilt) for point in spline.bezier_points]
            else:
                points = [(point.co.xyz, point.radius, point.tilt) for point in spline.points]
            if not points:
                continue

            chain = []
            for position, radius, tilt in points:
                vertex = working.verts.new(position)
                deform = vertex[deform_layer]
                deform[0] = radius
                deform[1] = (tilt + 1.0) / 2.0
                chain.append(vertex)

            for index in range(len(chain) - 1):
                working.edges.new((chain[index], chain[index + 1]))
            if spline.use_cyclic_u and len(chain) > 2:
                working.edges.new((chain[-1], chain[0]))

        working.to_mesh(mesh_data)
        working.free()

        self.report({'INFO'}, f"已转换为网格: {mesh_obj.name}")
        return {'FINISHED'}


class SHIYUME_OT_MeshToCurve(bpy.types.Operator):
    """网格顶点链转 NURBS 曲线,'Radius'/'Tilt' 顶点组写回控制点
    (Tilt 从 0..1 反归一化到 -1..1)。默认按边连通拆分样条,
    没有边时退回按顶点顺序连成单条"""
    bl_idname = "shiyume.mesh_to_curve"
    bl_label = "网格转曲线"
    bl_options = {'REGISTER', 'UNDO'}

    split_chains: bpy.props.BoolProperty(
        name="按边链拆分", default=True,
        description="沿边把网格分解成多条样条;关闭则全部顶点按序连成一条",
    )
    order: bpy.props.IntProperty(
        name="NURBS 阶数", default=5, min=2, max=6,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def _read_weights(self, obj):
        """Radius/Tilt 顶点组逐顶点取值;组缺失时返回默认。"""
        mesh = obj.data
        vertex_count = len(mesh.vertices)
        radius = [1.0] * vertex_count
        tilt = [0.0] * vertex_count

        radius_index = obj.vertex_groups.find("Radius")
        tilt_index = obj.vertex_groups.find("Tilt")
        if radius_index == -1 or tilt_index == -1:
            self.report({'WARNING'}, "缺少 Radius/Tilt 顶点组,使用默认值")
            return radius, tilt

        for vertex in mesh.vertices:
            for entry in vertex.groups:
                if entry.group == radius_index:
                    radius[vertex.index] = entry.weight
                elif entry.group == tilt_index:
                    tilt[vertex.index] = entry.weight * 2.0 - 1.0
        return radius, tilt

    @staticmethod
    def _vertex_chains(mesh):
        """按边连通把顶点分解成链:先从度 1 端点起走,再收剩余的环。"""
        adjacency = {}
        for edge in mesh.edges:
            a, b = edge.vertices
            adjacency.setdefault(a, []).append(b)
            adjacency.setdefault(b, []).append(a)

        visited = set()
        chains = []

        def walk(start):
            chain = [start]
            visited.add(start)
            current = start
            while True:
                next_vertex = next(
                    (neighbor for neighbor in adjacency.get(current, ()) if neighbor not in visited),
                    None,
                )
                if next_vertex is None:
                    return chain
                visited.add(next_vertex)
                chain.append(next_vertex)
                current = next_vertex

        for vertex_index, neighbors in adjacency.items():
            if len(neighbors) == 1 and vertex_index not in visited:
                chains.append(walk(vertex_index))
        for vertex_index in adjacency:
            if vertex_index not in visited:
                chains.append(walk(vertex_index))
        return chains

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        if not mesh.vertices:
            return {'CANCELLED'}

        radius, tilt = self._read_weights(obj)

        if self.split_chains and mesh.edges:
            chains = self._vertex_chains(mesh)
        else:
            chains = [list(range(len(mesh.vertices)))]

        curve_data = bpy.data.curves.new('VertexCurve', 'CURVE')
        curve_data.dimensions = '3D'
        curve_obj = bpy.data.objects.new('VertexCurveObj', curve_data)
        context.collection.objects.link(curve_obj)

        matrix = obj.matrix_world
        for chain in chains:
            if not chain:
                continue
            spline = curve_data.splines.new('NURBS')
            spline.points.add(len(chain) - 1)
            spline.order_u = min(len(chain), self.order)
            spline.use_endpoint_u = True

            for point, vertex_index in zip(spline.points, chain):
                x, y, z = matrix @ mesh.vertices[vertex_index].co
                point.co = (x, y, z, 1.0)
                point.radius = radius[vertex_index]
                point.tilt = tilt[vertex_index]

        self.report({'INFO'}, f"已生成 {len(chains)} 条样条")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_CurveSmoothFix,
    SHIYUME_OT_CurveToMesh,
    SHIYUME_OT_MeshToCurve,
)
