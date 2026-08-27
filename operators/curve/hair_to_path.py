import bmesh
import bpy
import heapq
import math

from mathutils import Vector

BACKTRACK_ALLOWANCE = 0.12
RAIL_LENGTH_RATIO = 0.45
PINCH_TIP_FRACTION = 0.10
PINCH_JUMP_FRACTION = 0.40
PINCH_FLATNESS_FRACTION = 0.15
DIRECTION_VALID_FRACTION = 0.25
PAIR_COINCIDENCE_FRACTION = 0.5
PAIR_WELD_DISTANCE = 1.0e-5
PROFILE_SURVEY_FRACTION = 0.30
PROFILE_SURVEY_LIMIT = 14
SLICE_LIMIT_FACTOR = 1.5
SLICE_MERGE_FRACTION = 0.02
PROFILE_SIMPLIFY_FRACTION = 0.03
PATH_ORDER = 5
REGULARIZATION = 1.0e-6
TILT_ITERATIONS = 4
TILT_WEIGHT_FLOOR = 0.02
TILT_REPORT_FRACTION = 0.20


def ordered(elements):
    return sorted(elements, key=lambda element: element.index)


def shell_islands(mesh):
    visited = set()
    islands = []
    for vertex in mesh.verts:
        if vertex in visited:
            continue
        stack = [vertex]
        component = []
        visited.add(vertex)
        while stack:
            current = stack.pop()
            component.append(current)
            for edge in current.link_edges:
                other = edge.other_vert(current)
                if other not in visited:
                    visited.add(other)
                    stack.append(other)
        islands.append(component)
    return islands


def geodesic_distance(sources, allowed):
    distance = {vertex: 0.0 for vertex in sources}
    queue = [(0.0, vertex.index, vertex) for vertex in sources]
    heapq.heapify(queue)
    while queue:
        current, _, vertex = heapq.heappop(queue)
        if current > distance.get(vertex, 1.0e30) + 1.0e-12:
            continue
        for edge in vertex.link_edges:
            other = edge.other_vert(vertex)
            if other not in allowed:
                continue
            candidate = current + (other.co - vertex.co).length
            if candidate < distance.get(other, 1.0e30) - 1.0e-12:
                distance[other] = candidate
                heapq.heappush(queue, (candidate, other.index, other))
    return distance


def shell_arclength_field(component):
    allowed = set(component)
    seed = geodesic_distance([component[0]], allowed)
    return geodesic_distance([max(seed, key=seed.get)], allowed)


def boundary_cycle(component):
    edges = set()
    for vertex in component:
        edges.update(vertex.link_edges)
    boundary_edges = [edge for edge in edges if len(edge.link_faces) == 1]
    if not boundary_edges:
        return None
    adjacency = {}
    for edge in boundary_edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)
    if set(len(entry) for entry in adjacency.values()) != {2}:
        return None
    start = boundary_edges[0]
    cycle = [start.verts[0]]
    previous = start.verts[0]
    current = start.verts[1]
    while current is not cycle[0]:
        cycle.append(current)
        following = None
        for edge in adjacency[current]:
            other = edge.other_vert(current)
            if other is not previous:
                following = other
                break
        if following is None:
            return None
        previous, current = current, following
        if len(cycle) > 2 * len(boundary_edges):
            return None
    return cycle


def split_cycle_into_rails(cycle, arclength):
    count = len(cycle)
    ranked = sorted(range(count), key=lambda index: arclength.get(cycle[index], 0.0))
    low, high = sorted((ranked[0], ranked[-1]))
    if low == high:
        return None
    return [cycle[low:high + 1], cycle[high:] + cycle[:low + 1]]


def run_length(run):
    return sum((run[index + 1].co - run[index].co).length for index in range(len(run) - 1))


def backtrack_ratio(run, arclength):
    values = [arclength.get(vertex, 0.0) for vertex in run]
    if values[0] > values[-1]:
        values.reverse()
    span = values[-1] - values[0]
    if span <= 1.0e-12:
        return 1.0
    decrease = sum(max(0.0, values[index] - values[index + 1]) for index in range(len(values) - 1))
    return decrease / span


def extract_ribbon(component, matrix, relaxed=False):
    cycle = boundary_cycle(component)
    if cycle is None:
        return None, "边界不是单一闭环"
    arclength = shell_arclength_field(component)
    runs = split_cycle_into_rails(cycle, arclength)
    if runs is None or len(runs) < 2:
        return None, "无法切分出两条边界线"
    runs.sort(key=run_length, reverse=True)
    ratio = RAIL_LENGTH_RATIO * (0.4 if relaxed else 1.0)
    allowance = BACKTRACK_ALLOWANCE * (4.0 if relaxed else 1.0)
    if run_length(runs[1]) < run_length(runs[0]) * ratio:
        return None, "两条边界线长度悬殊，可能是多分支"
    for run in runs[:2]:
        if backtrack_ratio(run, arclength) > allowance:
            return None, "边界线折返，属于多分支头发，需要手动拆分"
    left = [matrix @ vertex.co for vertex in runs[0]]
    right = [matrix @ vertex.co for vertex in runs[1]]
    if arclength.get(runs[0][0], 0.0) > arclength.get(runs[0][-1], 0.0):
        left.reverse()
    if arclength.get(runs[1][0], 0.0) > arclength.get(runs[1][-1], 0.0):
        right.reverse()
    if (left[0] - right[0]).length + (left[-1] - right[-1]).length > \
       (left[0] - right[-1]).length + (left[-1] - right[0]).length:
        right.reverse()
    return (left, right), None


