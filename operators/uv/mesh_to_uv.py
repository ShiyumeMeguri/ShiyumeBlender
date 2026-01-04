import bpy
import bmesh
from mathutils import Vector

class SHIYUME_OT_MeshToUV(bpy.types.Operator):
    """创建一个新的网格对象，该对象是原物体的"展开"版本。
    它包含两个形态键：Basis (3D形态) 和 UVSync (UV铺平形态)。
    不同于简单的UV同步，此工具会切断所有的 UV 边界边，确保展平时 UV 岛是物理分离的。"""
    bl_idname = "shiyume.mesh_to_uv"
    bl_label = "网格转UV (物理展开)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        source_obj = context.active_object
        if source_obj is None or source_obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}

        if not source_obj.data.uv_layers.active:
            self.report({'ERROR'}, "No active UV layer")
            return {'CANCELLED'}

        # 1. Bmesh processing to split UV islands
        bm = bmesh.new()
        bm.from_mesh(source_obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        uv_layer = bm.loops.layers.uv.active
        edges_to_split = set()
        epsilon = 1e-6

        for edge in bm.edges:
            if edge.seam:
                edges_to_split.add(edge)
                continue
            if not edge.is_manifold:
                edges_to_split.add(edge)
                continue

            l1 = edge.link_loops[0]
            l2 = edge.link_loops[1]
            v1, v2 = edge.verts

            # Map loop UVs for comparison
            l1_uvs = {l.vert.index: l[uv_layer].uv for l in l1.face.loops}
            l2_uvs = {l.vert.index: l[uv_layer].uv for l in l2.face.loops}

            if v1.index not in l2_uvs or v2.index not in l2_uvs:
                edges_to_split.add(edge)
                continue

            v1_match = (l1_uvs[v1.index] - l2_uvs[v1.index]).length < epsilon
            v2_match = (l1_uvs[v2.index] - l2_uvs[v2.index]).length < epsilon

            if not (v1_match and v2_match):
                edges_to_split.add(edge)

        if edges_to_split:
            bmesh.ops.split_edges(bm, edges=list(edges_to_split))

        bm.verts.ensure_lookup_table()

        # 2. Collect UV coordinates for the shape key
        uv_coords_map = {}
        for face in bm.faces:
            for loop in face.loops:
                vert_index = loop.vert.index
                if vert_index not in uv_coords_map:
                    uv = loop[uv_layer].uv
                    uv_coords_map[vert_index] = Vector((uv.x, uv.y, 0.0))

        # 3. Create new mesh and object
        new_mesh_data = bpy.data.meshes.new(source_obj.name + "_UV_Shape")
        bm.to_mesh(new_mesh_data)
        bm.free()

        new_obj = bpy.data.objects.new(new_mesh_data.name, new_mesh_data)
        context.collection.objects.link(new_obj)

        # Copy materials
        for mat_slot in source_obj.material_slots:
            new_obj.data.materials.append(mat_slot.material)

        # 4. Setup Shape Keys
        sk_basis = new_obj.shape_key_add(name='Basis', from_mix=False)
        sk_uv = new_obj.shape_key_add(name='UVSync', from_mix=False)

        for i, vert in enumerate(new_obj.data.vertices):
            if i in uv_coords_map:
                sk_uv.data[i].co = uv_coords_map[i]
            else:
                sk_uv.data[i].co = sk_basis.data[i].co

        # 5. Finalize
        new_obj.matrix_world = source_obj.matrix_world
        new_obj.location.x += source_obj.dimensions.x * 1.2
        
        context.view_layer.objects.active = new_obj
        new_obj.select_set(True)
        source_obj.select_set(False)
        sk_uv.value = 1.0

        self.report({'INFO'}, f"Created robust UV Mesh: {new_obj.name}")
        return {'FINISHED'}
