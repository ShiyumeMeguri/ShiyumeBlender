import bpy
import bmesh
from mathutils import Vector

# --- 全局设置 ---
# 使用自定义属性来标记我们的同步对象，比仅靠名字更可靠
SYNC_SOURCE_PROP = "uv_sync_source_object"


def update_uv_shape_key(sync_obj):
    """
    核心更新函数：从源对象读取UV，并更新同步对象的形态键。
    
    参数:
    sync_obj (bpy.types.Object): 带有形态键的UVSync对象。
    """
    # 1. 安全地获取源对象
    source_name = sync_obj.get(SYNC_SOURCE_PROP)
    if not source_name or source_name not in bpy.data.objects:
        return
        
    source_obj = bpy.data.objects[source_name]
    
    # 2. 验证所需的数据是否存在
    uv_layer = source_obj.data.uv_layers.get("UVSync_UV")
    if not uv_layer:
        return
        
    if not sync_obj.data.shape_keys:
        return

    uv_shape_key = sync_obj.data.shape_keys.key_blocks.get("UVSync")
    basis_key = sync_obj.data.shape_keys.key_blocks.get("Basis")

    if not uv_shape_key or not basis_key:
        return

    # 3. 使用 bmesh 在内存中处理网格，以便安全地分割顶点
    bm = bmesh.new()
    bm.from_mesh(source_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    
    uv_bmesh_layer = bm.loops.layers.uv.get(uv_layer.name)
    if not uv_bmesh_layer:
        bm.free()
        return

    # --- 关键：基于UV连续性的边分割逻辑 ---
    edges_to_split = set()
    epsilon = 1e-6

    for edge in bm.edges:
        if edge.seam or not edge.is_manifold:
            edges_to_split.add(edge)
            continue
        
        if len(edge.link_loops) != 2:
            continue

        l1, l2 = edge.link_loops
        v1, v2 = edge.verts

        l1_uvs = {l.vert.index: l[uv_bmesh_layer].uv for l in l1.face.loops}
        l2_uvs = {l.vert.index: l[uv_bmesh_layer].uv for l in l2.face.loops}

        v1_uv_match = (l1_uvs.get(v1.index, Vector()) - l2_uvs.get(v1.index, Vector())).length < epsilon
        v2_uv_match = (l1_uvs.get(v2.index, Vector()) - l2_uvs.get(v2.index, Vector())).length < epsilon

        if not (v1_uv_match and v2_uv_match):
            edges_to_split.add(edge)

    if edges_to_split:
        try:
            bmesh.ops.split_edges(bm, edges=list(edges_to_split))
            bm.verts.ensure_lookup_table()
        except Exception as e:
            print(f"BMesh split_edges operation failed: {e}")
            bm.free()
            return
            
    # 创建 顶点索引 -> UV坐标 的映射
    vert_uv_map = {}
    for face in bm.faces:
        for loop in face.loops:
            vert_idx = loop.vert.index
            if vert_idx not in vert_uv_map:
                uv = loop[uv_bmesh_layer].uv
                vert_uv_map[vert_idx] = Vector((uv.x, uv.y, 0.0))
    bm.free()

    # --- 4. 安全地更新形态键坐标 ---
    num_verts = len(basis_key.data)
    final_coords_flat = [0.0] * num_verts * 3
    basis_key.data.foreach_get("co", final_coords_flat)
    
    for vert_idx, uv_co in vert_uv_map.items():
        if vert_idx < num_verts:
            base_index = vert_idx * 3
            final_coords_flat[base_index]     = uv_co.x
            final_coords_flat[base_index + 1] = uv_co.y
            final_coords_flat[base_index + 2] = uv_co.z

    uv_shape_key.data.foreach_set("co", final_coords_flat)
    sync_obj.data.update()


def frame_change_sync_handler(scene, depsgraph):
    """帧变化回调处理器，用于自动触发更新。"""
    for obj in scene.objects:
        if SYNC_SOURCE_PROP in obj:
            update_uv_shape_key(obj)


def register_handler():
    """注册处理器函数，如果尚未注册的话"""
    if frame_change_sync_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(frame_change_sync_handler)
    print("UV同步处理器已激活。")


def setup_uv_sync_for_selected():
    """主函数：为所有选中的对象设置UV同步。"""
    selected_objects = bpy.context.selected_objects
    if not selected_objects:
        print("错误：没有选择任何对象。")
        return

    for source_obj in selected_objects:
        if source_obj.type != 'MESH':
            continue

        if not source_obj.data.uv_layers.active:
            print(f"跳过：对象 '{source_obj.name}' 没有活动的UV贴图。")
            continue
        
        # --- 最小改动修正 ---
        # 仅在 'UVSync_UV' 不存在时才创建它
        if "UVSync_UV" not in source_obj.data.uv_layers:
            active_uv_name = source_obj.data.uv_layers.active.name
            new_uv_layer = source_obj.data.uv_layers.new(name="UVSync_UV")
            source_uv_data = [0.0] * len(source_obj.data.loops) * 2
            source_obj.data.uv_layers[active_uv_name].data.foreach_get("uv", source_uv_data)
            new_uv_layer.data.foreach_set("uv", source_uv_data)
            print(f"在 '{source_obj.name}' 上创建了新的 'UVSync_UV' 贴图。")
        else:
            print(f"在 '{source_obj.name}' 上找到并使用现有的 'UVSync_UV' 贴图。")
        # --- 修正结束 ---

        sync_obj_name = source_obj.name + "_UVSync"
        if sync_obj_name in bpy.data.objects:
            sync_obj = bpy.data.objects[sync_obj_name]
            if sync_obj.data != source_obj.data:
                sync_obj.data = source_obj.data
            print(f"已找到现有的同步对象 '{sync_obj_name}'。")
        else:
            sync_obj = bpy.data.objects.new(sync_obj_name, source_obj.data)
            bpy.context.collection.objects.link(sync_obj)
            sync_obj.matrix_world = source_obj.matrix_world
            print(f"创建了链接对象 '{sync_obj_name}'。")

        sync_obj[SYNC_SOURCE_PROP] = source_obj.name

        if not sync_obj.data.shape_keys:
            sync_obj.shape_key_add(name='Basis')
        
        if "UVSync" not in sync_obj.data.shape_keys.key_blocks:
            sync_obj.shape_key_add(name='UVSync')
            print(f"在 '{sync_obj.name}' 上创建了 'UVSync' 形态键。")
        
        sync_obj.data.shape_keys.key_blocks["UVSync"].value = 1.0
        
        update_uv_shape_key(sync_obj)

    register_handler()
    print("\n设置完成！请修改原始对象上的 'UVSync_UV' 贴图，并在时间轴上播放或移动帧来查看同步对象的更新。")


# --- 脚本执行入口 ---
if __name__ == "__main__":
    setup_uv_sync_for_selected()