def polyline_parameters(points):
    parameters = [0.0]
    for index in range(len(points) - 1):
        parameters.append(parameters[-1] + (points[index + 1] - points[index]).length)
    total = parameters[-1]
    if total <= 1.0e-12:
        return [0.0 for _ in parameters], 0.0
    return [value / total for value in parameters], total


def evaluate_polyline(points, parameters, target):
    if target <= parameters[0]:
        return points[0].copy()
    if target >= parameters[-1]:
        return points[-1].copy()
    for index in range(len(parameters) - 1):
        low, high = parameters[index], parameters[index + 1]
        if low <= target <= high:
            span = high - low
            factor = 0.0 if span <= 1.0e-15 else (target - low) / span
            return points[index] + (points[index + 1] - points[index]) * factor
    return points[-1].copy()


def pair_rails(left_points, right_points):
    left_parameters, left_length = polyline_parameters(left_points)
    right_parameters, right_length = polyline_parameters(right_points)
    if left_length <= 1.0e-12 or right_length <= 1.0e-12:
        return []
    merged = []
    for value in sorted(set(left_parameters + right_parameters)):
        if merged and value - merged[-1] < 1.0e-4:
            continue
        merged.append(value)
    return [(value,
             evaluate_polyline(left_points, left_parameters, value),
             evaluate_polyline(right_points, right_parameters, value))
            for value in merged]


def is_cut_end(outer, middle, inner, reference):
    if outer >= reference * PINCH_TIP_FRACTION:
        return False
    if middle <= reference * PINCH_JUMP_FRACTION:
        return False
    return abs(middle - inner) < reference * PINCH_FLATNESS_FRACTION


def open_pinched_rails(left, right):
    for _ in range(4):
        if len(left) < 5 or len(right) < 5:
            break
        sections = pair_rails(left, right)
        if len(sections) < 4:
            break
        widths = [(entry[2] - entry[1]).length for entry in sections]
        reference = max(widths)
        if reference <= 1.0e-12:
            break
        if is_cut_end(widths[0], widths[1], widths[2], reference):
            left = left[1:]
            right = right[1:]
            continue
        if is_cut_end(widths[-1], widths[-2], widths[-3], reference):
            left = left[:-1]
            right = right[:-1]
            continue
        break
    return left, right


def strand_frames(cross_sections):
    centers = [(left + right) * 0.5 for _, left, right in cross_sections]
    widths = [(right - left).length for _, left, right in cross_sections]
    count = len(centers)
    tangents = []
    for index in range(count):
        if index == 0:
            tangent = centers[1] - centers[0]
        elif index == count - 1:
            tangent = centers[-1] - centers[-2]
        else:
            tangent = centers[index + 1] - centers[index - 1]
        if tangent.length <= 1.0e-12:
            tangent = Vector((0.0, 0.0, 1.0))
        tangents.append(tangent.normalized())
    reference = max(widths) if widths else 0.0
    raw = []
    for index in range(count):
        _, left, right = cross_sections[index]
        axis = right - left
        if reference <= 1.0e-12 or axis.length < reference * DIRECTION_VALID_FRACTION:
            raw.append(None)
            continue
        tangent = tangents[index]
        axis = axis - tangent * axis.dot(tangent)
        raw.append(None if axis.length <= 1.0e-12 else axis.normalized())
    valid = [index for index in range(count) if raw[index] is not None]
    if not valid:
        raw = [tangents[index].orthogonal().normalized() for index in range(count)]
        valid = list(range(count))
    directions = []
    for index in range(count):
        source = raw[index]
        if source is None:
            source = raw[min(valid, key=lambda candidate: abs(candidate - index))]
        tangent = tangents[index]
        axis = source - tangent * source.dot(tangent)
        if axis.length <= 1.0e-12:
            axis = tangent.orthogonal()
        directions.append(axis.normalized())
    return centers, widths, tangents, directions


class Strand:
    def __init__(self, left, right, shell_faces, shell_indices, vertex_count):
        left, right = open_pinched_rails(left, right)
        self.left = left
        self.right = right
        self.shells = [shell_faces]
        self.shell_indices = shell_indices
        self.vertex_count = vertex_count
        self.rebuild()
        if self.centers[0].z < self.centers[-1].z:
            self.left.reverse()
            self.right.reverse()
            self.rebuild()

    def rebuild(self):
        self.cross_sections = pair_rails(self.left, self.right)
        centers, widths, tangents, directions = strand_frames(self.cross_sections)
        self.centers = centers
        self.widths = widths
        self.tangents = tangents
        self.directions = directions

    @property
    def mean_width(self):
        return sum(self.widths) / len(self.widths)

    @property
    def faces(self):
        merged = []
        for shell in self.shells:
            merged.extend(shell)
        return merged


