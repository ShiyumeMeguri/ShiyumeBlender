import bpy
import bmesh

def create_bake_material():
    # Create a new material for baking
    if "BakeMaterial" not in bpy.data.materials:
        bake_material = bpy.data.materials.new(name="BakeMaterial")
        # Configure the material as needed, for example setting it to be non-reflective
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

    # Create a bake material
    bake_material = create_bake_material()

    uv_meshes = []

    for obj in objects:
        if obj.type != 'MESH':
            print(f"{obj.name} is not a mesh object.")
            continue

        # Create a new mesh object
        mesh_data = bpy.data.meshes.new(obj.name + "_UV_Projection")
        uv_mesh = bpy.data.objects.new(obj.name + "_UV_Projection", mesh_data)
        uv_sync_collection.objects.link(uv_mesh)

        # Unlink the new object from all other collections it might be linked to
        for collection in list(uv_mesh.users_collection):
            if collection != uv_sync_collection:
                collection.objects.unlink(uv_mesh)

        # If the original object has materials, copy them to the new object
        if obj.material_slots:
            for material in obj.material_slots:
                uv_mesh.data.materials.append(material.material)

        # Clear materials from the original object
        obj.data.materials.clear()

        # Assign BakeMaterial to the original object
        obj.data.materials.append(bake_material)

        # Use bmesh to copy the original mesh's UV data
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        # Ensure each vertex is independent for correct UV projection
        bmesh.ops.split_edges(bm, edges=bm.edges)

        # Modify vertex positions directly instead of creating new faces
        for face in bm.faces:
            for loop in face.loops:
                uv = loop[uv_layer].uv
                loop.vert.co = (uv.x, uv.y, 0)  # Project to plane

        # Update mesh data
        bm.to_mesh(mesh_data)
        bm.free()

        uv_meshes.append(uv_mesh)

    return uv_meshes


def update_uv_projection(obj_name, uv_mesh_name):
    # 获取原始对象和投影网格对象
    obj = bpy.data.objects[obj_name]
    uv_mesh = bpy.data.objects[uv_mesh_name]

    # 使用bmesh更新投影网格
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.active

    bm_uv = bmesh.new()
    bm_uv.from_mesh(uv_mesh.data)

    # 确保每个顶点都是独立的
    bmesh.ops.split_edges(bm, edges=bm.edges)
    bmesh.ops.split_edges(bm_uv, edges=bm_uv.edges)

    # 同步UV坐标到投影网格
    for face, uv_face in zip(bm.faces, bm_uv.faces):
        uv_face.material_index = face.material_index  # 更新材质索引
        for loop, uv_loop in zip(face.loops, uv_face.loops):
            uv = loop[uv_layer].uv
            uv_loop.vert.co = (uv.x, uv.y, 0)  # 更新坐标

    # 更新网格数据
    bm_uv.to_mesh(uv_mesh.data)
    bm.free()
    bm_uv.free()
    
def frame_change_callback(scene, depsgraph):
    frame = scene.frame_current
    if frame % 10 == 0:  # Update only every 10 frames
        if "UVSync" in bpy.data.collections:
            for uv_mesh in bpy.data.collections["UVSync"].objects:
                obj_name = uv_mesh.name.replace("_UV_Projection", "")
                if obj_name in bpy.data.objects:
                    update_uv_projection(obj_name, uv_mesh.name)

# Register frame change callback
bpy.app.handlers.frame_change_post.append(frame_change_callback)

# Example usage
selected_objects = bpy.context.selected_objects
uv_projections = create_uv_projection_mesh(selected_objects)
