import bpy
import bmesh
from mathutils import Vector

# --- 全局设置 ---
SYNC_SOURCE_PROP = "uv_sync_source_object"

def split_mesh_by_uv_islands(obj, uv_map_name):
    """
    【已修正的函数】
    直接修改给定对象的网格，根据指定的UV贴图来分割UV孤岛。
    使用了正确的UV连续性判断逻辑。
    """
    # 确保在对象模式下操作
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table() # 确保面查询表也已建立

    uv_layer = bm.loops.layers.uv.get(uv_map_name)
    if not uv_layer:
        print(f"错误: 在 '{obj.name}' 上找不到名为 '{uv_map_name}' 的UV贴图，无法分割。")
        bm.free()
        return

    edges_to_split = set()
    epsilon = 1e-6  # 用于浮点数比较的容差

    for edge in bm.edges:
        # 对于已经是缝合边、非流形边或边界边，直接加入分割列表以确保分离
        # 边界边 (len(edge.link_loops) != 2) 本身就是断开的，split_edges 对其无效，所以主要判断 seam 和 is_manifold
        if edge.seam or not edge.is_manifold:
            edges_to_split.add(edge)
            continue
        
        # 对于连接两个面的普通边，检查UV是否连续
        if len(edge.link_loops) != 2:
            continue

        # --- 这是从代码B移植过来的正确逻辑 ---
        
        # 获取边连接的两个循环(loop)，每个loop都属于一个面
        loop1, loop2 = edge.link_loops
        
        # 获取边的两个顶点
        v1, v2 = edge.verts

        # 为第一个面(loop1所在的面)建立一个 {顶点索引: UV坐标} 的映射
        loop1_uvs = {}
        for l in loop1.face.loops:
            loop1_uvs[l.vert.index] = l[uv_layer].uv

        # 为第二个面(loop2所在的面)也建立这样的映射
        loop2_uvs = {}
        for l in loop2.face.loops:
            loop2_uvs[l.vert.index] = l[uv_layer].uv

        # 核心比较：
        # 检查顶点v1在两个面上的UV坐标是否匹配
        v1_uv_match = (loop1_uvs.get(v1.index) - loop2_uvs.get(v1.index)).length < epsilon
        # 检查顶点v2在两个面上的UV坐标是否匹配
        v2_uv_match = (loop1_uvs.get(v2.index) - loop2_uvs.get(v2.index)).length < epsilon

        # 如果任意一个顶点的UV坐标在两个面之间不匹配，则这条边是UV边界
        if not (v1_uv_match and v2_uv_match):
            edges_to_split.add(edge)
        
        # --- 正确逻辑结束 ---

    if edges_to_split:
        print(f"在 '{obj.name}' 上找到 {len(edges_to_split)} 条UV不连续的边，正在进行分割...")
        bmesh.ops.split_edges(bm, edges=list(edges_to_split))
        # 将修改后的网格数据写回原始对象
        bm.to_mesh(obj.data)
        obj.data.update()
        print("网格分割完成。")
    else:
        print(f"在 '{obj.name}' 上未找到需要分割的UV边。")

    bm.free()

def update_uv_shape_key(sync_obj):
    """
    【已简化】核心更新函数。
    由于网格拓扑已在设置时固定，此函数只负责读取UV并更新顶点位置。
    """
    source_name = sync_obj.get(SYNC_SOURCE_PROP)
    if not source_name or source_name not in bpy.data.objects: return
    source_obj = bpy.data.objects[source_name]
    
    uv_layer = source_obj.data.uv_layers.get("UVSync_UV")
    if not uv_layer: return
        
    if not sync_obj.data.shape_keys: return
    uv_shape_key = sync_obj.data.shape_keys.key_blocks.get("UVSync")
    if not uv_shape_key: return

    # 使用 mesh.loops 和 uv_layer.data 可以非常快速地访问数据，无需bmesh
    num_loops = len(source_obj.data.loops)
    uv_coords = [0.0] * num_loops * 2
    uv_layer.data.foreach_get("uv", uv_coords)

    loop_vert_indices = [0] * num_loops
    source_obj.data.loops.foreach_get("vertex_index", loop_vert_indices)

    # 获取形态键数据以便快速写入
    num_verts = len(uv_shape_key.data)
    shape_key_coords = [0.0] * num_verts * 3
    # 这里我们直接用顶点的原始坐标作为基础，而不是读形态键，这样更稳定
    sync_obj.data.vertices.foreach_get("co", shape_key_coords)


    # 建立一个标志位，确保每个顶点只被赋值一次
    # 因为网格已经按UV孤岛分割，同一个顶点的不同loop现在是不同的顶点了，
    # 所以这个标志位不再是绝对必须的，但保留也无害。
    updated_verts = [False] * num_verts
    
    for i in range(num_loops):
        vert_idx = loop_vert_indices[i]
        if not updated_verts[vert_idx]:
            uv_x = uv_coords[i * 2]
            uv_y = uv_coords[i * 2 + 1]
            
            base_index = vert_idx * 3
            shape_key_coords[base_index] = uv_x
            shape_key_coords[base_index + 1] = uv_y
            shape_key_coords[base_index + 2] = 0.0 # Z轴为0
            
            updated_verts[vert_idx] = True
            
    # 一次性将所有坐标写回形态键
    uv_shape_key.data.foreach_set("co", shape_key_coords)
    sync_obj.data.update()

