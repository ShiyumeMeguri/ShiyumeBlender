import bpy
import bmesh
import math
import os
from mathutils import Vector

class SHIYUME_OT_UVPackLockGroup(bpy.types.Operator):
    """Pack UVs and assign indexed lock groups for UVPackmaster"""
    bl_idname = "shiyume.uv_pack_lock_group"
    bl_label = "UV Pack & Lock Group"
    bl_options = {'REGISTER', 'UNDO'}

    offset: bpy.props.FloatProperty(name="UV Offset", default=2.0)

    def execute(self, context):
        current_offset = 0.0
        group_count = 1
        initial_selection = context.selected_objects.copy()
        
        objects = [obj for obj in initial_selection if obj.type == 'MESH']
        for obj in objects:
            context.view_layer.objects.active = obj
            
            dim = obj.dimensions
            length = math.sqrt(dim.x**2 + dim.y**2 + dim.z**2)
            scale = 1/length if length >= 1 else 1
            
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.verify()
            
            for face in bm.faces:
                for loop in face.loops:
                    loop[uv_layer].uv.x += current_offset
                    loop[uv_layer].uv *= scale
            
            bmesh.update_edit_mesh(obj.data)
            
            # Lock Group logic (depends on UVPackmaster 3)
            try:
                context.scene.uvpm3_props.numbered_groups_descriptors.lock_group.group_num = group_count
                bpy.ops.uvpackmaster3.numbered_group_set_iparam(groups_desc_id="lock_group")
            except:
                self.report({'WARNING'}, "UVPackmaster 3 props not found, skipped group locking")
            
            group_count += 1
            current_offset += self.offset
            bpy.ops.object.mode_set(mode='OBJECT')

        return {'FINISHED'}

class SHIYUME_OT_UVRenderTexture(bpy.types.Operator):
    """Render UV layout of objects in 'RT' collection to a texture"""
    bl_idname = "shiyume.uv_render_texture"
    bl_label = "Render UV to Texture"
    bl_options = {'REGISTER'}

    resolution: bpy.props.IntProperty(name="Resolution", default=4096)

    def execute(self, context):
        rt_col = bpy.data.collections.get('RT')
        if not rt_col:
            rt_col = bpy.data.collections.new('RT')
            context.scene.collection.children.link(rt_col)
            self.report({'INFO'}, "Created 'RT' collection. Move objects there and run again.")
            return {'FINISHED'}

        if not rt_col.objects:
            self.report({'WARNING'}, "'RT' collection is empty")
            return {'CANCELLED'}

        # Get save path
        base_path = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        filepath = os.path.join(base_path, "RT_UV_Layout.png")

        # Select all objects in RT collection
        bpy.ops.object.select_all(action='DESELECT')
        for obj in rt_col.objects:
            if obj.type == 'MESH':
                obj.select_set(True)
        
        # Must be in edit mode for UV export
        context.view_layer.objects.active = [obj for obj in rt_col.objects if obj.type == 'MESH'][0]
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        try:
            bpy.ops.uv.export_layout(filepath=filepath, size=(self.resolution, self.resolution), opacity=1.0)
            self.report({'INFO'}, f"UV Layout exported to: {filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

        return {'FINISHED'}

class SHIYUME_OT_MeshUVSync(bpy.types.Operator):
    """Setup live synchronization between mesh and its UV layout using Shape Keys"""
    bl_idname = "shiyume.mesh_uv_sync"
    bl_label = "Mesh UV Sync Setup"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}
        
        # 1. Shape Key setup
        if not obj.data.shape_keys:
            obj.shape_key_add(name="Basis")
        
        sk_name = "UV_Layout"
        sk = obj.data.shape_keys.key_blocks.get(sk_name)
        if not sk:
            sk = obj.shape_key_add(name=sk_name)
        
        # 2. Bmesh access
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if not uv_layer:
            self.report({'ERROR'}, "No active UV layer")
            bm.free()
            return {'CANCELLED'}
            
        sk_layer = bm.verts.layers.shape.get(sk_name)
        
        # Map vertex to UV (taking first loop's UV)
        for v in bm.verts:
            if v.link_loops:
                uv = v.link_loops[0][uv_layer].uv
                v[sk_layer] = Vector((uv.x, uv.y, 0.0))
            else:
                v[sk_layer] = v.co
                
        bm.to_mesh(obj.data)
        bm.free()
        
        sk.value = 1.0
        self.report({'INFO'}, "Setup UV Layout Shape Key")
        return {'FINISHED'}

class SHIYUME_OT_MeshToUV(bpy.types.Operator):
    """Create a new mesh object with shape keys to morph between 3D and UV layout (Robust)"""
    bl_idname = "shiyume.mesh_to_uv"
    bl_label = "Mesh to UV (Robust)"
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

classes = (
    SHIYUME_OT_UVPackLockGroup,
    SHIYUME_OT_UVRenderTexture,
    SHIYUME_OT_MeshUVSync,
    SHIYUME_OT_MeshToUV,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
