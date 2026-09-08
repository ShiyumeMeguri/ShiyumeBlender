"""UV 孤岛查询。UV 编辑器里的所有算子共用这一份孤岛与选中判定。"""

from collections import namedtuple

from bpy_extras import bmesh_utils


SelectedIsland = namedtuple("SelectedIsland", ("faces", "selected_faces"))


def face_selected_test(bm, tool_settings):
    """返回 Blender 自己判定"这个面在 UV 编辑器里被选中"所用的规则。"""
    if tool_settings.use_uv_select_sync:
        if bm.uv_select_sync_valid:
            return lambda face: not face.hide and face.uv_select
        return lambda face: not face.hide and face.select
    return lambda face: not face.hide and face.select and face.uv_select


def collect_islands(bm, uv_layer):
    return bmesh_utils.bmesh_linked_uv_islands(bm, uv_layer)


def collect_selected_islands(bm, uv_layer, tool_settings):
    is_selected = face_selected_test(bm, tool_settings)
    islands = []
    for faces in collect_islands(bm, uv_layer):
        selected_faces = [face for face in faces if is_selected(face)]
        if selected_faces:
            islands.append(SelectedIsland(faces, selected_faces))
    return islands


def bounds(faces, uv_layer):
    """返回 (min_u, min_v, max_u, max_v)。"""
    min_u = min_v = float("inf")
    max_u = max_v = float("-inf")
    for face in faces:
        for loop in face.loops:
            u, v = loop[uv_layer].uv
            min_u = min(min_u, u)
            min_v = min(min_v, v)
            max_u = max(max_u, u)
            max_v = max(max_v, v)
    return min_u, min_v, max_u, max_v


def loops(faces):
    for face in faces:
        for loop in face.loops:
            yield loop


def select_faces(faces):
    """把面重新标成选中，网格选择与 UV 选择两份状态都要写。"""
    for face in faces:
        if not face.is_valid:
            continue
        face.select_set(True)
        face.uv_select_set(True)
