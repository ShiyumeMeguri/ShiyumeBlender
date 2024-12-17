import bpy
import bmesh

def create_uv_projection_mesh():
    # 获取当前选中的对象
    obj = bpy.context.active_object

    # 确保对象是网格
    if obj is None or obj.type != 'MESH':
        print("No mesh object is selected.")
        return None

    # 创建一个新的网格对象
    mesh_data = bpy.data.meshes.new(obj.name + "_UV_Projection")
    uv_mesh = bpy.data.objects.new(obj.name + "_UV_Projection", mesh_data)
    bpy.context.collection.objects.link(uv_mesh)

    # 如果原始对象有材质，复制到新对象
    if obj.material_slots:
        for material in obj.material_slots:
            uv_mesh.data.materials.append(material.material)

    # 使用bmesh复制原始网格的UV数据
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.verify()

    # 确保每个顶点都是独立的，以正确投影UV
    bmesh.ops.split_edges(bm, edges=bm.edges)

    # 直接修改顶点位置而不是创建新的面
    for face in bm.faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            # 仅修改顶点位置
            loop.vert.co = (uv.x, uv.y, 0)  # 投影到平面

    # 更新网格数据
    bm.to_mesh(mesh_data)
    bm.free()

    # 设置新对象为活动状态，以便执行remove_doubles
    bpy.context.view_layer.objects.active = uv_mesh
    uv_mesh.select_set(True)
    
    # 进入编辑模式并全选，合并相邻顶点
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')  # 全选顶点
    bpy.ops.mesh.remove_doubles()  # 合并相邻顶点
    bpy.ops.object.mode_set(mode='OBJECT')  # 返回对象模式

    return uv_mesh
    
# 使用示例
uv_projection = create_uv_projection_mesh()
