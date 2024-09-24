'''
blender script
在blender v2.92中成功使用

功能：
删除活动物体的空顶点组

空的顶点组代表着 一个顶点组
不包含任意顶点
或
顶点组内全部顶点的权重均小于等于0
'''

print(f'Start {__file__}')

import bpy

def check_each_vertex_group_max_weight(obj):
    gid_to_maxw = {}
    # 让统计字典内的顶点组的初始值为0
    for g in obj.vertex_groups:
        gid_to_maxw[g.index] = 0
        
    # 循环网格体的每一个顶点，统计每个顶点组的最大权重
    for v in obj.data.vertices:
        for g in v.groups:
            gid = g.group
            w = obj.vertex_groups[gid].weight(v.index)
            if (gid_to_maxw.get(gid) is None or w>gid_to_maxw[gid]):
                gid_to_maxw[gid] = w
    return gid_to_maxw

# 获得活动对象
obj = bpy.context.active_object

# 获得活动对象的 每个顶点组到最大权重的字典
gid_to_maxw = check_each_vertex_group_max_weight(obj)

# 让字典的值按大到小排序，这是为了从大到小逐个删除时，删除序号大的不会影响序号小。
wait_to_del_gids = []
for gid, maxw in gid_to_maxw.items():
    if maxw <= 0:
        wait_to_del_gids.append(gid)

# 让顶点组编号从大到小排序，这先删除编号大的不会对编号小的造成影响
wait_to_del_gids = sorted(wait_to_del_gids)[::-1]

print(f'Delete vertex group index list {wait_to_del_gids}')

# 逐个删除空顶点组
for gid in wait_to_del_gids:
    obj.vertex_groups.remove(obj.vertex_groups[gid])

print('Success')