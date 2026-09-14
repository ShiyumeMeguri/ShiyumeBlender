"""网格的合并语义: 谁盖谁、什么必须保留。只有这一份实现, 拉取和推送共用。

共享的是几何 / 拓扑 / 权重 / 形态键的**形状**。
每个文件自己的形态键**值**不共享 —— 那是本文件的体型设定, 是视图状态不是内容。

顶点权重存的是"组下标 -> 权重", 组**名**存在物体上。所以换网格数据块的同时必须把
顶点组名表一起换成来源那一份, 否则权重会静默错位到别的骨头上。名表作为参数传进来,
是因为推送时中转文件里只有网格数据块 —— 连物体一起写会把骨架和那条几百万关键帧的
动作一并拖进去。
"""

import bpy


def swap_mesh(target_obj, incoming, source_groups):
    """把 incoming 这份网格装到 target_obj 上, 保留 target 自己的形态键值。

    incoming:       来源的网格数据块 (已经在本文件里)
    source_groups:  来源物体的顶点组名表
    返回 (总结, 提示列表)。
    """
    old = target_obj.data
    if incoming is old:
        return "%s: 来源和本地是同一份数据, 没动" % target_obj.name, []
    notes = []

    kept_values = ({k.name: (k.value, k.mute) for k in old.shape_keys.key_blocks}
                   if old.shape_keys else {})
    old_groups = [g.name for g in target_obj.vertex_groups]
    before_verts = len(old.vertices)
    old_name = old.name

    target_obj.data = incoming

    restored = 0
    if incoming.shape_keys:
        for block in incoming.shape_keys.key_blocks:
            if block.name in kept_values:
                block.value, block.mute = kept_values[block.name]
                restored += 1
            else:
                notes.append("新形态键 %s (本地原本没有, 用来源的值)" % block.name)
        for name in kept_values:
            if name not in incoming.shape_keys.key_blocks:
                notes.append("形态键 %s 在来源里已不存在, 本地也随之消失" % name)
    elif kept_values:
        notes.append("来源没有形态键, 本地原有的 %d 个随之消失" % len(kept_values))

    if list(source_groups) != old_groups:
        for group in list(target_obj.vertex_groups):
            target_obj.vertex_groups.remove(group)
        for name in source_groups:
            target_obj.vertex_groups.new(name=name)
        notes.append("顶点组名表已按来源重建 (%d -> %d); 权重存的是组下标, 不换名表会错位"
                     % (len(old_groups), len(source_groups)))

    incoming.name = old_name
    old.use_fake_user = False
    if old.users == 0:
        bpy.data.meshes.remove(old)

    summary = ("%s 顶点 %d -> %d, 保留 %d 个形态键值"
               % (target_obj.name, before_verts, len(incoming.vertices), restored))
    return summary, notes
