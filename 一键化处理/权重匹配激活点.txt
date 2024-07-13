import bpy
import bmesh

# 保存当前模式
original_mode = bpy.context.object.mode

# 确保是处于编辑模式
obj = bpy.context.object
if original_mode != 'EDIT':
    bpy.ops.object.mode_set(mode='EDIT')

bm = bmesh.from_edit_mesh(obj.data)
deform_layer = bm.verts.layers.deform.active  # 获取deform层

if deform_layer is None:
    print("No vertex groups found.")
else:
    # 获取激活顶点
    active_vert = bm.select_history.active if isinstance(bm.select_history.active, bmesh.types.BMVert) else None

    if active_vert:
        # 获取激活顶点的顶点组和权重
        active_weights = {group: weight for group, weight in active_vert[deform_layer].items()}

        # 遍历所有选中的顶点
        for vert in bm.verts:
            if vert.select and vert != active_vert:
                # 删除不一致的顶点组
                vert_groups = {group: weight for group, weight in vert[deform_layer].items()}
                groups_to_remove = [group for group in vert_groups if group not in active_weights]
                for group in groups_to_remove:
                    del vert[deform_layer][group]

                # 复制激活顶点的顶点组和权重到当前顶点
                for group, weight in active_weights.items():
                    vert[deform_layer][group] = weight

        # 更新网格
        bmesh.update_edit_mesh(obj.data)

# 恢复原始模式
bpy.ops.object.mode_set(mode=original_mode)
