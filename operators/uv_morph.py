"""网格 ↔ UV 同步:一个算子三种模式(原地形态键 / 拆分副本 / 实时联动)。

约定统一使用 "UVSync" 形态键名,可与"参考拓扑重建"直接衔接。
"""

import bmesh
import bpy
import numpy as np

from ..core import batch, compat, uv_split

SYNC_SOURCE_PROP = "uv_sync_source_object"
LIVE_UV_NAME = "UVSync_UV"


# ---------------------------------------------------------------------------
# 实时联动:形态键跟随 UV 的帧变化处理器
# ---------------------------------------------------------------------------

def _update_uv_shape_key(sync_obj):
    """把源物体 UVSync_UV 的坐标写进联动物体的 UVSync 形态键(每顶点取首条 loop)。"""
    source_name = sync_obj.get(SYNC_SOURCE_PROP)
    if not source_name or source_name not in bpy.data.objects:
        return
    source_obj = bpy.data.objects[source_name]

    uv_layer = source_obj.data.uv_layers.get(LIVE_UV_NAME)
    if uv_layer is None:
        return
    shape_keys = sync_obj.data.shape_keys
    if shape_keys is None:
        return
    uv_shape_key = shape_keys.key_blocks.get("UVSync")
    if uv_shape_key is None:
        return

    mesh = source_obj.data
    loop_vertex = batch.read_int(mesh.loops, "vertex_index")
    uvs = batch.read_uvs(mesh, uv_layer)

    vertex_count = len(uv_shape_key.data)
    coordinates = batch.read_float(sync_obj.data.vertices, "co", 3)
    uv_positions = np.zeros((len(uvs), 3), dtype=np.float32)
    uv_positions[:, :2] = uvs
    batch.scatter_first_loop(vertex_count, loop_vertex, uv_positions, out=coordinates)

    batch.write_float(uv_shape_key.data, "co", coordinates)
    sync_obj.data.update()


def _frame_change_sync(scene, depsgraph):
    for obj in scene.objects:
        if SYNC_SOURCE_PROP in obj:
            if obj.name in depsgraph.ids:
                _update_uv_shape_key(obj)


def register_live_handler():
    if _frame_change_sync not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_frame_change_sync)


def unregister_live_handler():
    if _frame_change_sync in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_frame_change_sync)


# ---------------------------------------------------------------------------
# 主算子
# ---------------------------------------------------------------------------

