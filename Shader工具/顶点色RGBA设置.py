import bpy

def set_vertex_colors_based_on_groups(obj):
    # 确保对象是网格类型
    if obj.type != 'MESH':
        print("对象不是网格类型!")
        return

    # 进入顶点颜色绘制模式
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='VERTEX_PAINT')

    # 确保顶点颜色层存在
    if not obj.data.vertex_colors:
        obj.data.vertex_colors.new()

    color_layer = obj.data.vertex_colors.active

    # 定义顶点组到颜色通道的映射
    color_mapping = {
        'Red': 0,
        'Green': 1,
        'Blue': 2,
        'Alpha': 3
    }

    # 获取有效的顶点组索引
    group_indices = {}
    for group_name, color_index in color_mapping.items():
        group = obj.vertex_groups.get(group_name)
        if group:
            group_indices[group_name] = group.index

    # 设置顶点颜色
    for poly in obj.data.polygons:
        for idx, loop_idx in enumerate(poly.loop_indices):
            vert_idx = poly.vertices[idx]
            vert = obj.data.vertices[vert_idx]
            color = list(color_layer.data[loop_idx].color)  # 使用现有颜色

            # 根据有效的顶点组设置颜色
            for group_name, group_idx in group_indices.items():
                color_index = color_mapping[group_name]
                for g in vert.groups:
                    if g.group == group_idx:
                        color[color_index] = g.weight
                        break

            # 应用颜色
            color_layer.data[loop_idx].color = color

    # 返回对象模式
    bpy.ops.object.mode_set(mode='OBJECT')
    print("顶点颜色更新完成。")

# 选择要处理的对象
selected_objs = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
for obj in selected_objs:
    set_vertex_colors_based_on_groups(obj)
