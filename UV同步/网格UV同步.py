import bpy
import bmesh

def create_bake_material():
    # Create a new material for baking
    if "BakeMaterial" not in bpy.data.materials:
        bake_material = bpy.data.materials.new(name="BakeMaterial")
        bake_material.use_nodes = True
        bsdf = bake_material.node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Roughness'].default_value = 1.0
    else:
        bake_material = bpy.data.materials.get("BakeMaterial")
    return bake_material

def create_uv_projection_mesh(objects):
    # Create or get the UVSync collection
    if "UVSync" not in bpy.data.collections:
        uv_sync_collection = bpy.data.collections.new("UVSync")
        bpy.context.scene.collection.children.link(uv_sync_collection)
    else:
        uv_sync_collection = bpy.data.collections["UVSync"]

    bake_material = create_bake_material()
    uv_meshes = []

    for obj in objects:
        if obj.type != 'MESH':
            print(f"{obj.name} is not a mesh object.")
            continue

        uv_name = obj.name + "_UV_Projection"
        # 如果已经有同步网格，则直接更新顶点，不再创建新的
        if uv_name in bpy.data.objects:
            update_uv_projection(obj.name, uv_name)
            uv_meshes.append(bpy.data.objects[uv_name])
            continue

        # Create a new mesh object
        mesh_data = bpy.data.meshes.new(uv_name)
        uv_mesh = bpy.data.objects.new(uv_name, mesh_data)
        uv_sync_collection.objects.link(uv_mesh)

        # Unlink from other collections
        for collection in list(uv_mesh.users_collection):
            if collection != uv_sync_collection:
                collection.objects.unlink(uv_mesh)

        # Copy materials
        if obj.material_slots:
            for material in obj.material_slots:
                uv_mesh.data.materials.append(material.material)
        obj.data.materials.clear()
        obj.data.materials.append(bake_material)

        # Use bmesh to copy UVs and project verts
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()
        bmesh.ops.split_edges(bm, edges=bm.edges)

        for face in bm.faces:
            for loop in face.loops:
                uv = loop[uv_layer].uv
                loop.vert.co = (uv.x, uv.y, 0)

        bm.to_mesh(mesh_data)
        bm.free()

        uv_meshes.append(uv_mesh)

    return uv_meshes

def update_uv_projection(obj_name, uv_mesh_name):
    obj = bpy.data.objects[obj_name]
    uv_mesh = bpy.data.objects[uv_mesh_name]

    bm_src = bmesh.new()
    bm_src.from_mesh(obj.data)
    uv_layer = bm_src.loops.layers.uv.active

    bm_dst = bmesh.new()
    bm_dst.from_mesh(uv_mesh.data)

    bmesh.ops.split_edges(bm_src, edges=bm_src.edges)
    bmesh.ops.split_edges(bm_dst, edges=bm_dst.edges)

    # 刷新 faces 的内部索引表，避免 BMElemSeq[index] 错误
    bm_src.faces.ensure_lookup_table()
    bm_dst.faces.ensure_lookup_table()

    # 按面索引同步 UV 坐标，避免索引错位
    for face in bm_src.faces:
        dst_face = bm_dst.faces[face.index]
        dst_face.material_index = face.material_index
        for i, loop in enumerate(face.loops):
            uv = loop[uv_layer].uv
            dst_face.loops[i].vert.co = (uv.x, uv.y, 0)

    bm_dst.to_mesh(uv_mesh.data)
    bm_src.free()
    bm_dst.free()

def frame_change_callback(scene, depsgraph):
    frame = scene.frame_current
    if frame % 10 == 0:  # Update only every 10 frames
        if "UVSync" in bpy.data.collections:
            for uv_mesh in bpy.data.collections["UVSync"].objects:
                obj_name = uv_mesh.name.replace("_UV_Projection", "")
                if obj_name in bpy.data.objects:
                    update_uv_projection(obj_name, uv_mesh.name)

# Register frame change callback
if frame_change_callback not in bpy.app.handlers.frame_change_post:
    bpy.app.handlers.frame_change_post.append(frame_change_callback)

# Example usage
selected_objects = bpy.context.selected_objects
uv_projections = create_uv_projection_mesh(selected_objects)
