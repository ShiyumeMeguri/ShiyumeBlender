"""按标量场的等值线切割网格。

UV 孤岛只负责给出标量：每个孤岛的 UV 坐标是自己的一把尺子，互相不通约。
共享边上的顶点只有一个值，所以先在整片壳（经共享顶点连通的孤岛）上定出唯一的
标量场：参考孤岛取自己的 UV 坐标，相邻孤岛以共享顶点为边界条件做调和延拓。
然后整片壳按同一个场的等值线下刀，两侧在共享边上落的是同一个点，环边天然闭合。
"""

import math

import bmesh
import numpy

from . import uv_islands


AXIS_INDEX = {"U": 0, "V": 1}
SNAP_RATIO = 0.02
LEVEL_LIMIT = 20000


def uv_continuous(edge, uv_layer, tolerance):
    loops = list(edge.link_loops)
    if len(loops) != 2:
        return False
    first, second = loops
    first_uvs = {
        first.vert: first[uv_layer].uv,
        first.link_loop_next.vert: first.link_loop_next[uv_layer].uv,
    }
    for loop in (second, second.link_loop_next):
        matching = first_uvs.get(loop.vert)
        if matching is None or (matching - loop[uv_layer].uv).length > tolerance:
            return False
    return True


# ---------------------------------------------------------------------------
# 标量场
# ---------------------------------------------------------------------------


def _island_values(faces, uv_layer, axis_index):
    values = {}
    for face in faces:
        for loop in face.loops:
            values.setdefault(loop.vert, loop[uv_layer].uv[axis_index])
    return values


def _island_edges(faces, uv_layer):
    edges = {}
    for face in faces:
        for loop in face.loops:
            edge = loop.edge
            if edge not in edges:
                length = (loop[uv_layer].uv - loop.link_loop_next[uv_layer].uv).length
                edges[edge] = (loop.vert, loop.link_loop_next.vert, length)
    return edges.values()


def _harmonic_extension(count, edge_first, edge_second, weight, fixed, fixed_values):
    """在图上让 sum(w * (x_a - x_b)^2) 最小，fixed 处取给定值。"""
    solution = numpy.where(fixed, fixed_values, 0.0)
    free = ~fixed
    if not free.any():
        return solution

    def laplacian(vector):
        flow = weight * (vector[edge_first] - vector[edge_second])
        return (numpy.bincount(edge_first, flow, count)
                - numpy.bincount(edge_second, flow, count))

    degree = (numpy.bincount(edge_first, weight, count)
              + numpy.bincount(edge_second, weight, count))
    degree = numpy.where(degree > 0.0, degree, 1.0)

    residual = -laplacian(solution)
    residual[fixed] = 0.0
    scale = numpy.linalg.norm(residual)
    if scale == 0.0:
        return solution
    preconditioned = residual / degree
    direction = preconditioned.copy()
    rz = residual @ preconditioned
    for _step in range(min(4 * count + 50, 5000)):
        image = laplacian(direction)
        image[fixed] = 0.0
        curvature = direction @ image
        if curvature <= 0.0:
            break
        step = rz / curvature
        solution += step * direction
        residual -= step * image
        if numpy.linalg.norm(residual) <= scale * 1e-12:
            break
        preconditioned = residual / degree
        rz_next = residual @ preconditioned
        direction = preconditioned + (rz_next / rz) * direction
        rz = rz_next
    return solution


