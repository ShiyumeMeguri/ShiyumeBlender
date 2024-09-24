import bpy
import bmesh
from mathutils import Vector

def create_face_with_custom_normals(bm, pos, normal, size):
    """
    使用给定的自定义法线在指定位置创建一个朝向对齐的正方形面片。
    """
    if abs(normal.z) == 1:
        right = Vector((1, 0, 0))
    else:
        right = Vector((0, 0, 1)).cross(normal).normalized()
    up = normal.cross(right).normalized()

    half_size = size / 2
    quad_corners = [
        pos + right * half_size + up * half_size,
        pos - right * half_size + up * half_size,
        pos - right * half_size - up * half_size,
        pos + right * half_size - up * half_size,
    ]

    verts = [bm.verts.new(corner) for corner in quad_corners]
    bm.faces.new(verts)

def generate_faces_from_custom_normals(obj, size=0.1):
    """
    基于对象顶点的自定义法线生成正方形面片。
    """
    if obj.type != 'MESH':
        return

    bm = bmesh.new()


    # 为每个顶点的每个循环创建面片，使用自定义法线
    for poly in obj.data.polygons:
        for idx in poly.loop_indices:
            loop = obj.data.loops[idx]
            vert = obj.data.vertices[loop.vertex_index]
            pos = vert.co
            normal = loop.normal  # 使用循环的法线作为自定义法线

            create_face_with_custom_normals(bm, pos, normal, size)

    # 生成新的网格数据和对象
    new_mesh_data = bpy.data.meshes.new(obj.name + "_custom_normals_mesh")
    bm.to_mesh(new_mesh_data)
    new_mesh_obj = bpy.data.objects.new(obj.name + "_custom_normals", new_mesh_data)

    bpy.context.collection.objects.link(new_mesh_obj)

    bm.free()

# 获取当前激活的对象
active_obj = bpy.context.active_object

if active_obj:
    generate_faces_from_custom_normals(active_obj, 0.1)
else:
    print("No active object selected.")