def edge_connected_groups(faces, blocked=None):
    blocked = blocked or set()
    remaining = set(faces)
    groups = []
    while remaining:
        seed = ordered(remaining)[0]
        remaining.discard(seed)
        stack = [seed]
        group = {seed}
        while stack:
            face = stack.pop()
            for edge in face.edges:
                if edge in blocked:
                    continue
                for neighbour in edge.link_faces:
                    if neighbour in remaining:
                        remaining.discard(neighbour)
                        group.add(neighbour)
                        stack.append(neighbour)
        groups.append(group)
    return groups


def submesh_from_faces(faces):
    mesh = bmesh.new()
    lookup = {}
    for face in ordered(faces):
        for vertex in face.verts:
            if vertex not in lookup:
                lookup[vertex] = mesh.verts.new(vertex.co)
    mesh.verts.ensure_lookup_table()
    for face in faces:
        try:
            mesh.faces.new([lookup[vertex] for vertex in face.verts])
        except ValueError:
            continue
    mesh.faces.ensure_lookup_table()
    mesh.verts.index_update()
    return mesh


def rail_coincidence(first, second):
    points_a = first.left + first.right
    points_b = second.left + second.right
    hits_a = sum(1 for point in points_a
                 if any((point - other).length < PAIR_WELD_DISTANCE for other in points_b))
    hits_b = sum(1 for point in points_b
                 if any((point - other).length < PAIR_WELD_DISTANCE for other in points_a))
    return max(hits_a / float(len(points_a)), hits_b / float(len(points_b)))


def island_face_loops(island, matrix):
    faces = set()
    for vertex in island:
        faces.update(vertex.link_faces)
    return [[matrix @ vertex.co for vertex in face.verts] for face in ordered(faces)]


def ribbon_from_faces(faces, matrix, relaxed=False):
    sub = submesh_from_faces(faces)
    islands = shell_islands(sub)
    if len(islands) != 1:
        sub.free()
        return None
    ribbon, _ = extract_ribbon(islands[0], matrix, relaxed)
    if ribbon is None:
        sub.free()
        return None
    loops = island_face_loops(islands[0], matrix)
    size = len(islands[0])
    sub.free()
    return (ribbon, loops, size, set(faces))


TIP_ANGLE_LIMIT = 70.0


def corner_angle(face, vertex):
    verts = list(face.verts)
    index = verts.index(vertex)
    before = verts[index - 1].co - vertex.co
    after = verts[(index + 1) % len(verts)].co - vertex.co
    if before.length < 1.0e-12 or after.length < 1.0e-12:
        return 0.0
    return math.acos(max(-1.0, min(1.0, before.normalized().dot(after.normalized()))))


def angle_sum(vertex):
    return math.degrees(sum(corner_angle(face, vertex) for face in vertex.link_faces))


TIP_SHARP_ANGLE = 80.0
TIP_CROTCH_ANGLE = 270.0


def boundary_path_peak(angles, count, first, second):
    forward = [(first + step) % count for step in range((second - first) % count + 1)]
    backward = [(second + step) % count for step in range((first - second) % count + 1)]
    path = forward if len(forward) <= len(backward) else backward
    inner = [angles[index] for index in path[1:-1]]
    return max(inner) if inner else 0.0


