import bpy
import bmesh
from mathutils import Vector

# 设置相邻顶点的最大距离阈值
distance_threshold = 0.001

# 确保Blender处于编辑模式
bpy.ops.object.mode_set(mode='EDIT')

# 获取活动物体的mesh数据
obj = bpy.context.edit_object
me = obj.data

# 创建一个bmesh实例来操作顶点
bm = bmesh.from_edit_mesh(me)

# 尝试找到名为"Edge"的顶点组
vertex_group_index = obj.vertex_groups.find("Edge")
if vertex_group_index == -1:
    print("未找到名为'Edge'的顶点组。")
    # 退出脚本
    bpy.ops.object.mode_set(mode='OBJECT')
    exit()

# 获取顶点组
vg = obj.vertex_groups[vertex_group_index]

# 用于存储将要移动的顶点及其目标位置的字典
vertex_move_targets = {}

# 定义一个函数来获取顶点在顶点组中的权重，如果顶点不在顶点组中，则返回0
def get_vertex_weight(vertex, group_index):
    for g in vertex.groups:
        if g.group == group_index:
            return g.weight
    return 0.0

# 遍历所有顶点对，检查距离并计算中点位置
for vert1 in bm.verts:
    for vert2 in bm.verts:
        if vert1 != vert2:
            # 检查两个顶点的权重是否都大于0.1
            weight1 = get_vertex_weight(obj.data.vertices[vert1.index], vertex_group_index)
            weight2 = get_vertex_weight(obj.data.vertices[vert2.index], vertex_group_index)
            if weight1 > 0.1 and weight2 > 0.1:
                distance = (vert1.co - vert2.co).length
                if distance < distance_threshold:
                    target_position = (vert1.co + vert2.co) * 0.5
                    vertex_move_targets[vert1] = target_position
                    vertex_move_targets[vert2] = target_position

# 移动顶点到目标位置
for vert, target in vertex_move_targets.items():
    vert.co = target

# 更新mesh数据并返回到对象模式
bmesh.update_edit_mesh(me)
bpy.ops.object.mode_set(mode='OBJECT')

print("顶点移动完成。")
