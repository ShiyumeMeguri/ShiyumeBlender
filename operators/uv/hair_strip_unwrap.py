"""头发长条的展开内核：每个孤岛是 W 列四边形的长条（每排 W+1 个顶点），按真实长度展成不拉伸的梯形长条，发根朝上，
再做等价于「孤岛大小平均化 + UVToolkit 对齐左上角 + 归一化等比缩放占满 0-1」的整体排布。

每个孤岛：V 方向是沿两侧外缘中线的弧长，U 方向是每一排截面上各点间的真实距离（每排以中心对齐，尖端收成一点）。
所有孤岛用同一把真实长度尺子，所以孤岛大小天然平均化；整体再统一缩放使最大的一条恰好占满 0-1，
每个孤岛左上角对齐 (0, 1)、发根在 V = 1。之后在这套 UV 上按等距下刀，所有长条同一高度处的切线对应同样的真实长度，
并排的头发不会错位。
"""

from collections import defaultdict

from . import uv_islands


MAX_COLUMNS = 16


class UnsupportedIsland(Exception):
    pass


def _find(parent, edge):
    while parent[edge] is not edge:
        parent[edge] = parent[parent[edge]]
        edge = parent[edge]
    return edge


def opposite_edge_classes(faces):
    parent = {}
    for face in faces:
        if len(face.verts) != 4:
            raise UnsupportedIsland("含有非四边形的面")
        for loop in face.loops:
            parent.setdefault(loop.edge, loop.edge)
    for face in faces:
        edges = [loop.edge for loop in face.loops]
        for first, second in ((edges[0], edges[2]), (edges[1], edges[3])):
            root_first = _find(parent, first)
            root_second = _find(parent, second)
            if root_first is not root_second:
                parent[root_first] = root_second
    classes = defaultdict(list)
    for edge in parent:
        classes[_find(parent, edge)].append(edge)
    return list(classes.values())


def _grid_shape(face_count, class_sizes):
    """面数 = 列数 * (排数 - 1)；横向类有「列数」个、每类「排数」条边，纵向类有「排数 - 1」个、每类「列数 + 1」条边。"""
    for columns in range(1, MAX_COLUMNS + 1):
        if face_count % columns:
            continue
        rows = face_count // columns + 1
        if sorted(class_sizes) == sorted([rows] * columns + [columns + 1] * (rows - 1)):
            return columns, rows
    raise UnsupportedIsland("不是规则的四边形长条")


def _ordered_rungs(edges, face_set):
    ends = [edge for edge in edges if sum(1 for face in edge.link_faces if face in face_set) == 1]
    if len(ends) != 2:
        raise UnsupportedIsland("横向边没有恰好两个端点")
    members = set(edges)
    ordered = [ends[0]]
    previous_face = None
    current = ends[0]
    while True:
        faces = [face for face in current.link_faces if face in face_set and face is not previous_face]
        if not faces:
            break
        face = faces[0]
        other = [loop.edge for loop in face.loops if loop.edge in members and loop.edge is not current]
        if len(other) != 1:
            raise UnsupportedIsland("长条不是规则的网格")
        ordered.append(other[0])
        previous_face = face
        current = other[0]
    return ordered


def _order_columns(across):
    """横向类按从一侧到另一侧的顺序排列：相邻两列共享顶点。"""
    if len(across) == 1:
        return across
    vertex_sets = [{vertex for edge in edges for vertex in edge.verts} for edges in across]
    neighbours = [[other for other in range(len(across)) if other != index and vertex_sets[index] & vertex_sets[other]]
                  for index in range(len(across))]
    starts = [index for index, linked in enumerate(neighbours) if len(linked) == 1]
    if len(starts) != 2:
        raise UnsupportedIsland("各列没有串成一条")
    order = [starts[0]]
    while len(order) < len(across):
        following = [index for index in neighbours[order[-1]] if index not in order]
        if len(following) != 1:
            raise UnsupportedIsland("各列没有串成一条")
        order.append(following[0])
    return [across[index] for index in order]


