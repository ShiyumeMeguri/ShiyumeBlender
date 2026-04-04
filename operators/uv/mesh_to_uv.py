import bpy
import bmesh
from mathutils import Vector


class SHIYUME_OT_MeshToUV(bpy.types.Operator):
    """创建一个新的网格对象，并完整保留原物体的网格数据。
    新对象会追加一个 UVSync 形态键，用于把顶点移动到 UV 坐标位置。
    原对象不会被修改。"""

    bl_idname = "shiyume.mesh_to_uv"
    bl_label = "网格转UV (物理展开)"
    bl_options = {"REGISTER", "UNDO"}

    def _copy_shape_key_settings(self, source_obj, new_obj):
        old_shape_keys = source_obj.data.shape_keys
        new_shape_keys = new_obj.data.shape_keys
        if not old_shape_keys or not new_shape_keys:
            return

        old_blocks = old_shape_keys.key_blocks
        new_blocks = new_shape_keys.key_blocks
        relative_names = {}

        for old_key in old_blocks:
            relative_names[old_key.name] = (
                old_key.relative_key.name if old_key.relative_key else None
            )

        for old_key in old_blocks:
            new_key = new_blocks.get(old_key.name)
            if new_key is None:
                continue
            new_key.value = old_key.value
            new_key.slider_min = old_key.slider_min
            new_key.slider_max = old_key.slider_max
            new_key.mute = old_key.mute
            new_key.interpolation = old_key.interpolation
            new_key.vertex_group = old_key.vertex_group

        for old_key in old_blocks:
            new_key = new_blocks.get(old_key.name)
            relative_name = relative_names.get(old_key.name)
            if new_key is None or relative_name is None:
                continue
            relative_key = new_blocks.get(relative_name)
            if relative_key is not None:
                new_key.relative_key = relative_key

    def process_object(self, context, source_obj):
        if not source_obj.data.uv_layers.active:
            self.report(
                {"WARNING"},
                f"Object '{source_obj.name}' has no active UV layer, skipping.",
            )
            return None

        source_shape_keys = (
            source_obj.data.shape_keys.key_blocks
            if source_obj.data.shape_keys
            else None
        )

        # 1. Duplicate only mesh data. The new object keeps default object-level state.
        new_mesh_data = source_obj.data.copy()
        new_mesh_data.name = source_obj.data.name + "_UV_Shape"
        new_obj = bpy.data.objects.new(source_obj.name + "_UV_Shape", new_mesh_data)
        context.collection.objects.link(new_obj)

        # 2. Split UV island borders on the duplicate and record which source vertex
        # each new vertex comes from, so we can rebuild all shape keys afterwards.
        bm = bmesh.new()
        bm.from_mesh(new_obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            bm.free()
            self.report(
                {"WARNING"},
                f"Object '{source_obj.name}' has no active UV layer, skipping.",
            )
            bpy.data.objects.remove(new_obj, do_unlink=True)
            return None

        source_index_layer = bm.verts.layers.int.get("_source_vert_index")
        if source_index_layer is None:
            source_index_layer = bm.verts.layers.int.new("_source_vert_index")

        for vert in bm.verts:
            vert[source_index_layer] = vert.index

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

        source_vert_indices = [vert[source_index_layer] for vert in bm.verts]
        uv_coords_map = {}
        for face in bm.faces:
            for loop in face.loops:
                vert_index = loop.vert.index
                if vert_index not in uv_coords_map:
                    uv = loop[uv_layer].uv
                    uv_coords_map[vert_index] = Vector((uv.x, uv.y, 0.0))

        # Writing split topology back invalidates copied shape keys, so rebuild them next.
        if new_obj.data.shape_keys:
            new_obj.shape_key_clear()

        bm.to_mesh(new_obj.data)
        new_obj.data.update()
        bm.free()

        # 3. Rebuild original shape keys on top of the split topology.
        if source_shape_keys:
            for key_block in source_shape_keys:
                new_key = new_obj.shape_key_add(name=key_block.name, from_mix=False)
                for i, source_vert_index in enumerate(source_vert_indices):
                    new_key.data[i].co = key_block.data[source_vert_index].co
        else:
            new_obj.shape_key_add(name="Basis", from_mix=False)

        sk_uv = new_obj.data.shape_keys.key_blocks.get("UVSync")
        if sk_uv is None:
            sk_uv = new_obj.shape_key_add(name="UVSync", from_mix=False)

        basis_key = new_obj.data.shape_keys.key_blocks[0]
        for i, _vert in enumerate(new_obj.data.vertices):
            if i in uv_coords_map:
                sk_uv.data[i].co = uv_coords_map[i]
            else:
                sk_uv.data[i].co = basis_key.data[i].co

        # 4. Restore shape key settings from the source object.
        if source_shape_keys:
            self._copy_shape_key_settings(source_obj, new_obj)

        sk_uv.value = 1.0
        return new_obj

    def execute(self, context):
        selected_meshes = [
            obj for obj in context.selected_objects if obj.type == "MESH"
        ]

        if not selected_meshes:
            self.report({"ERROR"}, "Select at least one mesh object")
            return {"CANCELLED"}

        created_objects = []

        # Process all selected objects
        for obj in selected_meshes:
            new_obj = self.process_object(context, obj)
            if new_obj:
                created_objects.append(new_obj)

        if not created_objects:
            return {"CANCELLED"}

        # Deselect old, select new
        bpy.ops.object.select_all(action="DESELECT")
        for obj in created_objects:
            obj.select_set(True)

        context.view_layer.objects.active = created_objects[-1]

        self.report({"INFO"}, f"Created {len(created_objects)} UV mesh copies")
        return {"FINISHED"}