def tip_clusters(island):
    cycle = boundary_cycle(island)
    if cycle is None:
        return None
    angles = [angle_sum(vertex) for vertex in cycle]
    marks = [index for index in range(len(cycle)) if angles[index] < TIP_SHARP_ANGLE]
    if not marks:
        return []
    count = len(cycle)
    parent = {index: index for index in marks}

    def root(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for first in range(len(marks)):
        for second in range(first + 1, len(marks)):
            if boundary_path_peak(angles, count, marks[first], marks[second]) < TIP_CROTCH_ANGLE:
                low, high = root(marks[first]), root(marks[second])
                if low != high:
                    parent[low] = high
    groups = {}
    for index in marks:
        groups.setdefault(root(index), []).append(index)
    representatives = []
    for members in groups.values():
        best = min(members, key=lambda index: angles[index])
        representatives.append(cycle[best])
    return representatives


def tip_vertices(island, limit=TIP_ANGLE_LIMIT):
    result = []
    for vertex in ordered(island):
        if not any(len(edge.link_faces) == 1 for edge in vertex.link_edges):
            continue
        if angle_sum(vertex) < limit:
            result.append(vertex)
    return result


CROTCH_ANGLE_SUM = 270.0
CROTCH_RIM_ANGLE = 45.0


class FacePatch(object):
    def __init__(self, faces):
        self.faces = set(faces)
        self.verts = set()
        self.edges = set()
        for face in self.faces:
            self.verts.update(face.verts)
            self.edges.update(face.edges)
        self.degree = {}
        for edge in self.edges:
            self.degree[edge] = sum(1 for face in edge.link_faces
                                    if face in self.faces)
        self.rim = set(edge for edge in self.edges if self.degree[edge] < 2)

    def interior_edges(self, vertex):
        return [edge for edge in ordered(vertex.link_edges)
                if edge in self.edges and self.degree[edge] == 2]

    def rim_edges(self, vertex):
        return [edge for edge in ordered(vertex.link_edges) if edge in self.rim]

    def linked_faces(self, edge):
        return [face for face in edge.link_faces if face in self.faces]

    def angle_sum(self, vertex):
        return math.degrees(sum(corner_angle(face, vertex)
                                for face in vertex.link_faces
                                if face in self.faces))

    def rim_angle(self, vertex):
        rim = self.rim_edges(vertex)
        if len(rim) != 2:
            return None
        first = rim[0].other_vert(vertex).co - vertex.co
        second = rim[1].other_vert(vertex).co - vertex.co
        if first.length < 1.0e-12 or second.length < 1.0e-12:
            return None
        return math.degrees(first.angle(second))

    def loop_step(self, edge, vertex):
        interior = self.interior_edges(vertex)
        if len(interior) + len(self.rim_edges(vertex)) != 4 or not interior:
            return None
        faces = set(self.linked_faces(edge))
        for other in interior:
            if other is edge:
                continue
            if not (set(self.linked_faces(other)) & faces):
                return other
        return None


def edge_direction(edge, vertex):
    span = edge.other_vert(vertex).co - vertex.co
    if span.length < 1.0e-12:
        return None
    return span.normalized()


def crotch_vertices(patch):
    result = []
    for vertex in ordered(patch.verts):
        if len(patch.rim_edges(vertex)) != 2:
            continue
        if patch.angle_sum(vertex) < CROTCH_ANGLE_SUM:
            continue
        angle = patch.rim_angle(vertex)
        if angle is None or angle > CROTCH_RIM_ANGLE:
            continue
        result.append(vertex)
    return result


def inward_direction(patch, vertex):
    rim = patch.rim_edges(vertex)
    first = edge_direction(rim[0], vertex)
    second = edge_direction(rim[1], vertex)
    if first is None or second is None:
        return None
    span = first + second
    if span.length < 1.0e-9:
        return None
    return -span.normalized()


def crotch_start_edge(patch, crotch):
    inward = inward_direction(patch, crotch)
    if inward is None:
        return None
    best = None
    for edge in patch.interior_edges(crotch):
        span = edge_direction(edge, crotch)
        if span is None:
            continue
        score = span.dot(inward)
        if best is None or score > best[0]:
            best = (score, edge)
    if best is None or best[0] <= 0.0:
        return None
    return best[1]


def walk_loop_cut(patch, crotch, start):
    chain = [start]
    visited = {start}
    node = start.other_vert(crotch)
    current = start
    while not patch.rim_edges(node):
        following = patch.loop_step(current, node)
        if following is None or following in visited:
            incoming = edge_direction(current, node)
            if incoming is None:
                return None
            best = None
            for other in patch.interior_edges(node):
                if other is current or other in visited:
                    continue
                span = edge_direction(other, node)
                if span is None:
                    continue
                score = -span.dot(incoming)
                if best is None or score > best[0]:
                    best = (score, other)
            if best is None or best[0] <= 0.0:
                return None
            following = best[1]
        visited.add(following)
        chain.append(following)
        node = following.other_vert(node)
        current = following
    return chain


def group_holds_tip(group, tips):
    return any(any(face in group for face in tip.link_faces) for tip in tips)


def split_patch_by_loops(patch, tips):
    local = [tip for tip in tips
             if any(face in patch.faces for face in tip.link_faces)]
    blocked = set()
    count = len(edge_connected_groups(patch.faces))
    for crotch in crotch_vertices(patch):
        start = crotch_start_edge(patch, crotch)
        if start is None:
            continue
        chain = walk_loop_cut(patch, crotch, start)
        if not chain:
            continue
        merged = blocked | set(chain)
        groups = edge_connected_groups(patch.faces, merged)
        if len(groups) <= count:
            continue
        if local and any(not group_holds_tip(group, local) for group in groups):
            continue
        blocked = merged
        count = len(groups)
    return edge_connected_groups(patch.faces, blocked)


def split_island_by_loops(island, matrix):
    faces = set()
    for vertex in island:
        faces.update(vertex.link_faces)
    clustered = tip_clusters(island)
    tips = clustered if clustered is not None else tip_vertices(island, TIP_ANGLE_LIMIT)
    entries = []
    for group in edge_connected_groups(faces):
        for piece in split_patch_by_loops(FacePatch(group), tips):
            entry = ribbon_from_faces(piece, matrix)
            if entry is None:
                entry = ribbon_from_faces(piece, matrix, True)
            if entry is not None:
                entries.append(entry)
    return entries


def collect_strands(source_object, split_branches=True):
    mesh = bmesh.new()
    mesh.from_mesh(source_object.data)
    mesh.verts.ensure_lookup_table()
    matrix = source_object.matrix_world
    rejected = []
    leftover = []
    entries = []
    for shell_index, island in enumerate(shell_islands(mesh)):
        loops = island_face_loops(island, matrix)
        if split_branches:
            found = split_island_by_loops(island, matrix)
        else:
            ribbon, _ = extract_ribbon(island, matrix)
            found = [(ribbon, loops, len(island), set())] if ribbon is not None else []
        if not found:
            rejected.append((shell_index, len(island), "无法提取为发片条带"))
            leftover.append(loops)
            continue
        covered = set()
        for entry in found:
            covered |= entry[3]
            entries.append((shell_index, entry))
        island_faces = set()
        for vertex in island:
            island_faces.update(vertex.link_faces)
        missing = island_faces - covered
        if missing and covered:
            leftover.append([[matrix @ vertex.co for vertex in face.verts]
                             for face in ordered(missing)])
    candidates = []
    for shell_index, entry in entries:
        left, right = entry[0]
        candidates.append(Strand(left, right, entry[1], [shell_index], entry[2]))
    strands = []
    for candidate in sorted(candidates, key=lambda item: -len(item.centers)):
        merged = False
        for strand in strands:
            if rail_coincidence(strand, candidate) >= PAIR_COINCIDENCE_FRACTION:
                strand.shells.extend(candidate.shells)
                strand.shell_indices.extend(candidate.shell_indices)
                strand.vertex_count += candidate.vertex_count
                merged = True
                break
        if not merged:
            strands.append(candidate)
    mesh.free()
    return strands, rejected, leftover


def slice_faces_with_plane(faces, origin, normal, limit):
    points = []
    for loop in faces:
        signed = [(vertex - origin).dot(normal) for vertex in loop]
        size = len(loop)
        for index in range(size):
            following = (index + 1) % size
            first, second = signed[index], signed[following]
            if (first > 0.0) == (second > 0.0):
                continue
            gap = first - second
            if abs(gap) < 1.0e-15:
                continue
            hit = loop[index] + (loop[following] - loop[index]) * (first / gap)
            if (hit - origin).length > limit:
                continue
            points.append(hit)
    return points


def simplify_polyline(points, tolerance):
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    direction = (end[0] - start[0], end[1] - start[1])
    length = math.hypot(direction[0], direction[1])
    worst_index = 0
    worst_distance = -1.0
    for index in range(1, len(points) - 1):
        point = points[index]
        if length <= 1.0e-15:
            distance = math.hypot(point[0] - start[0], point[1] - start[1])
        else:
            distance = abs(direction[0] * (start[1] - point[1]) -
                           (start[0] - point[0]) * direction[1]) / length
        if distance > worst_distance:
            worst_index = index
            worst_distance = distance
    if worst_distance <= tolerance:
        return [start, end]
    return simplify_polyline(points[:worst_index + 1], tolerance)[:-1] + \
        simplify_polyline(points[worst_index:], tolerance)


def shell_cross_section(faces, origin, tangent, axis_x, axis_y, width):
    points = slice_faces_with_plane(faces, origin, tangent, width * SLICE_LIMIT_FACTOR)
    if len(points) < 2:
        return None
    planar = []
    for point in points:
        offset = point - origin
        planar.append((offset.dot(axis_x) / width, offset.dot(axis_y) / width))
    planar.sort(key=lambda entry: entry[0])
    merged = []
    for entry in planar:
        if merged and math.hypot(entry[0] - merged[-1][0], entry[1] - merged[-1][1]) < SLICE_MERGE_FRACTION:
            continue
        merged.append(entry)
    if len(merged) < 2:
        return None
    return merged


def cross_section_at(strand, frames, index):
    if strand.widths[index] <= 1.0e-9:
        return None
    axis_x, axis_y = frames[index]
    polylines = []
    for faces in strand.shells:
        section = shell_cross_section(faces, strand.centers[index], strand.tangents[index],
                                      axis_x, axis_y, strand.widths[index])
        if section is None:
            continue
        polylines.append(simplify_polyline(section, PROFILE_SIMPLIFY_FRACTION))
    return polylines or None


def strand_profile(strand, frames):
    order = sorted(range(len(strand.widths)), key=lambda index: -strand.widths[index])
    reference = max(strand.widths) if strand.widths else 0.0
    survey = [index for index in order
              if reference > 1.0e-12 and strand.widths[index] > reference * PROFILE_SURVEY_FRACTION]
    tally = {}
    cache = {}
    for index in survey[:PROFILE_SURVEY_LIMIT]:
        polylines = cross_section_at(strand, frames, index)
        if polylines is None:
            continue
        cache[index] = polylines
        tally[len(polylines)] = tally.get(len(polylines), 0) + 1
    if tally:
        dominant = max(tally.items(), key=lambda entry: (entry[1], entry[0]))[0]
        for index in survey:
            polylines = cache.get(index)
            if polylines is not None and len(polylines) == dominant:
                return polylines
    for index in order:
        polylines = cache.get(index)
        if polylines is None:
            polylines = cross_section_at(strand, frames, index)
        if polylines is not None:
            return polylines
    return None


def decimate_indices(strand, tolerance):
    samples = [(center.x, center.y, center.z, strand.widths[index])
               for index, center in enumerate(strand.centers)]

    def walk(low, high):
        if high - low < 2:
            return []
        start = samples[low]
        end = samples[high]
        direction = tuple(end[axis] - start[axis] for axis in range(4))
        length_squared = sum(value * value for value in direction)
        worst_index = low
        worst_distance = -1.0
        for index in range(low + 1, high):
            offset = tuple(samples[index][axis] - start[axis] for axis in range(4))
            if length_squared <= 1.0e-18:
                distance = math.sqrt(sum(value * value for value in offset))
            else:
                factor = sum(offset[axis] * direction[axis] for axis in range(4)) / length_squared
                factor = max(0.0, min(1.0, factor))
                residual = tuple(offset[axis] - direction[axis] * factor for axis in range(4))
                distance = math.sqrt(sum(value * value for value in residual))
            if distance > worst_distance:
                worst_index = index
                worst_distance = distance
        if worst_distance <= tolerance:
            return []
        return walk(low, worst_index) + [worst_index] + walk(worst_index, high)

    return [0] + walk(0, len(samples) - 1) + [len(samples) - 1]


def create_profile_object(name, polylines):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '2D'
    for polyline in polylines:
        spline = curve.splines.new('POLY')
        spline.points.add(len(polyline) - 1)
        for index, point in enumerate(polyline):
            spline.points[index].co = (point[0], point[1], 0.0, 1.0)
        spline.use_cyclic_u = False
    return bpy.data.objects.new(name, curve)


def create_probe_object(name):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '2D'
    spline = curve.splines.new('POLY')
    spline.points.add(2)
    for index, point in enumerate(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))):
        spline.points[index].co = (point[0], point[1], 0.0, 1.0)
    spline.use_cyclic_u = False
    return bpy.data.objects.new(name, curve)