def _monotone_fit(knots):
    """把 (坐标, 值) 拟合成单调函数（池相邻违规者），返回去重排序后的两列。"""
    order = numpy.argsort(knots[:, 0], kind="stable")
    positions = knots[order, 0]
    values = knots[order, 1]
    unique_positions, inverse = numpy.unique(positions, return_inverse=True)
    sums = numpy.bincount(inverse, values)
    counts = numpy.bincount(inverse).astype(numpy.float64)
    means = sums / counts
    sign = 1.0 if numpy.corrcoef(unique_positions, means)[0, 1] >= 0.0 or len(means) < 3 else -1.0
    blocks = []
    for mean, weight in zip(sign * means, counts):
        blocks.append([mean, weight, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            last = blocks.pop()
            blocks[-1][0] = (blocks[-1][0] * blocks[-1][1] + last[0] * last[1]) / (blocks[-1][1] + last[1])
            blocks[-1][1] += last[1]
            blocks[-1][2] += last[2]
    fitted = sign * numpy.concatenate([numpy.full(size, mean) for mean, _weight, size in blocks])
    return unique_positions, fitted


def _warp(knots, coordinates):
    """沿孤岛自己的轴把坐标映成场值：折线插值，两端以孤岛自己的尺度（斜率 1）外延。"""
    positions, values = _monotone_fit(knots)
    if len(positions) == 1:
        return values[0] + (coordinates - positions[0])
    result = numpy.interp(coordinates, positions, values)
    below = coordinates < positions[0]
    above = coordinates > positions[-1]
    result[below] = values[0] + (coordinates[below] - positions[0])
    result[above] = values[-1] + (coordinates[above] - positions[-1])
    return result


def _extend_into_island(faces, values, uv_layer, field):
    """孤岛里已有定值的顶点（共享边）当边界：先沿孤岛自己的轴拟合出单调映射，
    再把边界上与映射的残差做调和延拓，叠加到其余顶点上，写进 field。"""
    verts = list(values)
    index_of = {vert: index for index, vert in enumerate(verts)}
    edges = list(_island_edges(faces, uv_layer))
    edge_first = numpy.array([index_of[first] for first, _second, _length in edges], dtype=numpy.int64)
    edge_second = numpy.array([index_of[second] for _first, second, _length in edges], dtype=numpy.int64)
    weight = numpy.array([1.0 / max(length, 1e-9) for _first, _second, length in edges])
    fixed = numpy.array([vert in field for vert in verts])
    own = numpy.array([values[vert] for vert in verts])
    base = _warp(numpy.array([[own[index], field[vert]] for index, vert in enumerate(verts) if fixed[index]]), own)
    residual = numpy.array([field[vert] - base[index] if fixed[index] else 0.0
                            for index, vert in enumerate(verts)])
    correction = _harmonic_extension(len(verts), edge_first, edge_second, weight, fixed, residual)
    for index, vert in enumerate(verts):
        if not fixed[index]:
            field[vert] = float(base[index] + correction[index])


def build_field(islands, uv_layer, axis_index):
    """返回 (场, 壳列表)。壳是经共享顶点连通的孤岛编号列表，每片壳一个参考孤岛。"""
    island_faces = [island.selected_faces for island in islands]
    island_values = [_island_values(faces, uv_layer, axis_index) for faces in island_faces]
    extents = [max(values.values()) - min(values.values()) if values else 0.0
               for values in island_values]

    owners = {}
    for index, values in enumerate(island_values):
        for vert in values:
            owners.setdefault(vert, []).append(index)

    field = {}
    assigned = [False] * len(islands)
    shells = []
    for start in sorted(range(len(islands)), key=lambda index: -extents[index]):
        if assigned[start]:
            continue
        assigned[start] = True
        field.update(island_values[start])
        shell = [start]
        cursor = 0
        while cursor < len(shell):
            current = shell[cursor]
            cursor += 1
            neighbors = sorted(
                {other for vert in island_values[current] for other in owners[vert]
                 if not assigned[other]},
                key=lambda index: -extents[index])
            for other in neighbors:
                if assigned[other]:
                    continue
                assigned[other] = True
                _extend_into_island(island_faces[other], island_values[other], uv_layer, field)
                shell.append(other)
        shells.append(shell)
    return field, shells


# ---------------------------------------------------------------------------
# 等值线下刀
# ---------------------------------------------------------------------------


def _cut_level(faces, field, level, snap, cut_edges):
    live = [face for face in faces if face.is_valid]
    edges = {edge for face in live for edge in face.edges}
    crossings = []
    for edge in edges:
        first, second = edge.verts
        first_offset = field[first] - level
        second_offset = field[second] - level
        if abs(first_offset) <= snap or abs(second_offset) <= snap:
            continue
        if (first_offset < 0.0) != (second_offset < 0.0):
            crossings.append((edge, first, first_offset / (first_offset - second_offset)))
    for edge, first, factor in crossings:
        _new_edge, new_vert = bmesh.utils.edge_split(edge, first, factor)
        field[new_vert] = level

    stack = [face for face in live if face.is_valid]
    while stack:
        face = stack.pop()
        if not face.is_valid:
            continue
        verts = [loop.vert for loop in face.loops]
        count = len(verts)
        on_level = [index for index, vert in enumerate(verts)
                    if abs(field[vert] - level) <= snap]
        best = None
        for position, first in enumerate(on_level):
            for second in on_level[position + 1:]:
                gap = min(second - first, count - (second - first))
                if gap >= 2 and (best is None or gap < best[0]):
                    best = (gap, first, second)
        if best is None:
            continue
        _gap, first, second = best
        new_face, new_loop = bmesh.utils.face_split(face, verts[first], verts[second])
        if new_face is None:
            continue
        cut_edges.add(new_loop.edge)
        faces.add(new_face)
        stack.append(face)
        stack.append(new_face)


def _row_edges(faces, uv_layer, axis_index, tolerance, slope, excluded):
    """旧布线里与刀路同向的内部边：UV 里沿刀路方向的分量远大于垂直方向的分量。"""
    other_index = 1 - axis_index
    rows = []
    seen = set()
    for face in faces:
        if not face.is_valid:
            continue
        for loop in face.loops:
            edge = loop.edge
            if edge in seen:
                continue
            seen.add(edge)
            if edge in excluded or edge.seam or len(edge.link_faces) != 2:
                continue
            if not all(linked in faces for linked in edge.link_faces):
                continue
            if not uv_continuous(edge, uv_layer, tolerance):
                continue
            start = loop[uv_layer].uv
            end = loop.link_loop_next[uv_layer].uv
            along = abs(end[other_index] - start[other_index])
            across = abs(end[axis_index] - start[axis_index])
            if along > tolerance and across <= slope * along:
                rows.append(edge)
    return rows


def _level_steps(field, vert, origin, interval, snap):
    steps = round((field[vert] - origin) / interval)
    if abs(field[vert] - (origin + steps * interval)) > snap:
        return None
    return steps


def _rows(edges):
    """经共享顶点相连的旧边是同一整条旧行，只能整条溶解或整条保留。"""
    parent = {edge: edge for edge in edges}

    def find(edge):
        while parent[edge] is not edge:
            parent[edge] = parent[parent[edge]]
            edge = parent[edge]
        return edge

    by_vert = {}
    for edge in edges:
        for vert in edge.verts:
            by_vert.setdefault(vert, []).append(edge)
    for incident in by_vert.values():
        root = find(incident[0])
        for edge in incident[1:]:
            parent[find(edge)] = root
    rows = {}
    for edge in edges:
        rows.setdefault(find(edge), []).append(edge)
    return list(rows.values())


def _row_leaves_quads(row):
    """整条旧行溶解之后，被它并起来的每一块面是不是四边形（或更少）。
    并起来的多边形边数 = 各面边数之和 - 2 * 溶解的边数，再扣掉随后被溶解的二度顶点。"""
    counts = {}
    for edge in row:
        for vert in edge.verts:
            counts[vert] = counts.get(vert, 0) + 1
    removed = {vert for vert, count in counts.items() if len(vert.link_edges) - count == 2}

    parent = {}

    def find(face):
        while parent[face] is not face:
            parent[face] = parent[parent[face]]
            face = parent[face]
        return face

    for edge in row:
        for face in edge.link_faces:
            parent.setdefault(face, face)
    for edge in row:
        first, second = edge.link_faces
        parent[find(first)] = find(second)
    regions = {}
    for edge in row:
        regions.setdefault(find(edge.link_faces[0]), set()).add(edge)
    members = {}
    for face in parent:
        members.setdefault(find(face), []).append(face)
    for root, faces in members.items():
        size = sum(len(face.verts) for face in faces) - 2 * len(regions.get(root, ()))
        size -= len({vert for face in faces for vert in face.verts if vert in removed})
        if size > 4:
            return False
    return True


def _landmark_knots(rows, field, levels):
    """溶解之后仍会留下多余角的旧行，它的拓扑地标（接缝的尽头、尖端的顶点）必须落在一条刀路上。
    返回 (地标场值下限, 上限, 目标刀路) 列表。"""
    knots = []
    for row in _rows(rows):
        if _row_leaves_quads(row):
            continue
        counts = {}
        for edge in row:
            for vert in edge.verts:
                counts[vert] = counts.get(vert, 0) + 1
        values = [field[vert] for vert, count in counts.items() if len(vert.link_edges) - count >= 3]
        if not values:
            continue
        mean = sum(values) / len(values)
        knots.append((min(values), max(values), min(levels, key=lambda level: abs(level - mean))))
    return knots


def _warp_field(verts, field, knots):
    """把场做一次单调的分段线性变形，让每个地标正好落在目标刀路上：
    网格不动，只是地标之间的刀距按比例伸缩，旧行就不必再保留成多出来的一行。"""
    knots.sort()
    positions = []
    targets = []
    for low, high, target in knots:
        for position in (low, high):
            position = max(position, positions[-1] + 1e-9) if positions else position
            positions.append(position)
            targets.append(max(target, targets[-1] if targets else target))
    values = numpy.array([field[vert] for vert in verts])
    warped = numpy.interp(values, positions, targets)
    below = values < positions[0]
    above = values > positions[-1]
    warped[below] = values[below] + (targets[0] - positions[0])
    warped[above] = values[above] + (targets[-1] - positions[-1])
    for vert, value in zip(verts, warped):
        field[vert] = float(value)


def _grid_levels(values, origin, interval, snap):
    step = math.ceil((min(values) + snap - origin) / interval)
    levels = []
    while origin + step * interval < max(values) - snap:
        levels.append(origin + step * interval)
        step += 1
    return levels


def _replaced_edges(rows, field, origin, interval, snap):
    candidates = []
    for edge in rows:
        first, second = edge.verts
        steps = _level_steps(field, first, origin, interval, snap)
        if steps is not None and steps == _level_steps(field, second, origin, interval, snap):
            continue
        candidates.append(edge)
    return [edge for row in _rows(candidates) if _row_leaves_quads(row) for edge in row]


def _check_level_count(bm, uv_layer, tool_settings, axes, interval):
    """动刀之前先量好：任何一片壳的刀数超限就整个拒绝，不留下切了一半的网格。"""
    islands = uv_islands.collect_selected_islands(bm, uv_layer, tool_settings)
    for axis in axes:
        field, shells = build_field(islands, uv_layer, AXIS_INDEX[axis])
        for shell in shells:
            values = [field[loop.vert] for index in shell
                      for face in islands[index].selected_faces for loop in face.loops]
            if (max(values) - min(values)) / interval > LEVEL_LIMIT:
                raise ValueError("切刀数超过 %d：间隔相对 UV 尺寸太小" % LEVEL_LIMIT)


def cut_by_grid(bm, uv_layer, tool_settings, axes, interval, align_to_island,
                dissolve_old, parallel_angle, tolerance):
    """按壳统一的场做等距下刀，返回 (被切的壳数, 新增面数, 溶解的旧边数)。"""
    snap = interval * SNAP_RATIO
    slope = math.tan(parallel_angle)
    cut_shells = 0
    before = len(bm.faces)
    dissolved = 0

    _check_level_count(bm, uv_layer, tool_settings, axes, interval)
    for axis in axes:
        axis_index = AXIS_INDEX[axis]
        islands = uv_islands.collect_selected_islands(bm, uv_layer, tool_settings)
        if not islands:
            continue
        field, shells = build_field(islands, uv_layer, axis_index)
        cut_edges = set()
        shell_faces = []
        for shell in shells:
            faces = {face for index in shell for face in islands[index].selected_faces}
            low = min(field[loop.vert] for face in faces for loop in face.loops)
            origin = low if align_to_island else 0.0
            verts = list({loop.vert for face in faces for loop in face.loops})
            levels = _grid_levels([field[vert] for vert in verts], origin, interval, snap)
            if dissolve_old and levels:
                knots = _landmark_knots(
                    _row_edges(faces, uv_layer, axis_index, tolerance, slope, cut_edges),
                    field, levels)
                if knots:
                    _warp_field(verts, field, knots)
                    levels = _grid_levels([field[vert] for vert in verts], origin, interval, snap)
            for level in levels:
                _cut_level(faces, field, level, snap, cut_edges)
            if levels:
                cut_shells += 1
            shell_faces.append((faces, origin))

        for faces, origin in shell_faces:
            uv_islands.select_faces(face for face in faces if face.is_valid)
            if dissolve_old:
                rows = _row_edges(faces, uv_layer, axis_index, tolerance, slope, cut_edges)
                edges = _replaced_edges(rows, field, origin, interval, snap)
                if edges:
                    bmesh.ops.dissolve_edges(bm, edges=edges, use_verts=True)
                    dissolved += len(edges)

    return cut_shells, len(bm.faces) - before, dissolved
