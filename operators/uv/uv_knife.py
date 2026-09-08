"""在 UV 平面上沿折线切割网格面。

内核只认两样东西：一组要切的面，一组写在 UV 坐标里的折线。
切割位置由折线与面在 UV 平面上的交点决定，新顶点的三维位置由该面的
UV→位置映射插值得到，其余循环数据交给 bmesh 自己插值。
"""

from collections import deque

import bmesh
from mathutils import Vector
from mathutils.geometry import barycentric_transform


PARALLEL_DENOMINATOR = 1e-12


class Crossing:
    """折线穿过某个面的边界时留下的一个点。"""

    __slots__ = ("distance", "point", "vert", "loop", "factor")

    def __init__(self, distance, point, vert=None, loop=None, factor=0.0):
        self.distance = distance
        self.point = point
        self.vert = vert
        self.loop = loop
        self.factor = factor


def cut_faces(bm, uv_layer, faces, polylines, tolerance):
    """沿 polylines 切割 faces，返回切完之后的面集合。"""
    work_faces = set(faces)
    for polyline in polylines:
        if len(polyline) < 2:
            continue
        line_bounds = _polyline_bounds(polyline)
        pending = deque(work_faces)
        while pending:
            face = pending.popleft()
            if not face.is_valid:
                continue
            if not _bounds_overlap(line_bounds,
                                   _face_bounds(face, uv_layer), tolerance):
                continue
            cut = _find_first_cut(face, uv_layer, polyline, tolerance)
            if cut is None:
                continue
            produced = _apply_cut(uv_layer, face, cut)
            if produced is None:
                continue
            work_faces.update(produced)
            pending.extend(produced)
    return work_faces


# ---------------------------------------------------------------------------
# 折线与面的求交
# ---------------------------------------------------------------------------


def _cross_2d(first, second):
    return first.x * second.y - first.y * second.x


def _polyline_bounds(polyline):
    us = [point.x for point in polyline]
    vs = [point.y for point in polyline]
    return min(us), min(vs), max(us), max(vs)


def _face_bounds(face, uv_layer):
    us = []
    vs = []
    for loop in face.loops:
        uv = loop[uv_layer].uv
        us.append(uv.x)
        vs.append(uv.y)
    return min(us), min(vs), max(us), max(vs)


def _bounds_overlap(first, second, tolerance):
    return not (first[0] > second[2] + tolerance
                or first[2] < second[0] - tolerance
                or first[1] > second[3] + tolerance
                or first[3] < second[1] - tolerance)


def _polyline_point(polyline, distance):
    index = max(0, min(int(distance), len(polyline) - 2))
    fraction = distance - index
    return polyline[index].lerp(polyline[index + 1], fraction)


def _polyline_bends(polyline, start_distance, end_distance, tolerance):
    bends = []
    for index in range(1, len(polyline) - 1):
        if index <= start_distance + 1e-9 or index >= end_distance - 1e-9:
            continue
        point = polyline[index]
        if bends and (point - bends[-1]).length <= tolerance:
            continue
        bends.append(point)
    return bends


def _boundary_crossings(loops, points, polyline, tolerance):
    crossings = []
    count = len(points)
    for segment_index in range(len(polyline) - 1):
        start = polyline[segment_index]
        direction = polyline[segment_index + 1] - start
        length = direction.length
        if length <= tolerance:
            continue
        segment_tolerance = tolerance / length

        for loop_index in range(count):
            corner = points[loop_index]
            next_index = (loop_index + 1) % count
            next_corner = points[next_index]
            edge = next_corner - corner
            edge_length = edge.length
            if edge_length <= tolerance:
                continue

            denominator = _cross_2d(direction, edge)
            if abs(denominator) <= PARALLEL_DENOMINATOR:
                continue

            offset = corner - start
            segment_factor = _cross_2d(offset, edge) / denominator
            edge_factor = _cross_2d(offset, direction) / denominator
            if (segment_factor < -segment_tolerance
                    or segment_factor > 1.0 + segment_tolerance):
                continue
            edge_tolerance = tolerance / edge_length
            if edge_factor < -edge_tolerance or edge_factor > 1.0 + edge_tolerance:
                continue

            distance = segment_index + min(max(segment_factor, 0.0), 1.0)
            if edge_factor <= edge_tolerance:
                crossings.append(Crossing(distance, corner.copy(),
                                          vert=loops[loop_index].vert))
            elif edge_factor >= 1.0 - edge_tolerance:
                crossings.append(Crossing(distance, next_corner.copy(),
                                          vert=loops[next_index].vert))
            else:
                crossings.append(Crossing(distance,
                                          corner.lerp(next_corner, edge_factor),
                                          loop=loops[loop_index],
                                          factor=edge_factor))

    crossings.sort(key=lambda crossing: crossing.distance)
    return _merge_duplicates(crossings, tolerance)


def _merge_duplicates(crossings, tolerance):
    merged = []
    for crossing in crossings:
        if merged and (merged[-1].point - crossing.point).length <= tolerance:
            if merged[-1].vert is None and crossing.vert is not None:
                merged[-1] = crossing
            continue
        merged.append(crossing)
    return merged


def _point_in_polygon(point, polygon):
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if (current.y > point.y) != (previous.y > point.y):
            span = previous.y - current.y
            if span != 0.0:
                boundary_x = current.x + (point.y - current.y) / span * (previous.x - current.x)
                if point.x < boundary_x:
                    inside = not inside
        previous = current
    return inside