def strip_rows(faces):
    """把一个孤岛整理成从一端到另一端的若干排，每排是从一侧到另一侧的 W+1 个顶点。"""
    face_set = set(faces)
    classes = opposite_edge_classes(faces)
    columns, row_count = _grid_shape(len(faces), [len(edges) for edges in classes])
    if columns == row_count - 1 and columns + 1 == row_count:
        raise UnsupportedIsland("横向与纵向无法区分")
    across = [edges for edges in classes if len(edges) == row_count]
    if len(across) != columns:
        raise UnsupportedIsland("横向与纵向无法区分")
    rungs = [_ordered_rungs(edges, face_set) for edges in _order_columns(across)]
    if any(len(column) != row_count for column in rungs):
        raise UnsupportedIsland("排数与面数对不上")
    for index in range(1, columns):
        if not set(rungs[index - 1][0].verts) & set(rungs[index][0].verts):
            rungs[index].reverse()

    rows = []
    for row in range(row_count):
        if columns == 1:
            first, second = rungs[0][row].verts
            if rows:
                previous_left = rows[-1][0]
                linked = {edge.other_vert(previous_left) for edge in previous_left.link_edges}
                first, second = (first, second) if first in linked else (second, first)
            rows.append([first, second])
            continue
        shared = []
        for index in range(1, columns):
            common = set(rungs[index - 1][row].verts) & set(rungs[index][row].verts)
            if len(common) != 1:
                raise UnsupportedIsland("相邻两列的横向边没有共享的顶点")
            shared.append(next(iter(common)))
        left = rungs[0][row].other_vert(shared[0])
        right = rungs[-1][row].other_vert(shared[-1])
        rows.append([left] + shared + [right])
    return rows


def _row_center(row):
    """弧长沿两侧外缘的中线量：两侧外缘顶点被正反两个孤岛共享，同一根头发的正反面因此用同一把弧长，
    并排头发之间也不会因为各自挑了不同的中线而错位。"""
    return 0.5 * (row[0].co + row[-1].co)


def _mean_key(rows, key_of_vertex):
    keys = [key_of_vertex(vertex) for row in rows for vertex in row]
    return sum(keys) / len(keys)


def root_first(rows, key_of_vertex):
    """发根一端排在前面：两端各取三分之一的排，顶点键平均值小的一端是发根。"""
    third = max(1, len(rows) // 3)
    head = _mean_key(rows[:third], key_of_vertex)
    tail = _mean_key(rows[-third:], key_of_vertex)
    if abs(head - tail) < 1.0e-9:
        raise UnsupportedIsland("两端分不出发根")
    return rows if head < tail else rows[::-1]


def island_layout(rows):
    """返回 (每排各点的 (u, 到发根的弧长 s), 宽度, 长度)，u 以最宽一排居中后从 0 起。"""
    centers = [_row_center(row) for row in rows]
    arc = [0.0]
    for index in range(1, len(centers)):
        arc.append(arc[-1] + (centers[index] - centers[index - 1]).length)
    offsets = []
    widths = []
    for row in rows:
        positions = [0.0]
        for index in range(1, len(row)):
            positions.append(positions[-1] + (row[index].co - row[index - 1].co).length)
        widths.append(positions[-1])
        offsets.append([position - 0.5 * positions[-1] for position in positions])
    island_width = max(widths)
    coordinates = [[(offset + 0.5 * island_width, arc[index]) for offset in row_offsets]
                   for index, row_offsets in enumerate(offsets)]
    return coordinates, island_width, arc[-1]


def _signed_uv_area(face, position):
    points = [position[loop.vert] for loop in face.loops]
    return sum(points[index][0] * points[(index + 1) % len(points)][1]
               - points[(index + 1) % len(points)][0] * points[index][1] for index in range(len(points)))


def unwrap(bm, uv_layer, key_of_vertex, selected_only, tool_settings):
    """重写 uv_layer：返回 (展开的孤岛数, 跳过的 [(原因, 面数)], 统一缩放比例)。"""
    if selected_only:
        islands = [island.faces for island in uv_islands.collect_selected_islands(bm, uv_layer, tool_settings)]
    else:
        islands = uv_islands.collect_islands(bm, uv_layer)

    laid_out = []
    skipped = []
    for faces in islands:
        try:
            rows = root_first(strip_rows(faces), key_of_vertex)
        except UnsupportedIsland as error:
            skipped.append((str(error), len(faces)))
            continue
        coordinates, width, length = island_layout(rows)
        laid_out.append((faces, rows, coordinates, width, length))

    if not laid_out:
        return 0, skipped, 0.0
    scale = 1.0 / max(max(width, length) for _faces, _rows, _coordinates, width, length in laid_out)
    for faces, rows, coordinates, width, _length in laid_out:
        position = {}
        for row, points in zip(rows, coordinates):
            for vertex, (u, s) in zip(row, points):
                position[vertex] = (u * scale, 1.0 - s * scale)
        mirror = sum(_signed_uv_area(face, position) for face in faces) < 0.0
        for face in faces:
            for loop in face.loops:
                u, v = position[loop.vert]
                loop[uv_layer].uv = (width * scale - u if mirror else u, v)
    return len(laid_out), skipped, scale