class SHIYUME_OT_MeshUVMorph(bpy.types.Operator):
    """网格与 UV 布局互看的三种同步方式:
    原地形态键 —— 在原网格上加形态键把顶点摆到 UV 位置(不拆缝,最轻量);
    拆分副本 —— 复制网格并按 UV 缝拆边,重建全部形态键再追加 UVSync 键(原网格不动);
    实时联动 —— 按 UV 缝拆分原网格(不可逆!)并创建链接副本,帧变化时形态键跟随 UV 更新"""
    bl_idname = "shiyume.mesh_uv_morph"
    bl_label = "网格UV同步"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="模式",
        items=[
            ('SHAPEKEY', "原地形态键", "在原网格上添加形态键;共享顶点跨 UV 岛时取首条 loop 的坐标"),
            ('COPY', "拆分副本", "复制网格并按 UV 缝拆边,顶点与 UV 一一对应;保留并重建全部形态键"),
            ('LIVE', "实时联动", "拆分原网格并创建链接副本,UV 改动随帧变化实时同步到形态键"),
        ],
        default='COPY',
    )
    shape_key_name: bpy.props.StringProperty(
        name="形态键名", default="UVSync",
        description="UV 位置形态键的名字('参考拓扑重建'默认读取 UVSync)",
    )

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "mode")
        layout.prop(self, "shape_key_name")
        if self.mode == 'LIVE':
            layout.label(text="将按 UV 缝拆分原网格,不可逆", icon='ERROR')

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        created = []
        processed = 0

        for obj in meshes:
            if obj.data.uv_layers.active is None:
                self.report({'WARNING'}, f"'{obj.name}' 没有激活 UV,跳过")
                continue
            if self.mode == 'SHAPEKEY':
                self._morph_in_place(obj)
                processed += 1
            elif self.mode == 'COPY':
                new_obj = self._build_split_copy(context, obj)
                if new_obj:
                    created.append(new_obj)
                    processed += 1
            else:
                self._setup_live(context, obj)
                processed += 1

        if processed == 0:
            return {'CANCELLED'}

        if self.mode == 'COPY' and created:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in created:
                obj.select_set(True)
            context.view_layer.objects.active = created[-1]
        elif self.mode == 'LIVE':
            register_live_handler()

        self.report({'INFO'}, f"已同步 {processed} 个网格({self.mode})")
        return {'FINISHED'}

    # ------------------------------------------------------------------
    # 模式一:原地形态键
    # ------------------------------------------------------------------

    def _morph_in_place(self, obj):
        mesh = obj.data
        if not mesh.shape_keys:
            obj.shape_key_add(name="Basis")

        shape_key = mesh.shape_keys.key_blocks.get(self.shape_key_name)
        if shape_key is None:
            shape_key = obj.shape_key_add(name=self.shape_key_name, from_mix=False)

        loop_vertex = batch.read_int(mesh.loops, "vertex_index")
        uvs = batch.read_uvs(mesh)
        uv_positions = np.zeros((len(uvs), 3), dtype=np.float32)
        uv_positions[:, :2] = uvs

        # 没有 loop 的孤立顶点保持原位
        coordinates = batch.read_float(mesh.vertices, "co", 3)
        batch.scatter_first_loop(len(mesh.vertices), loop_vertex, uv_positions, out=coordinates)

        batch.write_float(shape_key.data, "co", coordinates)
        shape_key.value = 1.0
        mesh.update()

    # ------------------------------------------------------------------
    # 模式二:拆分副本
    # ------------------------------------------------------------------

    def _build_split_copy(self, context, source_obj):
        source_shape_keys = source_obj.data.shape_keys

        new_mesh = source_obj.data.copy()
        new_mesh.name = source_obj.data.name + "_UV_Shape"
        new_obj = bpy.data.objects.new(source_obj.name + "_UV_Shape", new_mesh)
        context.collection.objects.link(new_obj)

        # UV 不连续边检测(NumPy)→ bmesh 拆分,同时用整型层记录每个新顶点的源顶点号
        split_edge_indices = uv_split.uv_discontinuous_edge_indices(new_mesh)

        working = bmesh.new()
        working.from_mesh(new_mesh)
        working.verts.ensure_lookup_table()
        working.edges.ensure_lookup_table()

        source_index_layer = working.verts.layers.int.new("_source_vert_index")
        for vertex in working.verts:
            vertex[source_index_layer] = vertex.index

        if len(split_edge_indices):
            edges = [working.edges[int(index)] for index in split_edge_indices]
            bmesh.ops.split_edges(working, edges=edges)

        # 写回拆分拓扑会作废复制来的形态键,先清掉,随后按源顶点映射重建
        if new_obj.data.shape_keys:
            new_obj.shape_key_clear()
        working.to_mesh(new_mesh)
        new_mesh.update()
        working.free()

        # 源顶点映射:拆分产生的新顶点继承整型层的源顶点号
        map_attribute = new_mesh.attributes.get("_source_vert_index")
        source_map = np.empty(len(new_mesh.vertices), dtype=np.int32)
        map_attribute.data.foreach_get("value", source_map)
        new_mesh.attributes.remove(map_attribute)

        # 重建源形态键:整块 gather,零逐点循环
        if source_shape_keys:
            for key_block in source_shape_keys.key_blocks:
                source_points = batch.read_float(key_block.data, "co", 3)
                new_key = new_obj.shape_key_add(name=key_block.name, from_mix=False)
                batch.write_float(new_key.data, "co", source_points[source_map])
        else:
            new_obj.shape_key_add(name="Basis", from_mix=False)

        # UVSync 键:顶点摆到 UV 位置;无 loop 的顶点回落到 basis
        uv_shape_key = new_mesh.shape_keys.key_blocks.get(self.shape_key_name)
        if uv_shape_key is None:
            uv_shape_key = new_obj.shape_key_add(name=self.shape_key_name, from_mix=False)

        basis_key = new_mesh.shape_keys.key_blocks[0]
        coordinates = batch.read_float(basis_key.data, "co", 3)
        loop_vertex = batch.read_int(new_mesh.loops, "vertex_index")
        uvs = batch.read_uvs(new_mesh)
        uv_positions = np.zeros((len(uvs), 3), dtype=np.float32)
        uv_positions[:, :2] = uvs
        batch.scatter_first_loop(len(new_mesh.vertices), loop_vertex, uv_positions, out=coordinates)
        batch.write_float(uv_shape_key.data, "co", coordinates)

        if source_shape_keys:
            compat.copy_shape_key_settings(source_shape_keys, new_obj)

        uv_shape_key.value = 1.0
        return new_obj

    # ------------------------------------------------------------------
    # 模式三:实时联动
    # ------------------------------------------------------------------

    def _setup_live(self, context, source_obj):
        mesh = source_obj.data

        # 把当前激活 UV 固化成专用联动层
        if LIVE_UV_NAME not in mesh.uv_layers:
            active_uv = mesh.uv_layers.active
            new_layer = mesh.uv_layers.new(name=LIVE_UV_NAME, do_init=False)
            batch.write_float(new_layer.data, "uv", batch.read_uvs(mesh, active_uv))

        # 按联动层的 UV 缝拆分原网格(不可逆)
        split_edge_indices = uv_split.uv_discontinuous_edge_indices(mesh, uv_name=LIVE_UV_NAME)
        uv_split.split_mesh_edges(mesh, split_edge_indices)

        # 建立/复用共享同一网格数据的联动物体
        sync_name = source_obj.name + "_UVSync"
        sync_obj = bpy.data.objects.get(sync_name)
        if sync_obj is not None:
            if sync_obj.data != mesh:
                sync_obj.data = mesh
        else:
            sync_obj = bpy.data.objects.new(sync_name, mesh)
            context.collection.objects.link(sync_obj)

        sync_obj.matrix_world = source_obj.matrix_world
        sync_obj[SYNC_SOURCE_PROP] = source_obj.name

        if not mesh.shape_keys:
            sync_obj.shape_key_add(name='Basis')
        existing = mesh.shape_keys.key_blocks.get("UVSync")
        if existing is not None:
            sync_obj.shape_key_remove(existing)

        uv_shape_key = sync_obj.shape_key_add(name='UVSync')
        sync_obj.active_shape_key_index = mesh.shape_keys.key_blocks.keys().index("UVSync")
        uv_shape_key.value = 1.0

        _update_uv_shape_key(sync_obj)


class SHIYUME_OT_MeshUVMorphStop(bpy.types.Operator):
    """停止实时 UV 联动处理器(已创建的 _UVSync 物体与形态键保留)"""
    bl_idname = "shiyume.mesh_uv_morph_stop"
    bl_label = "停止UV实时联动"
    bl_options = {'REGISTER'}

    def execute(self, context):
        unregister_live_handler()
        self.report({'INFO'}, "UV 实时联动处理器已停用")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_MeshUVMorph,
    SHIYUME_OT_MeshUVMorphStop,
)