def distance_to_segment(point, start, end):
    direction = end - start
    length_squared = direction.length_squared
    if length_squared <= 0.0:
        return (point - start).length
    factor = max(0.0, min(1.0, (point - start).dot(direction) / length_squared))
    return (point - (start + direction * factor)).length


def _distance_to_boundary(point, polygon):
    shortest = float("inf")
    previous = polygon[-1]
    for current in polygon:
        shortest = min(shortest, distance_to_segment(point, previous, current))
        previous = current
    return shortest


def _is_strictly_inside(point, polygon, tolerance):
    if _distance_to_boundary(point, polygon) <= tolerance:
        return False
    return _point_in_polygon(point, polygon)


def _find_first_cut(face, uv_layer, polyline, tolerance):
    loops = list(face.loops)
    if len(loops) < 3:
        return None
    points = [loop[uv_layer].uv.copy() for loop in loops]
    crossings = _boundary_crossings(loops, points, polyline, tolerance)

    for index in range(len(crossings) - 1):
        first = crossings[index]
        second = crossings[index + 1]
        middle = _polyline_point(polyline,
                                 (first.distance + second.distance) * 0.5)
        if not _is_strictly_inside(middle, points, tolerance):
            continue
        bends = _polyline_bends(polyline, first.distance, second.distance,
                                tolerance)
        if not bends and _would_be_adjacent(face, first, second):
            continue
        return first, second, bends
    return None


def _would_be_adjacent(face, first, second):
    """切完之后这两个交点会不会正好是同一条已有边的两端。"""
    if first.vert is not None and second.vert is not None:
        return _verts_adjacent_in_face(face, first.vert, second.vert)
    if first.vert is not None:
        return first.vert in second.loop.edge.verts
    if second.vert is not None:
        return second.vert in first.loop.edge.verts
    return first.loop.edge is second.loop.edge


def _verts_adjacent_in_face(face, first_vert, second_vert):
    if first_vert is second_vert:
        return True
    for loop in face.loops:
        pair = (loop.vert, loop.link_loop_next.vert)
        if first_vert in pair and second_vert in pair:
            return True
    return False


# ---------------------------------------------------------------------------
# 落刀
# ---------------------------------------------------------------------------


def _as_plane_point(uv):
    return Vector((uv.x, uv.y, 0.0))


def _distance_to_triangle(point, triangle):
    if _point_in_polygon(point, triangle):
        return 0.0
    return min(distance_to_segment(point, triangle[0], triangle[1]),
               distance_to_segment(point, triangle[1], triangle[2]),
               distance_to_segment(point, triangle[2], triangle[0]))


def _position_from_uv(loops, points, uv_point):
    best_indices = (0, 1, 2)
    best_distance = float("inf")
    for index in range(1, len(points) - 1):
        indices = (0, index, index + 1)
        distance = _distance_to_triangle(
            uv_point, (points[indices[0]], points[indices[1]], points[indices[2]]))
        if distance < best_distance:
            best_distance = distance
            best_indices = indices
            if distance == 0.0:
                break
    return barycentric_transform(
        _as_plane_point(uv_point),
        _as_plane_point(points[best_indices[0]]),
        _as_plane_point(points[best_indices[1]]),
        _as_plane_point(points[best_indices[2]]),
        loops[best_indices[0]].vert.co,
        loops[best_indices[1]].vert.co,
        loops[best_indices[2]].vert.co,
    )


def _split_at(loop, factor):
    _new_edge, new_vert = bmesh.utils.edge_split(loop.edge, loop.vert, factor)
    return new_vert


def _resolve_pair(first, second):
    if first.vert is not None and second.vert is not None:
        return first.vert, second.vert
    if first.vert is not None:
        return first.vert, _split_at(second.loop, second.factor)
    if second.vert is not None:
        return _split_at(first.loop, first.factor), second.vert
    if first.loop.edge is not second.loop.edge:
        return _split_at(first.loop, first.factor), _split_at(second.loop, second.factor)

    far, near = (first, second) if first.factor >= second.factor else (second, first)
    from_vert = far.loop.vert
    near_edge, far_vert = bmesh.utils.edge_split(far.loop.edge, from_vert, far.factor)
    _split_edge, near_vert = bmesh.utils.edge_split(
        near_edge, from_vert, near.factor / far.factor)
    if far is first:
        return far_vert, near_vert
    return near_vert, far_vert


def _apply_cut(uv_layer, face, cut):
    first, second, bends = cut
    loops = list(face.loops)
    points = [loop[uv_layer].uv.copy() for loop in loops]
    positions = [_position_from_uv(loops, points, bend) for bend in bends]

    first_vert, second_vert = _resolve_pair(first, second)
    if first_vert is second_vert:
        return None

    boundary_verts = set(face.verts)
    new_face, _new_loop = bmesh.utils.face_split(
        face, first_vert, second_vert, coords=positions)
    if new_face is None:
        return None

    if bends:
        created = (set(face.verts) | set(new_face.verts)) - boundary_verts
        _stamp_uv(created, uv_layer, bends)

    return face, new_face


def _stamp_uv(verts, uv_layer, bends):
    """把折线拐点的 UV 精确写回新顶点，插值只保证近似落在折线上。"""
    remaining = list(bends)
    for vert in verts:
        if not remaining:
            break
        reference = vert.link_loops[0][uv_layer].uv
        nearest = min(remaining, key=lambda bend: (bend - reference).length_squared)
        remaining.remove(nearest)
        for loop in vert.link_loops:
            loop[uv_layer].uv = nearest.copy()
