import bpy
import bmesh

SYNC_SOURCE_PROP = "uv_sync_source_object"


def split_mesh_by_uv_islands(obj, uv_map_name):
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.get(uv_map_name)
    if not uv_layer:
        print(f"错误: 在 '{obj.name}' 上找不到名为 '{uv_map_name}' 的UV贴图，无法分割。")
        bm.free()
        return

    edges_to_split = set()
    epsilon = 1e-6

    for edge in bm.edges:
        if edge.seam or not edge.is_manifold:
            edges_to_split.add(edge)
            continue

        if len(edge.link_loops) != 2:
            continue

        loop1, loop2 = edge.link_loops

        v1, v2 = edge.verts

        loop1_uvs = {}
        for l in loop1.face.loops:
            loop1_uvs[l.vert.index] = l[uv_layer].uv

        loop2_uvs = {}
        for l in loop2.face.loops:
            loop2_uvs[l.vert.index] = l[uv_layer].uv

        v1_uv_match = (loop1_uvs.get(v1.index) - loop2_uvs.get(v1.index)).length < epsilon
        v2_uv_match = (loop1_uvs.get(v2.index) - loop2_uvs.get(v2.index)).length < epsilon

        if not (v1_uv_match and v2_uv_match):
            edges_to_split.add(edge)

    if edges_to_split:
        print(f"在 '{obj.name}' 上找到 {len(edges_to_split)} 条UV不连续的边，正在进行分割...")
        bmesh.ops.split_edges(bm, edges=list(edges_to_split))
        bm.to_mesh(obj.data)
        obj.data.update()
        print("网格分割完成。")
    else:
        print(f"在 '{obj.name}' 上未找到需要分割的UV边。")

    bm.free()


def update_uv_shape_key(sync_obj):
    source_name = sync_obj.get(SYNC_SOURCE_PROP)
    if not source_name or source_name not in bpy.data.objects:
        return
    source_obj = bpy.data.objects[source_name]

    uv_layer = source_obj.data.uv_layers.get("UVSync_UV")
    if not uv_layer:
        return

    if not sync_obj.data.shape_keys:
        return
    uv_shape_key = sync_obj.data.shape_keys.key_blocks.get("UVSync")
    if not uv_shape_key:
        return

    num_loops = len(source_obj.data.loops)
    uv_coords = [0.0] * num_loops * 2
    uv_layer.data.foreach_get("uv", uv_coords)

    loop_vert_indices = [0] * num_loops
    source_obj.data.loops.foreach_get("vertex_index", loop_vert_indices)

    num_verts = len(uv_shape_key.data)
    shape_key_coords = [0.0] * num_verts * 3
    sync_obj.data.vertices.foreach_get("co", shape_key_coords)

    updated_verts = [False] * num_verts

    for i in range(num_loops):
        vert_idx = loop_vert_indices[i]
        if not updated_verts[vert_idx]:
            uv_x = uv_coords[i * 2]
            uv_y = uv_coords[i * 2 + 1]

            base_index = vert_idx * 3
            shape_key_coords[base_index] = uv_x
            shape_key_coords[base_index + 1] = uv_y
            shape_key_coords[base_index + 2] = 0.0

            updated_verts[vert_idx] = True

    uv_shape_key.data.foreach_set("co", shape_key_coords)
    sync_obj.data.update()


def frame_change_sync_handler(scene, depsgraph):
    for obj in scene.objects:
        if SYNC_SOURCE_PROP in obj:
            if obj.name in depsgraph.ids:
                update_uv_shape_key(obj)


def register_handler():
    if frame_change_sync_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(frame_change_sync_handler)
    print("UV同步处理器已激活。")


def unregister_handler():
    if frame_change_sync_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(frame_change_sync_handler)


class SHIYUME_OT_MeshUVSyncLive(bpy.types.Operator):
    """实时UV同步：把选中网格按UV孤岛拆分（直接改原网格！），并创建链接的 _UVSync 副本与 'UVSync' 形态键。
    形态键会在帧变化时跟随 UV 实时更新。注意：此操作会修改原网格的拓扑（按UV缝拆分），不可逆。"""
    bl_idname = "shiyume.mesh_uv_sync_live"
    bl_label = "网格UV同步 (实时)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, "没有选择任何对象。")
            return {'CANCELLED'}

        for source_obj in selected_objects:
            if source_obj.type != 'MESH':
                continue

            active_uv = source_obj.data.uv_layers.active
            if not active_uv:
                print(f"跳过：对象 '{source_obj.name}' 没有活动的UV贴图。")
                continue

            uv_map_name = "UVSync_UV"
            if uv_map_name not in source_obj.data.uv_layers:
                new_uv_layer = source_obj.data.uv_layers.new(name=uv_map_name)
                new_uv_layer.data.foreach_set('uv', [uv for co in active_uv.data for uv in co.uv])
                print(f"在 '{source_obj.name}' 上，已将当前激活的UV复制到新的 '{uv_map_name}' 贴图。")

            print(f"--- 正在处理: {source_obj.name} ---")
            split_mesh_by_uv_islands(source_obj, uv_map_name)

            sync_obj_name = source_obj.name + "_UVSync"

            if sync_obj_name in bpy.data.objects:
                sync_obj = bpy.data.objects[sync_obj_name]
                if sync_obj.data != source_obj.data:
                    sync_obj.data = source_obj.data
                print(f"已找到现有的同步对象 '{sync_obj_name}' 并重新链接网格。")
            else:
                sync_obj = bpy.data.objects.new(sync_obj_name, source_obj.data)
                context.collection.objects.link(sync_obj)
                print(f"创建了链接对象 '{sync_obj_name}'。")

            sync_obj.matrix_world = source_obj.matrix_world
            sync_obj[SYNC_SOURCE_PROP] = source_obj.name

            if not sync_obj.data.shape_keys:
                sync_obj.shape_key_add(name='Basis')

            if "UVSync" in sync_obj.data.shape_keys.key_blocks:
                uv_key = sync_obj.data.shape_keys.key_blocks["UVSync"]
                sync_obj.shape_key_remove(uv_key)

            uv_shape = sync_obj.shape_key_add(name='UVSync')
            print(f"在 '{sync_obj.name}' 上创建了 'UVSync' 形态键。")

            sync_obj.active_shape_key_index = sync_obj.data.shape_keys.key_blocks.keys().index("UVSync")
            uv_shape.value = 1.0

            update_uv_shape_key(sync_obj)

        register_handler()
        self.report({'INFO'}, "实时UV同步已激活，原网格已被分割。")
        return {'FINISHED'}


class SHIYUME_OT_MeshUVSyncLiveDisable(bpy.types.Operator):
    """关闭实时 UV 同步处理器（仍保留已创建的 _UVSync 对象与形态键）"""
    bl_idname = "shiyume.mesh_uv_sync_live_disable"
    bl_label = "关闭UV同步处理器"
    bl_options = {'REGISTER'}

    def execute(self, context):
        unregister_handler()
        self.report({'INFO'}, "UV同步处理器已停用")
        return {'FINISHED'}
