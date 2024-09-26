import bpy

def prune_vertex_groups(obj, max_groups=4, min_weight=0.01):
    # 记录原始模式
    original_mode = bpy.context.object.mode
    # 确保对象处于对象模式
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # 获取骨骼的名称列表
    bone_names = set(bone.name for bone in obj.parent.data.bones) if obj.parent and obj.parent.type == 'ARMATURE' else set()

    # 对每个选中的顶点进行操作
    for v in [v for v in obj.data.vertices if v.select]:
        # 获取顶点相关的顶点组及其权重，并过滤掉不匹配任何骨骼的顶点组
        group_weights = [(group.group, group.weight) for group in v.groups if obj.vertex_groups[group.group].name in bone_names]

        # 先移除所有权重小于最小值的顶点组
        for group, weight in group_weights:
            if weight < min_weight:
                obj.vertex_groups[group].remove([v.index])
        
        # 重新获取顶点组及其权重，因为可能有变化
        group_weights = [(group.group, group.weight) for group in v.groups if obj.vertex_groups[group.group].name in bone_names and group.weight >= min_weight]
        # 排序权重，由低到高
        group_weights.sort(key=lambda x: x[1])
        
        # 如果顶点组数量仍超过最大允许值，则删除最低的权重组
        while len(group_weights) > max_groups:
            # 删除最低权重组
            group_to_remove = group_weights.pop(0)
            obj.vertex_groups[group_to_remove[0]].remove([v.index])
    
    # 恢复到原始模式
    bpy.ops.object.mode_set(mode=original_mode)

# 获取当前活跃对象
active_obj = bpy.context.active_object

# 调用函数
prune_vertex_groups(active_obj)
