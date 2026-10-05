import bmesh
import bpy
import numpy


class SHIYUME_OT_SelectIslandInner(bpy.types.Operator):
    """孤岛边缘去首尾选边：按孤岛（连通块）只选中边界边（相当于「选择选区边界」），
    并沿主轴方向排除首尾两端的顶点。用于头发正反两面合并前的选择，
    避免发根/发尖处重合的顶点被「按距离合并」误并。
    有选中面时只处理选中的面，否则处理整个网格。"""
    bl_idname = "shiyume.select_island_inner"
    bl_label = "孤岛边缘去首尾选边"
    bl_options = {'REGISTER', 'UNDO'}

    end_ratio: bpy.props.FloatProperty(
        name="首尾比例",
        default=0.02,
        min=0.0,
        max=0.49,
        precision=3,
        description="沿孤岛主轴方向，首尾各占长度该比例以内的顶点被排除；0 只排除最末一排",
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def _collect_islands(self, faces):
        remaining = set(faces)
        islands = []
        while remaining:
            seed = remaining.pop()
            island = [seed]
            stack = [seed]
            while stack:
                face = stack.pop()
                for edge in face.edges:
                    for neighbor in edge.link_faces:
                        if neighbor in remaining:
                            remaining.remove(neighbor)
                            island.append(neighbor)
                            stack.append(neighbor)
            islands.append(island)
        return islands

    def _end_vertices(self, vertices):
        points = numpy.array([vertex.co[:] for vertex in vertices], dtype=numpy.float64)
        centered = points - points.mean(axis=0)
        eigenvalues, eigenvectors = numpy.linalg.eigh(centered.T @ centered)
        axis = eigenvectors[:, numpy.argmax(eigenvalues)]
        projection = centered @ axis
        low = projection.min()
        length = projection.max() - low
        margin = length * self.end_ratio + length * 1e-6
        return {
            vertex
            for vertex, value in zip(vertices, projection)
            if value <= low + margin or value >= low + length - margin
        }

    def execute(self, context):
        objects = [obj for obj in context.objects_in_mode_unique_data if obj.type == 'MESH']
        edge_total = 0
        excluded_total = 0

        for obj in objects:
            bm = bmesh.from_edit_mesh(obj.data)
            selected = [face for face in bm.faces if face.select and not face.hide]
            scope = selected if selected else [face for face in bm.faces if not face.hide]
            scope_set = set(scope)

            kept_edges = []
            for island in self._collect_islands(scope):
                island_set = set(island)
                vertices = list({vertex for face in island for vertex in face.verts})
                ends = self._end_vertices(vertices)
                excluded_total += len(ends)
                island_edges = {edge for face in island for edge in face.edges}
                for edge in island_edges:
                    inside = sum(1 for face in edge.link_faces if face in island_set)
                    if inside != 1:
                        continue
                    if edge.verts[0] in ends or edge.verts[1] in ends:
                        continue
                    kept_edges.append(edge)

            for face in bm.faces:
                face.select_set(False)
            for edge in bm.edges:
                edge.select_set(False)
            for vertex in bm.verts:
                vertex.select_set(False)

            for edge in kept_edges:
                edge.select_set(True)

            bm.select_flush_mode()
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            edge_total += len(kept_edges)

        self.report({'INFO'}, f"已选中 {edge_total} 条边缘边，排除首尾顶点 {excluded_total} 个")
        return {'FINISHED'}
