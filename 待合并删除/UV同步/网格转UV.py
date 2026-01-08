import bpy
import bmesh
from mathutils import Vector

def create_uv_shape_key_mesh_robust():
    """
    创建一个新网格对象，该对象使用形态键(Shape Key)来在原始形态和UV投影视角之间转换。
    
    此方法经过了关键修正：它不再仅仅依赖“缝合边(Seams)”，而是通过检查每条边上
    UV坐标的实际连续性来决定是否分割。这确保了即便是没有被标记为缝合边的UV岛边界，
    或是完全重叠的UV岛（如纽扣的顶面和底面），也能被正确地分离开，从而完美地投影。
    """
    # 1. 获取并验证当前选中的对象
    source_obj = bpy.context.active_object
    if source_obj is None or source_obj.type != 'MESH':
        print("错误：请先选择一个网格对象。")
        # 在Blender脚本中，返回{'CANCELLED'}是标准的表示操作取消的方式
        return {'CANCELLED'}

    # 确保对象有UV贴图
    if not source_obj.data.uv_layers.active:
        print(f"错误：对象 '{source_obj.name}' 没有活动的UV贴图。")
        return {'CANCELLED'}

    # --- 核心步骤开始 ---

    # 2. 使用 bmesh 在内存中处理网格数据
    bm = bmesh.new()
    bm.from_mesh(source_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.active

    # 3. 【关键修正】找出所有UV不连续的边并分割它们
    # 这是最核心的改进。我们不再只依赖edge.seam。
    edges_to_split = set()
    epsilon = 1e-6  # 用于浮点数比较的微小容差

    for edge in bm.edges:
        # 如果边已经被标记为缝合边，直接加入待分割列表
        if edge.seam:
            edges_to_split.add(edge)
            continue
            
        # 如果边连接的面少于2个（边界边），通常它已经是UV边界，但split_edges对它无效。
        # 如果连接的面多于2个（非流形），情况复杂，直接分割以确保安全。
        if not edge.is_manifold:
            edges_to_split.add(edge)
            continue

        # 对于连接两个面的普通边，检查UV是否连续
        # 获取边连接的两个循环(loop)
        l1 = edge.link_loops[0]
        l2 = edge.link_loops[1]

        # 获取边的两个顶点
        v1, v2 = edge.verts

        # 为第一个面(l1.face)找到两个顶点的UV坐标
        l1_uvs = {}
        for l in l1.face.loops:
            l1_uvs[l.vert.index] = l[uv_layer].uv

        # 为第二个面(l2.face)找到两个顶点的UV坐标
        l2_uvs = {}
        for l in l2.face.loops:
            l2_uvs[l.vert.index] = l[uv_layer].uv

        # 比较两个面在v1和v2处的UV坐标是否相同
        # 如果任意一个顶点的UV坐标在两个面之间不匹配，则这条边是UV边界
        v1_uv_match = (l1_uvs[v1.index] - l2_uvs[v1.index]).length < epsilon
        v2_uv_match = (l1_uvs[v2.index] - l2_uvs[v2.index]).length < epsilon

        if not (v1_uv_match and v2_uv_match):
            edges_to_split.add(edge)

    # 执行分割操作
    if edges_to_split:
        bmesh.ops.split_edges(bm, edges=list(edges_to_split))

    # bmesh 更新内部索引
    bm.verts.ensure_lookup_table()

    # 4. 准备形态键数据 (此部分逻辑与之前相同，因为网格已经被正确分割)
    uv_coords_map = {}
    for face in bm.faces:
        for loop in face.loops:
            # 因为已经分割，一个顶点现在只对应一个UV坐标
            vert_index = loop.vert.index
            if vert_index not in uv_coords_map:
                uv = loop[uv_layer].uv
                uv_coords_map[vert_index] = Vector((uv.x, uv.y, 0.0))

    # --- 核心步骤结束 ---

    # 5. 创建新的网格数据和对象
    new_mesh_data = bpy.data.meshes.new(source_obj.name + "_UV_Shape")
    bm.to_mesh(new_mesh_data)
    bm.free()

    new_obj = bpy.data.objects.new(new_mesh_data.name, new_mesh_data)
    bpy.context.collection.objects.link(new_obj)

    # 6. 复制材质
    for material_slot in source_obj.material_slots:
        new_obj.data.materials.append(material_slot.material)

    # 7. 创建并填充形态键
    sk_basis = new_obj.shape_key_add(name='Basis', from_mix=False)
    sk_uv = new_obj.shape_key_add(name='UVSync', from_mix=False)

    for i, vert in enumerate(new_obj.data.vertices):
        if i in uv_coords_map:
            sk_uv.data[i].co = uv_coords_map[i]
        else:
            # 对于孤立的、没有面的顶点，保持其原始位置
            sk_uv.data[i].co = sk_basis.data[i].co

    # 8. 清理和收尾
    bpy.context.view_layer.objects.active = new_obj
    new_obj.select_set(True)
    source_obj.select_set(False)
    new_obj.data.shape_keys.key_blocks['UVSync'].value = 1.0
    
    print(f"成功创建了带有UV形态键的对象 '{new_obj.name}'，已修正重叠UV问题。")
    return new_obj

# --- 如何在Blender中运行此脚本 ---
# 1. 打开Blender，切换到 "Scripting" 工作区。
# 2. 粘贴此代码。
# 3. 在3D视图中，选择一个已展好UV的网格对象（例如一个有重叠UV的纽扣模型）。
# 4. 运行脚本 (Alt+P)。

# 执行函数
if __name__ == "__main__":
    create_uv_shape_key_mesh_robust()