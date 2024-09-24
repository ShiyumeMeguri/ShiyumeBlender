import bpy
import bmesh
import math

uv_offset = 2.0
current_offset = 0.0
group_count = 1  # 初始化组号为 1

# 保存初始选中对象的列表
initial_selection = bpy.context.selected_objects.copy()

# 过滤出类型为 'MESH' 的选中对象
objects_to_process = [obj for obj in initial_selection if obj.type == 'MESH']

for obj in objects_to_process:
    # 单独选中当前处理的对象
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # 检查对象是否有顶点
    if len(obj.data.vertices) == 0:
        print(f"对象 {obj.name} 没有顶点，跳过处理。")
        continue

    # 获取对象在世界空间中的维度向量长度
    dimensions = obj.dimensions
    dimension_length = math.sqrt(dimensions.x**2 + dimensions.y**2 + dimensions.z**2)
    scale_factor = 1 / dimension_length if dimension_length >= 1 else 1

    # 切换到编辑模式并设置适当的面板
    bpy.ops.object.mode_set(mode='EDIT')

    # 创建一个 bmesh 实例并获取 UV 图层
    bm = bmesh.from_edit_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.verify()

    # 选择所有 UVs
    bpy.ops.uv.select_all(action='DESELECT')  # 先清除选中
    bpy.ops.uv.select_all(action='SELECT')    # 选择所有 UV

    # 移动和缩放所有 UVs
    for face in bm.faces:
        for loop in face.loops:
            loop_uv = loop[uv_layer]
            loop_uv.uv.x += current_offset  # 增加 X 坐标偏移量
            loop_uv.uv *= scale_factor  # 缩放 UVs

    # 刷新 bmesh 的更改到 mesh
    bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)

    # 退出编辑模式
    bpy.ops.object.mode_set(mode='OBJECT')

    # 重新选中对象并锁定 UVs
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    
    # 设置 UV 组号
    bpy.context.scene.uvpm3_props.numbered_groups_descriptors.lock_group.group_num = group_count
    bpy.ops.uvpackmaster3.numbered_group_set_iparam(groups_desc_id="lock_group")

    group_count += 1  # 增加组号以用于下一个对象

    bpy.ops.object.mode_set(mode='OBJECT')

    # 更新偏移量以供下一个对象使用
    current_offset += uv_offset

# 恢复初始选中状态
bpy.ops.object.select_all(action='DESELECT')
for obj in initial_selection:
    obj.select_set(True)