def create_path_curve(name, centers, widths, profile_object, resolution):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '3D'
    curve.twist_mode = 'MINIMUM'
    curve.twist_smooth = 0.0
    curve.bevel_mode = 'OBJECT'
    curve.bevel_object = profile_object
    curve.use_fill_caps = False
    curve.use_path = True
    curve.resolution_u = resolution
    spline = curve.splines.new('NURBS')
    spline.points.add(len(centers) - 1)
    for index, center in enumerate(centers):
        point = spline.points[index]
        point.co = (center.x, center.y, center.z, 1.0)
        point.radius = widths[index]
        point.tilt = 0.0
    spline.order_u = min(PATH_ORDER, len(centers))
    spline.use_endpoint_u = True
    spline.use_cyclic_u = False
    spline.resolution_u = resolution
    spline.use_smooth = True
    return bpy.data.objects.new(name, curve)


def evaluate_probe(curve_object, probe_object, depsgraph):
    curve = curve_object.data
    original = curve.bevel_object
    curve.bevel_object = probe_object
    depsgraph.update()
    evaluated = curve_object.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    vertices = [vertex.co.copy() for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    curve.bevel_object = original
    readings = []
    for index in range(len(vertices) // 3):
        origin = vertices[3 * index]
        readings.append((origin,
                         vertices[3 * index + 1] - origin,
                         vertices[3 * index + 2] - origin))
    return readings


def measure_basis(curve_object, probe_object, depsgraph):
    points = curve_object.data.splines[0].points
    stored = [point.radius for point in points]
    columns = []
    for index in range(len(points)):
        for other, point in enumerate(points):
            point.radius = 1.0 if other == index else 0.0
        columns.append([reading[1].length for reading in
                        evaluate_probe(curve_object, probe_object, depsgraph)])
    for point, radius in zip(points, stored):
        point.radius = radius
    rows = len(columns[0])
    return [[columns[column][row] for column in range(len(columns))] for row in range(rows)]


def gaussian_solve(matrix, right):
    size = len(right)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1.0e-14:
            matrix[column][column] += 1.0e-9
            pivot = column
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        right[column], right[pivot] = right[pivot], right[column]
        for row in range(column + 1, size):
            factor = matrix[row][column] / matrix[column][column]
            if factor == 0.0:
                continue
            for inner in range(column, size):
                matrix[row][inner] -= factor * matrix[column][inner]
            right[row] -= factor * right[column]
    result = [0.0] * size
    for column in reversed(range(size)):
        total = right[column] - sum(matrix[column][inner] * result[inner]
                                    for inner in range(column + 1, size))
        result[column] = total / matrix[column][column]
    return result


def solve_least_squares(matrix, targets, weights=None):
    rows = len(matrix)
    columns = len(matrix[0])
    if weights is None:
        weights = [1.0] * rows
    normal = [[0.0] * columns for _ in range(columns)]
    for first in range(columns):
        for second in range(columns):
            normal[first][second] = sum(weights[row] * matrix[row][first] * matrix[row][second]
                                        for row in range(rows))
        normal[first][first] += REGULARIZATION
    solutions = []
    for target in targets:
        right = [sum(weights[row] * matrix[row][column] * target[row] for row in range(rows))
                 for column in range(columns)]
        solutions.append(gaussian_solve([row[:] for row in normal], right))
    return solutions


def centerline_parameters(centers):
    values = [0.0]
    for index in range(len(centers) - 1):
        values.append(values[-1] + (centers[index + 1] - centers[index]).length)
    total = values[-1]
    if total <= 1.0e-12:
        return [0.0 for _ in values]
    return [value / total for value in values]


def interpolate(values, parameters, target, blend):
    if target <= parameters[0]:
        return values[0]
    if target >= parameters[-1]:
        return values[-1]
    for index in range(len(parameters) - 1):
        low, high = parameters[index], parameters[index + 1]
        if low <= target <= high:
            span = high - low
            factor = 0.0 if span <= 1.0e-15 else (target - low) / span
            return blend(values[index], values[index + 1], factor)
    return values[-1]


def build_targets(strand, count):
    parameters = centerline_parameters(strand.centers)
    positions = []
    widths = []
    directions = []
    for index in range(count):
        value = index / float(count - 1)
        positions.append(interpolate(strand.centers, parameters, value,
                                     lambda a, b, f: a.lerp(b, f)))
        widths.append(interpolate(strand.widths, parameters, value,
                                  lambda a, b, f: a * (1.0 - f) + b * f))
        direction = interpolate(strand.directions, parameters, value,
                                lambda a, b, f: a * (1.0 - f) + b * f)
        tangent = interpolate(strand.tangents, parameters, value,
                              lambda a, b, f: a * (1.0 - f) + b * f)
        if tangent.length <= 1.0e-12:
            tangent = Vector((0.0, 0.0, 1.0))
        tangent = tangent.normalized()
        direction = direction - tangent * direction.dot(tangent)
        if direction.length <= 1.0e-12:
            direction = tangent.orthogonal()
        directions.append(direction.normalized())
    return positions, widths, directions


def unwrap(values):
    result = [values[0]]
    for value in values[1:]:
        previous = result[-1]
        while value - previous > math.pi:
            value -= 2.0 * math.pi
        while previous - value > math.pi:
            value += 2.0 * math.pi
        result.append(value)
    return result


def measure_tilt_error(readings, directions):
    deltas = []
    for index, reading in enumerate(readings):
        axis_x, axis_y = reading[1], reading[2]
        if axis_x.length <= 1.0e-12 or axis_y.length <= 1.0e-12:
            deltas.append(deltas[-1] if deltas else 0.0)
            continue
        target = directions[min(index, len(directions) - 1)]
        deltas.append(math.atan2(target.dot(axis_y.normalized()),
                                 target.dot(axis_x.normalized())))
    return deltas


def fit_path(curve_object, strand, probe_object, depsgraph):
    points = curve_object.data.splines[0].points
    basis = measure_basis(curve_object, probe_object, depsgraph)
    positions, widths, directions = build_targets(strand, len(basis))
    solutions = solve_least_squares(basis, [
        [position.x for position in positions],
        [position.y for position in positions],
        [position.z for position in positions],
        widths,
    ])
    for index, point in enumerate(points):
        point.co = (solutions[0][index], solutions[1][index], solutions[2][index], 1.0)
        point.radius = max(0.0, solutions[3][index])
    depsgraph.update()
    reference = max(widths) if widths else 0.0
    weights = [max(TILT_WEIGHT_FLOOR, width / reference) if reference > 1.0e-12 else 1.0
               for width in widths]
    significant = [index for index, width in enumerate(widths)
                   if reference > 1.0e-12 and width > reference * TILT_REPORT_FRACTION]
    for _ in range(TILT_ITERATIONS):
        deltas = unwrap(measure_tilt_error(
            evaluate_probe(curve_object, probe_object, depsgraph), directions))
        if max(abs(deltas[index]) for index in significant or range(len(deltas))) < 1.0e-4:
            break
        correction = solve_least_squares(basis, [deltas], weights)[0]
        for index, point in enumerate(points):
            point.tilt -= correction[index]
        depsgraph.update()
    readings = evaluate_probe(curve_object, probe_object, depsgraph)
    final = measure_tilt_error(readings, directions)
    residual = max(abs(final[index]) for index in significant or range(len(final)))
    return residual, readings


def frames_for_strand(strand, readings):
    if not readings:
        return [(Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)))] * len(strand.centers)
    parameters = centerline_parameters(strand.centers)
    frames = []
    for index in range(len(strand.centers)):
        position = min(len(readings) - 1,
                       int(round(parameters[index] * (len(readings) - 1))))
        span_x, span_y = readings[position][1], readings[position][2]
        if span_x.length <= 1.0e-12 or span_y.length <= 1.0e-12:
            for candidate in range(len(readings)):
                span_x, span_y = readings[candidate][1], readings[candidate][2]
                if span_x.length > 1.0e-12 and span_y.length > 1.0e-12:
                    break
        frames.append((span_x.normalized(), span_y.normalized()))
    return frames


