import bpy
import bmesh

# 确保处于对象模式
bpy.ops.object.mode_set(mode='OBJECT')

# 获取当前选中的对象
obj = bpy.context.active_object

# 确保对象是一个网格
if obj.type == 'MESH':
    # 创建一个新的UV Map，命名为"RuriOutlineNormal"，如果已存在则使用现有的
    uv_map_name = "OutlineNormal"
    if uv_map_name not in obj.data.uv_layers:
        obj.data.uv_layers.new(name=uv_map_name)
    uv_layer = obj.data.uv_layers[uv_map_name]

    # 获取网格数据
    mesh = obj.data
    
    # 进入编辑模式
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(mesh)
    
    # 确保我们在正确的UV Map中操作
    uv_layer = bm.loops.layers.uv[uv_map_name]

    # 遍历每个顶点，并设置UV坐标
    for face in bm.faces:
        for loop in face.loops:
            normal = loop.vert.normal
            # 将法线的X和Y分量存储到UV坐标中
            loop[uv_layer].uv = (normal.x, normal.y)
    
    # 更新网格
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    bpy.ops.object.mode_set(mode='OBJECT')
else:
    print("选中的不是网格对象。")

print("完成将法线的XY分量写入到'OutlineNormal' UV Map。")
