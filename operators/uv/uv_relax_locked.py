"""锁边的方形头发 UV 重排：孤岛是矩形，外轮廓（四个角和四条边）一点不动，里面重新排成规整的网格。

每一排的所有顶点落在同一个 V 上（绝对水平的直线），V 按这一排沿头发的真实弧长占全长的比例分布，
所以纵向没有拉伸；两侧的顶点只沿矩形的左右边上下滑动。
每一列的所有顶点落在同一个 U 上（绝对垂直的直线）：均匀模式下各列等分矩形宽度，中间列正好居中；
保形模式下各列取 3D 里各排宽度比例的加权平均位置。头发首尾收拢成一点的那几排，3D 里没有宽度可言，
也按同样的列位置排，所以首尾的点完全居中，不会偏向左右。
展开方向沿用孤岛现有的朝向：V 大的一端仍在上，U 小的一侧仍在左，贴图不会被翻转。
"""

import numpy

from . import hair_strip_unwrap, uv_islands


OUTLINE_TOLERANCE = 1.0e-4
MIN_STEP_RATIO = 1.0e-7
ROW_WIDTH_FLOOR = 1.0e-9


class UnsupportedIsland(Exception):
    pass


def _oriented_rows(rows, uv):
    """使 V 大的一端排在前面、每排内 U 小的一侧排在前面。"""
    third = max(1, len(rows) // 3)
    head = numpy.mean([uv[vertex][1] for row in rows[:third] for vertex in row])
    tail = numpy.mean([uv[vertex][1] for row in rows[-third:] for vertex in row])
    if head < tail:
        rows = rows[::-1]
    tilt = sum(uv[row[-1]][0] - uv[row[0]][0] for row in rows)
    if tilt < 0.0:
        rows = [row[::-1] for row in rows]
    return rows


def _check_rectangle(uv, boundary):
    points = numpy.array([uv[vertex] for vertex in boundary])
    low = points.min(axis=0)
    high = points.max(axis=0)
    if high[0] - low[0] <= 0.0 or high[1] - low[1] <= 0.0:
        raise UnsupportedIsland("轮廓宽或高为零")
    tolerance = OUTLINE_TOLERANCE * float(max(high - low))
    for x, y in points:
        on_vertical = min(abs(x - low[0]), abs(x - high[0])) <= tolerance
        on_horizontal = min(abs(y - low[1]), abs(y - high[1])) <= tolerance
        if not (on_vertical or on_horizontal):
            raise UnsupportedIsland("轮廓不是与坐标轴对齐的矩形")
    return low, high


def _row_fractions(row):
    """一排各点在 3D 里按累计距离占总宽的比例；宽度为零（收拢成一点）时返回 (None, 0)。"""
    positions = [0.0]
    for index in range(1, len(row)):
        positions.append(positions[-1] + (row[index].co - row[index - 1].co).length)
    if positions[-1] <= ROW_WIDTH_FLOOR:
        return None, 0.0
    return [position / positions[-1] for position in positions], positions[-1]


def column_fractions(rows, column_mode):
    count = len(rows[0])
    even = [index / (count - 1) for index in range(count)]
    if column_mode == "EVEN":
        return even
    totals = numpy.zeros(count)
    weight = 0.0
    for row in rows:
        fractions, width = _row_fractions(row)
        if fractions is not None:
            totals += width * numpy.array(fractions)
            weight += width
    if weight <= 0.0:
        return even
    result = totals / weight
    result[0] = 0.0
    result[-1] = 1.0
    return result.tolist()


def row_heights(rows):
    """每一排到首排的弧长占全长的比例（沿两侧外缘中线量），严格递增，首排 0、末排 1。"""
    centers = [0.5 * (row[0].co + row[-1].co) for row in rows]
    arc = [0.0]
    for index in range(1, len(centers)):
        arc.append(arc[-1] + (centers[index] - centers[index - 1]).length)
    if arc[-1] <= 0.0:
        raise UnsupportedIsland("长条长度为零")
    fractions = [0.0]
    for index in range(1, len(arc)):
        fractions.append(max(arc[index] / arc[-1], fractions[-1] + MIN_STEP_RATIO))
    return [value / fractions[-1] for value in fractions]


def regrid_island(faces, uv_layer, column_mode):
    face_set = set(faces)
    uv = {}
    for face in faces:
        for loop in face.loops:
            uv[loop.vert] = numpy.array(loop[uv_layer].uv)
    boundary = {vertex for face in faces for edge in face.edges
                if sum(1 for linked in edge.link_faces if linked in face_set) == 1 for vertex in edge.verts}
    low, high = _check_rectangle(uv, boundary)
    try:
        rows = _oriented_rows(hair_strip_unwrap.strip_rows(faces), uv)
    except hair_strip_unwrap.UnsupportedIsland as error:
        raise UnsupportedIsland(str(error))
    columns = column_fractions(rows, column_mode)
    heights = row_heights(rows)
    placed = {}
    for row, height in zip(rows, heights):
        v = float(high[1] - (high[1] - low[1]) * height)
        for vertex, fraction in zip(row, columns):
            placed[vertex] = (float(low[0] + (high[0] - low[0]) * fraction), v)
    for face in faces:
        for loop in face.loops:
            loop[uv_layer].uv = placed[loop.vert]


def regrid(bm, uv_layer, column_mode, selected_only, tool_settings):
    """返回 (处理的孤岛数, 跳过的 [(原因, 面数)])。"""
    if selected_only:
        islands = [island.faces for island in uv_islands.collect_selected_islands(bm, uv_layer, tool_settings)]
    else:
        islands = uv_islands.collect_islands(bm, uv_layer)
    done = 0
    skipped = []
    for faces in islands:
        try:
            regrid_island(faces, uv_layer, column_mode)
        except UnsupportedIsland as error:
            skipped.append((str(error), len(faces)))
            continue
        done += 1
    return done, skipped