def frame_change_sync_handler(scene, depsgraph):
    for obj in scene.objects:
        if SYNC_SOURCE_PROP in obj:
            # 检查对象是否在当前视图层中可见，避免不必要的更新
            if obj.name in depsgraph.ids:
                 update_uv_shape_key(obj)

def register_handler():
    # 避免重复注册
    if frame_change_sync_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(frame_change_sync_handler)
    print("UV同步处理器已激活。")

def setup_uv_sync_for_selected():
    """
    【主函数】
    先直接修改原始网格，然后再创建链接到此网格的同步对象。
    """
    selected_objects = bpy.context.selected_objects
    if not selected_objects:
        print("错误：没有选择任何对象。")
        return

    for source_obj in selected_objects:
        if source_obj.type != 'MESH': continue
        
        # 确保对象有活动的UV层，否则无法继续
        active_uv = source_obj.data.uv_layers.active
        if not active_uv:
            print(f"跳过：对象 '{source_obj.name}' 没有活动的UV贴图。")
            continue
        
        uv_map_name = "UVSync_UV"
        # 如果名为"UVSync_UV"的UV图层不存在，则复制当前激活的UV层并重命名
        if uv_map_name not in source_obj.data.uv_layers:
            new_uv_layer = source_obj.data.uv_layers.new(name=uv_map_name)
            new_uv_layer.data.foreach_set('uv', [uv for co in active_uv.data for uv in co.uv])
            print(f"在 '{source_obj.name}' 上，已将当前激活的UV复制到新的 '{uv_map_name}' 贴图。")

        # --- 核心修正点 1：在一切开始之前，直接修改原始网格 ---
        print(f"--- 正在处理: {source_obj.name} ---")
        split_mesh_by_uv_islands(source_obj, uv_map_name)
        
        sync_obj_name = source_obj.name + "_UVSync"
        
        # --- 核心修正点 2：不创建副本，直接链接修改后的原始网格 ---
        if sync_obj_name in bpy.data.objects:
            sync_obj = bpy.data.objects[sync_obj_name]
            if sync_obj.data != source_obj.data:
                sync_obj.data = source_obj.data # 确保链接的是同一个数据块
            print(f"已找到现有的同步对象 '{sync_obj_name}' 并重新链接网格。")
        else:
            # 创建新对象时，链接到源对象的数据块(source_obj.data)
            sync_obj = bpy.data.objects.new(sync_obj_name, source_obj.data)
            bpy.context.collection.objects.link(sync_obj)
            print(f"创建了链接对象 '{sync_obj_name}'。")

        sync_obj.matrix_world = source_obj.matrix_world
        sync_obj[SYNC_SOURCE_PROP] = source_obj.name
        
        # --- 设置形态键 (现在是在一个拓扑稳定的网格上操作) ---
        if not sync_obj.data.shape_keys:
            sync_obj.shape_key_add(name='Basis')
        
        if "UVSync" in sync_obj.data.shape_keys.key_blocks:
            uv_key = sync_obj.data.shape_keys.key_blocks["UVSync"]
            sync_obj.shape_key_remove(uv_key)

        uv_shape = sync_obj.shape_key_add(name='UVSync')
        print(f"在 '{sync_obj.name}' 上创建了 'UVSync' 形态键。")
        
        sync_obj.active_shape_key_index = sync_obj.data.shape_keys.key_blocks.keys().index("UVSync")
        uv_shape.value = 1.0
        
        # 触发一次立即更新来填充形态键
        update_uv_shape_key(sync_obj)

    register_handler()
    print("\n设置完成！原始网格已被修改。请修改 'UVSync_UV' 贴图并切换帧来查看同步更新。")


if __name__ == "__main__":
    setup_uv_sync_for_selected()