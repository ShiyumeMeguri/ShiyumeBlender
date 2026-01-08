import bpy
import bmesh

def prune_vertex_groups(obj, max_groups=4, min_weight=0.01):
    """
    清理所选顶点的顶点组。
    - 移除权重低于 min_weight 的顶点组。
    - 将每个顶点的顶点组数量限制为 max_groups，移除权重最低的组。
    """
    # 检查对象是否为网格类型
    if obj is None or obj.type != 'MESH':
        print("错误：请选择一个网格对象。")
        return

    # 记录原始模式
    original_mode = obj.mode

    # --- 使用 BMesh 获取选中的顶点 ---
    # 必须切换到编辑模式才能访问BMesh中的选择数据
    if original_mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')

    bm = bmesh.from_edit_mesh(obj.data)
    selected_verts_indices = [v.index for v in bm.verts if v.select]
    
    # 释放 bmesh
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode='OBJECT')

    if not selected_verts_indices:
        print("没有选择任何顶点。请在编辑模式下选择顶点后再运行脚本。")
        bpy.ops.object.mode_set(mode=original_mode)
        return

    print(f"找到了 {len(selected_verts_indices)} 个选中的顶点。")

    # 获取骨骼名称列表（如果存在父级骨架）
    bone_names = set()
    if obj.parent and obj.parent.type == 'ARMATURE':
        bone_names = set(bone.name for bone in obj.parent.data.bones)
        print(f"从父级骨架 '{obj.parent.name}' 中找到了 {len(bone_names)} 个骨骼。")
    else:
        print("警告：对象没有父级骨架，将处理所有顶点组。")

    verts_processed = 0
    # 对每个选中的顶点进行操作
    for v_index in selected_verts_indices:
        v = obj.data.vertices[v_index]
        
        # 获取顶点相关的顶点组及其权重
        if obj.parent and obj.parent.type == 'ARMATURE':
            # 如果有骨架，只考虑与骨骼同名的顶点组
            group_weights = [(g.group, g.weight) for g in v.groups if obj.vertex_groups[g.group].name in bone_names]
        else:
            # 如果没有骨架，处理所有顶点组
            group_weights = [(g.group, g.weight) for g in v.groups]

        # 1. 先移除所有权重小于最小值的顶点组
        groups_to_remove_low_weight = [gw[0] for gw in group_weights if gw[1] < min_weight]
        for group_index in groups_to_remove_low_weight:
            obj.vertex_groups[group_index].remove([v.index])

        # 2. 重新获取有效的顶点组，因为可能有变化
        if obj.parent and obj.parent.type == 'ARMATURE':
            group_weights = [(g.group, g.weight) for g in v.groups if obj.vertex_groups[g.group].name in bone_names]
        else:
            group_weights = [(g.group, g.weight) for g in v.groups]
            
        # 3. 如果顶点组数量仍超过最大允许值，则删除权重最低的组
        if len(group_weights) > max_groups:
            # 按权重排序（由低到高）
            group_weights.sort(key=lambda x: x[1])
            
            # 计算需要移除的组的数量
            num_to_remove = len(group_weights) - max_groups
            
            # 移除权重最低的组
            for i in range(num_to_remove):
                group_to_remove = group_weights[i]
                obj.vertex_groups[group_to_remove[0]].remove([v.index])
        
        verts_processed += 1

    print(f"处理完成，共修改了 {verts_processed} 个顶点。")
    
    # 更新网格数据以确保更改在视口中可见
    obj.data.update()

    # 恢复到原始模式
    bpy.ops.object.mode_set(mode=original_mode)

# --- 如何运行脚本 ---
# 1. 在3D视图中，选择你的网格对象。
# 2. 进入“编辑模式”（Tab键）。
# 3. 选择你想要修改的顶点。
# 4. 运行此脚本。

# 获取当前活跃对象
active_obj = bpy.context.active_object

# 调用函数
prune_vertex_groups(active_obj)