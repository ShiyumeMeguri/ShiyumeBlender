import bpy
import bmesh
from mathutils import Matrix

def ensure_object_mode():
    if bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

def ensure_edit_mode(obj):
    ensure_object_mode()
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')

def apply_new_normals_with_point_normals(obj, distance):
    # 确保对象的类型是网格
    if obj.type != 'MESH':
        return
    
    # 复制对象
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    bpy.context.collection.objects.link(new_obj)
    
    # 在对象模式下修改新对象的顶点位置
    ensure_object_mode()
    bpy.context.view_layer.objects.active = new_obj
    bpy.ops.object.mode_set(mode='EDIT')
    bm_new = bmesh.from_edit_mesh(new_obj.data)

    # 修改顶点在局部坐标中的位置
    for v in bm_new.verts:
        v.co += v.normal * distance

    bmesh.update_edit_mesh(new_obj.data)
    bpy.ops.object.mode_set(mode='OBJECT')

    # 为原始模型的每个顶点设置新的法线
    ensure_edit_mode(obj)
    bm_orig = bmesh.from_edit_mesh(obj.data)
    bm_orig.verts.ensure_lookup_table()

    for i, v_orig in enumerate(bm_orig.verts):
        bpy.ops.mesh.select_all(action='DESELECT')
        bm_orig.verts[i].select = True
        bmesh.update_edit_mesh(obj.data)
        
        # 使用全局坐标设置新的法线方向
        global_new_co = new_obj.matrix_world @ new_obj.data.vertices[i].co
        bpy.ops.mesh.point_normals(target_location=global_new_co)

    bpy.ops.object.mode_set(mode='OBJECT')

    # 删除临时扩展的网格
    ensure_object_mode()
    bpy.data.objects.remove(new_obj)

# 设置扩展的距离
expand_distance = 0.001 

# 记录已经处理过的网格数据
processed_meshes = set()

# 遍历所有选中的对象
for obj in bpy.context.selected_objects:
    mesh_data = obj.data
    if mesh_data not in processed_meshes:
        apply_new_normals_with_point_normals(obj, expand_distance)
        processed_meshes.add(mesh_data)

print("操作完成，已更新原始模型的顶点法线，并删除了临时网格。")
