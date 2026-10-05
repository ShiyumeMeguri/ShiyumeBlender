import bmesh
import bpy
from bpy_extras import bmesh_utils


class SHIYUME_OT_SelectIslandSeam(bpy.types.Operator):
    """选孤岛接缝边：选中 UV 孤岛之间共用的边（头发正反两面相接的两条侧边）。
    网格开口的首尾边只挨着一个面，不会被选中，所以接下来按距离合并
    不会把发根发尖的顶点并掉。有选中的面时只处理挨着选中面的接缝，否则处理整个网格。"""
    bl_idname = "shiyume.select_island_seam"
    bl_label = "选孤岛接缝边"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        context.tool_settings.mesh_select_mode = (False, True, False)
        edge_total = 0

        for obj in context.objects_in_mode_unique_data:
            if obj.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                continue

            selected = {face for face in bm.faces if face.select and not face.hide}
            owner = {face: index
                     for index, faces in enumerate(bmesh_utils.bmesh_linked_uv_islands(bm, uv_layer))
                     for face in faces}

            seams = []
            for edge in bm.edges:
                if edge.hide or len(edge.link_faces) != 2:
                    continue
                first, second = edge.link_faces
                if owner[first] == owner[second]:
                    continue
                if selected and first not in selected and second not in selected:
                    continue
                seams.append(edge)

            for face in bm.faces:
                face.select_set(False)
            for edge in bm.edges:
                edge.select_set(False)
            for vert in bm.verts:
                vert.select_set(False)
            for edge in seams:
                edge.select_set(True)

            bm.select_flush_mode()
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            edge_total += len(seams)

        self.report({'INFO'}, f"已选中 {edge_total} 条孤岛接缝边")
        return {'FINISHED'}