def create_leftover_object(name, shells):
    vertices = []
    polygons = []
    for shell in shells:
        for loop in shell:
            start = len(vertices)
            vertices.extend(tuple(point) for point in loop)
            polygons.append(tuple(range(start, len(vertices))))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], polygons)
    mesh.update()
    return bpy.data.objects.new(name, mesh)


def ensure_collection(scene, name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


class SHIYUME_OT_HairToPath(bpy.types.Operator):
    """把头发面片转换成 Path（NURBS）曲线。
    每条头发单独一条曲线，并用它自己的横截面作为 Bevel Object，
    截面按每片壳拆成开放样条，所以生成的拓扑和原始面片同构。
    控制点的位置 / Radius / Tilt 由实测 NURBS 基函数最小二乘反解得到，
    保证求值出来的曲线本身贴合原网格，而不是让控制多边形贴合。
    多分支头发不支持，会原样导出到 HairToPath_NeedManualSplit 供手动拆分。"""
    bl_idname = "shiyume.hair_to_path"
    bl_label = "头发转路径曲线"
    bl_options = {'REGISTER', 'UNDO'}

    resolution: bpy.props.IntProperty(
        name="曲线分辨率",
        description="Path 曲线的 resolution_u，采样段数 =（控制点数 - 1）× 分辨率",
        default=3, min=1, max=24)

    control_tolerance: bpy.props.FloatProperty(
        name="控制点简化容差",
        description="按平均宽度的比例简化控制点。调小得到更多控制点与更高精度",
        default=0.10, min=0.0, max=1.0, precision=3)

    split_branches: bpy.props.BoolProperty(
        name="拆分多分支",
        description="对无法作为单条发片提取的面片做 Reeb 分解，按分叉切成独立发丝",
        default=True)

    export_unconverted: bpy.props.BoolProperty(
        name="导出未转换面片",
        description="把多分支等无法转换的面片原样导出成网格，方便手动拆分后重跑",
        default=True)

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        scene = context.scene
        sources = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not sources:
            self.report({'ERROR'}, "没有选中网格物体")
            return {'CANCELLED'}

        curve_collection = ensure_collection(scene, "HairToPath_Curves")
        profile_collection = ensure_collection(scene, "HairToPath_Profiles")
        leftover_collection = ensure_collection(scene, "HairToPath_NeedManualSplit")

        probe = create_probe_object("HairToPath_FrameProbe")
        scene.collection.objects.link(probe)
        depsgraph = context.evaluated_depsgraph_get()

        built = 0
        skipped = 0
        residuals = []
        try:
            for source in sources:
                strands, rejected, leftover = collect_strands(source, self.split_branches)
                skipped += len(rejected)
                if leftover and self.export_unconverted:
                    unconverted = create_leftover_object(source.name + "_Unconverted", leftover)
                    leftover_collection.objects.link(unconverted)
                for order, strand in enumerate(strands):
                    label = "%s_S%02d" % (source.name, order)
                    placeholder = create_profile_object(
                        label + "_ProfileTemp",
                        [[(-0.5, 0.0), (0.0, -0.1), (0.5, 0.0)],
                         [(0.5, 0.0), (0.0, 0.1), (-0.5, 0.0)]])
                    scene.collection.objects.link(placeholder)
                    indices = decimate_indices(strand, strand.mean_width * self.control_tolerance)
                    curve_object = create_path_curve(
                        label + "_Curve",
                        [strand.centers[index] for index in indices],
                        [strand.widths[index] for index in indices],
                        placeholder, self.resolution)
                    curve_collection.objects.link(curve_object)
                    residual, readings = fit_path(curve_object, strand, probe, depsgraph)
                    residuals.append(residual)
                    polylines = strand_profile(strand, frames_for_strand(strand, readings))
                    if polylines is None:
                        bpy.data.objects.remove(placeholder)
                        bpy.data.objects.remove(curve_object)
                        skipped += 1
                        continue
                    profile_object = create_profile_object(label + "_Profile", polylines)
                    profile_collection.objects.link(profile_object)
                    profile_object.hide_viewport = True
                    profile_object.hide_render = True
                    curve_object.data.bevel_object = profile_object
                    for material in source.data.materials:
                        curve_object.data.materials.append(material)
                    bpy.data.objects.remove(placeholder)
                    built += 1
        finally:
            bpy.data.objects.remove(probe)

        depsgraph.update()
        ranked = sorted(residuals)
        median = ranked[len(ranked) // 2] if ranked else 0.0
        worst = ranked[-1] if ranked else 0.0
        self.report({'INFO'}, "生成 %d 条路径曲线，跳过 %d 片，Tilt 残差 中位 %.1f 度 / 最大 %.1f 度" % (
            built, skipped, math.degrees(median), math.degrees(worst)))
        return {'FINISHED'} if built else {'CANCELLED'}
