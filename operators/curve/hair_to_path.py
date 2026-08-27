import bmesh
import bpy
import heapq
import math

from mathutils import Vector

RAIL_DIRECTION_THRESHOLD = 0.5
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
SEAM_SPLIT_DEPTH = 3
SEAM_REFINE_ROUNDS = 4
SEAM_WIDTH_MEDIAN_LIMIT = 2.4
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


def closest_point_on_polyline(points, target):
    best = (points[0], 1.0e30, 0, 0.0)
    for index in range(len(points) - 1):
        start = points[index]
        direction = points[index + 1] - start
        length_squared = direction.length_squared
        if length_squared <= 1.0e-24:
            continue
        factor = max(0.0, min(1.0, (target - start).dot(direction) / length_squared))
        candidate = start + direction * factor
        distance = (candidate - target).length
        if distance < best[1]:
            best = (candidate, distance, index, factor)
    return best


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


class Union:
    def __init__(self, items=()):
        self.parent = {item: item for item in items}

    def add(self, item):
        if item not in self.parent:
            self.parent[item] = item

    def root(self, item):
        self.add(item)
        while self.parent[item] is not item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def join(self, first, second):
        a, b = self.root(first), self.root(second)
        if a is not b:
            self.parent[a] = b


def opposite_edge(face, edge):
    if len(face.verts) != 4:
        return None
    corners = set(edge.verts)
    for other in face.edges:
        if other is edge:
            continue
        if not (set(other.verts) & corners):
            return other
    return None


def edge_rings(faces):
    union = Union()
    for face in ordered(faces):
        if len(face.verts) != 4:
            continue
        for edge in face.edges:
            union.add(edge)
            partner = opposite_edge(face, edge)
            if partner is not None:
                union.join(edge, partner)
    rings = {}
    for face in ordered(faces):
        for edge in ordered(face.edges):
            union.add(edge)
            rings.setdefault(union.root(edge), set()).add(edge)
    ring_of = {}
    for key, group in rings.items():
        for edge in group:
            ring_of[edge] = key
    return ring_of, {key: len(group) for key, group in rings.items()}


def classify_rungs(faces):
    ring_of, ring_size = edge_rings(faces)
    votes = {}
    for face in ordered(faces):
        if len(face.verts) != 4:
            continue
        sizes = {}
        for edge in face.edges:
            sizes.setdefault(ring_of[edge], []).append(edge)
        if len(sizes) != 2:
            continue
        ranked = sorted(sizes.items(), key=lambda entry: ring_size[entry[0]])
        for edge in ranked[0][1]:
            votes[edge] = votes.get(edge, 0) - 1
        for edge in ranked[1][1]:
            votes[edge] = votes.get(edge, 0) + 1
    return set(edge for edge, value in votes.items() if value > 0)


def face_bands(faces, rungs):
    union = Union(ordered(faces))
    for face in ordered(faces):
        for edge in face.edges:
            if edge in rungs:
                continue
            for neighbour in edge.link_faces:
                if neighbour is not face and neighbour in faces:
                    union.join(face, neighbour)
    groups = {}
    for face in ordered(faces):
        groups.setdefault(union.root(face), []).append(face)
    bands = [set(group) for group in groups.values()]
    band_of = {}
    for index, band in enumerate(bands):
        for face in band:
            band_of[face] = index
    return bands, band_of


def band_links(band_of, rungs):
    links = {}
    for edge in rungs:
        touching = sorted(set(band_of[face] for face in edge.link_faces if face in band_of))
        for first in range(len(touching)):
            for second in range(first + 1, len(touching)):
                links.setdefault(touching[first], set()).add(touching[second])
                links.setdefault(touching[second], set()).add(touching[first])
    return links


def decompose_by_rings(component):
    faces = set()
    for vertex in component:
        faces.update(vertex.link_faces)
    rungs = classify_rungs(faces)
    if not rungs:
        return [faces]
    bands, band_of = face_bands(faces, rungs)
    links = band_links(band_of, rungs)
    junctions = set(index for index in range(len(bands)) if len(links.get(index, ())) > 2)
    if not junctions:
        return [faces]
    free = [index for index in range(len(bands)) if index not in junctions]
    union = Union(free)
    for index in free:
        for other in links.get(index, ()):
            if other not in junctions:
                union.join(index, other)
    groups = {}
    for index in free:
        groups.setdefault(union.root(index), []).append(index)
    pieces = []
    for members in groups.values():
        collected = set()
        for index in members:
            collected |= bands[index]
        pieces.append((set(members), collected))
    for index in junctions:
        attached = [entry for entry in pieces if links.get(index, set()) & entry[0]]
        if attached:
            max(attached, key=lambda entry: len(entry[1]))[1].update(bands[index])
        else:
            pieces.append(({index}, set(bands[index])))
    return [entry[1] for entry in pieces]


def edge_connected_groups(faces):
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


def columns_of(faces, rungs):
    parent = {face: face for face in ordered(faces)}

    def root(item):
        while parent[item] is not item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for face in ordered(faces):
        for edge in ordered(face.edges):
            if edge not in rungs:
                continue
            for neighbour in ordered(edge.link_faces):
                if neighbour is not face and neighbour in faces:
                    first, second = root(face), root(neighbour)
                    if first is not second:
                        parent[first] = second
    groups = {}
    for face in ordered(faces):
        groups.setdefault(root(face), []).append(face)
    return [set(group) for group in groups.values()]


def column_links(columns):
    index_of = {}
    for index, column in enumerate(columns):
        for face in ordered(column):
            index_of[face] = index
    links = {}
    for face in ordered(index_of):
        index = index_of[face]
        for edge in face.edges:
            for neighbour in edge.link_faces:
                other = index_of.get(neighbour)
                if other is None or other == index:
                    continue
                links.setdefault(index, set()).add(other)
    return links


def column_orders(columns, links):
    if not columns:
        return []
    ends = [index for index in range(len(columns)) if len(links.get(index, ())) <= 1]
    orders = []
    for start in (ends or [0])[:2]:
        order = [start]
        seen = {start}
        while True:
            following = None
            for other in sorted(links.get(order[-1], ())):
                if other not in seen:
                    following = other
                    break
            if following is None:
                break
            order.append(following)
            seen.add(following)
        if len(order) == len(columns):
            orders.append(order)
    if not orders:
        orders.append(list(range(len(columns))))
    return orders


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


def ribbon_width(entry):
    left, right = entry[0]
    sections = pair_rails(left, right)
    if not sections:
        return 0.0
    return max((section[2] - section[1]).length for section in sections)


def candidate_splits(faces, matrix):
    rungs = classify_rungs(faces)
    if not rungs:
        return []
    columns = columns_of(faces, rungs)
    if len(columns) < 2:
        return []
    links = column_links(columns)
    found = []
    for order in column_orders(columns, links):
        for cut in range(1, len(columns)):
            left = set()
            right = set()
            for position, index in enumerate(order):
                (left if position < cut else right).update(columns[index])
            if not left or not right:
                continue
            first = ribbon_from_faces(left, matrix)
            if first is None:
                continue
            second = ribbon_from_faces(right, matrix)
            if second is None:
                continue
            found.append((max(ribbon_width(first), ribbon_width(second)), first, second))
    found.sort(key=lambda entry: entry[0])
    return found


def split_faces(faces, matrix, depth):
    direct = ribbon_from_faces(faces, matrix)
    if direct is not None:
        return [direct]
    if depth > 0:
        found = candidate_splits(faces, matrix)
        if found:
            return [found[0][1], found[0][2]]
        rungs = classify_rungs(faces)
        columns = columns_of(faces, rungs) if rungs else []
        if len(columns) >= 2:
            links = column_links(columns)
            for order in column_orders(columns, links):
                for cut in range(1, len(columns)):
                    left = set()
                    right = set()
                    for position, index in enumerate(order):
                        (left if position < cut else right).update(columns[index])
                    if not left or not right:
                        continue
                    first = split_faces(left, matrix, depth - 1)
                    if not first:
                        continue
                    second = split_faces(right, matrix, depth - 1)
                    if not second:
                        continue
                    return first + second
    loose = ribbon_from_faces(faces, matrix, True)
    return [loose] if loose is not None else []


def split_island(island, matrix):
    faces = set()
    for vertex in island:
        faces.update(vertex.link_faces)
    return split_faces(faces, matrix, SEAM_SPLIT_DEPTH)


def refine_by_width(entries, matrix, limit):
    result = list(entries)
    for _ in range(SEAM_REFINE_ROUNDS):
        changed = False
        expanded = []
        for entry in result:
            if ribbon_width(entry) <= limit:
                expanded.append(entry)
                continue
            found = candidate_splits(entry[3], matrix)
            if found:
                expanded.extend((found[0][1], found[0][2]))
                changed = True
            else:
                expanded.append(entry)
        result = expanded
        if not changed:
            break
    return result


TIP_ANGLE_LIMIT = 70.0
OPPOSITE_END_SPREAD = 0.5
HAIRPIN_ANGLE = 110.0
HAIRPIN_MARGIN = 0.2
TIP_PREFERENCE = "min"
TIP_LADDER_SLACK = 1
PIECE_BALANCE_FLOOR = 0.55


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
TIP_BUILDER_ORDER = "partition_with_tips,grow_with_tips,grow_faces_from_tips"


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


def partitions(counts, target):
    results = []

    def walk(position, remaining, current, started):
        if remaining == 0:
            if position == len(counts):
                results.append(list(current))
            return
        total = 0
        for end in range(position, len(counts)):
            total += counts[end]
            if total > 1:
                break
            if total == 1:
                current.append((position, end + 1))
                walk(end + 1, remaining - 1, current, True)
                current.pop()
        return

    walk(0, target, [], False)
    return results


def fallback(faces, matrix):
    found = candidate_splits(faces, matrix)
    if found:
        return [found[0][1], found[0][2]]
    result = split_faces(faces, matrix, SEAM_SPLIT_DEPTH)
    return result if result else []


def tip_parameters(entry, tips, matrix):
    left, right = entry[0]
    sections = pair_rails(left, right)
    if len(sections) < 2:
        return []
    centers = [(section[1] + section[2]) * 0.5 for section in sections]
    values = []
    for tip in tips:
        point = matrix @ tip.co
        best = min(range(len(centers)), key=lambda index: (centers[index] - point).length)
        values.append(best / float(len(centers) - 1))
    return values


def tips_at_opposite_ends(entry, tips, matrix):
    values = tip_parameters(entry, tips, matrix)
    if len(values) < 2:
        return False
    return (max(values) - min(values)) > OPPOSITE_END_SPREAD


def share_edge(first, second):
    for face in first:
        for edge in face.edges:
            for neighbour in edge.link_faces:
                if neighbour in second:
                    return True
    return False


def merge_to_target(entries, matrix, target):
    result = list(entries)
    while len(result) > target:
        best = None
        for first in range(len(result)):
            for second in range(first + 1, len(result)):
                if not share_edge(result[first][3], result[second][3]):
                    continue
                merged = ribbon_from_faces(result[first][3] | result[second][3], matrix)
                if merged is None:
                    continue
                score = ribbon_width(merged)
                if best is None or score < best[0]:
                    best = (score, first, second, merged)
        if best is None:
            break
        _, first, second, merged = best
        result = [entry for index, entry in enumerate(result)
                  if index not in (first, second)] + [merged]
    return result


TIP_LIMIT_LADDER = (45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0)


def grow_faces_from_tips(faces, matrix, tips):
    if len(tips) < 2:
        return None
    centre = {}
    for face in ordered(faces):
        centre[face] = sum((vertex.co for vertex in face.verts), Vector()) / len(face.verts)
    seeds = {}
    for order, tip in enumerate(tips):
        best = None
        for face in tip.link_faces:
            if face not in centre:
                continue
            distance = (centre[face] - tip.co).length
            if best is None or distance < best[0]:
                best = (distance, face)
        if best is None:
            return None
        if best[1] in seeds:
            return None
        seeds[best[1]] = order
    queue = []
    label = {}
    for face, order in seeds.items():
        label[face] = order
        heapq.heappush(queue, (0.0, face.index, face))
    cost = {face: 0.0 for face in seeds}
    while queue:
        value, _, face = heapq.heappop(queue)
        if value > cost.get(face, 1.0e30) + 1.0e-12:
            continue
        for edge in ordered(face.edges):
            for neighbour in ordered(edge.link_faces):
                if neighbour is face or neighbour not in centre:
                    continue
                step = value + (centre[neighbour] - centre[face]).length
                if step < cost.get(neighbour, 1.0e30) - 1.0e-12:
                    cost[neighbour] = step
                    label[neighbour] = label[face]
                    heapq.heappush(queue, (step, neighbour.index, neighbour))
    if len(label) < len(faces):
        return None
    groups = {}
    for face, order in label.items():
        groups.setdefault(order, set()).add(face)
    if len(groups) != len(tips):
        return None
    produced = []
    for order in sorted(groups):
        entry = ribbon_from_faces(groups[order], matrix)
        if entry is None:
            return None
        produced.append(entry)
    return produced


def partition_with_tips(faces, island, matrix, tips):
    return try_partition(faces, island, matrix, None, tips)


def grow_with_tips(faces, island, matrix, tips):
    return grow_from_tips(faces, island, matrix, None, tips)


def try_partition(faces, island, matrix, limit, marks=None):
    tips = marks if marks is not None else tip_vertices(island, limit)
    target = len(tips)
    if target < 2:
        return None, target
    rungs = classify_rungs(faces)
    if not rungs:
        return None, target
    columns = columns_of(faces, rungs)
    if len(columns) < target:
        return None, target
    index_of = {}
    for index, column in enumerate(columns):
        for face in column:
            index_of[face] = index
    tally = [0] * len(columns)
    for tip in tips:
        votes = {}
        for face in tip.link_faces:
            position = index_of.get(face)
            if position is not None:
                votes[position] = votes.get(position, 0) + 1
        if votes:
            tally[max(votes.items(), key=lambda entry: (entry[1], -entry[0]))[0]] += 1
    links = column_links(columns)
    best = None
    for order in column_orders(columns, links):
        counts = [tally[index] for index in order]
        if sum(counts) != target:
            continue
        for spans in partitions(counts, target):
            pieces = []
            for start, stop in spans:
                collected = set()
                for position in range(start, stop):
                    collected |= columns[order[position]]
                pieces.append(collected)
            ribbons = [ribbon_from_faces(piece, matrix) for piece in pieces]
            if any(entry is None for entry in ribbons):
                continue
            score = max(ribbon_width(entry) for entry in ribbons)
            if best is None or score < best[0]:
                best = (score, ribbons)
    if marks is not None:
        return best[1] if best else None
    return (best[1] if best else None), target


def hairpin_split(entry, matrix):
    left, right = entry[0]
    sections = pair_rails(left, right)
    if len(sections) < 8:
        return None
    centers = [(section[1] + section[2]) * 0.5 for section in sections]
    step = max(1, len(centers) // 8)
    worst = 0.0
    position = None
    for index in range(step, len(centers) - step):
        before = centers[index] - centers[index - step]
        after = centers[index + step] - centers[index]
        if before.length < 1.0e-9 or after.length < 1.0e-9:
            continue
        value = math.degrees(before.angle(after))
        parameter = index / float(len(centers) - 1)
        if value > worst and HAIRPIN_MARGIN < parameter < 1.0 - HAIRPIN_MARGIN:
            worst = value
            position = index
    if position is None or worst < HAIRPIN_ANGLE:
        return None
    faces = entry[3]
    rungs = classify_rungs(faces)
    if not rungs:
        return None
    bands, band_of = face_bands(faces, rungs)
    ranking = []
    for index, band in enumerate(bands):
        total = 0.0
        for face in band:
            centre = sum((matrix @ vertex.co for vertex in face.verts), Vector()) / len(face.verts)
            nearest = min(range(len(centers)),
                          key=lambda position: (centers[position] - centre).length)
            total += nearest
        ranking.append((total / len(band), index))
    ranking.sort()
    best = None
    for cut in range(1, len(ranking)):
        first = set()
        second = set()
        for order, (_, index) in enumerate(ranking):
            (first if order < cut else second).update(bands[index])
        if not first or not second:
            continue
        pieces = [ribbon_from_faces(first, matrix), ribbon_from_faces(second, matrix)]
        if any(piece is None for piece in pieces):
            continue
        distance = abs(ranking[cut][0] - position)
        if best is None or distance < best[0]:
            best = (distance, pieces)
    return best[1] if best else None


def grow_from_tips(faces, island, matrix, limit, given=None):
    marks = given if given is not None else tip_vertices(island, limit)
    if len(marks) < 2:
        return None
    rungs = classify_rungs(faces)
    if not rungs:
        return None
    columns = columns_of(faces, rungs)
    if len(columns) < len(marks):
        return None
    index_of = {}
    for index, column in enumerate(columns):
        for face in column:
            index_of[face] = index
    seeds = {}
    for order, tip in enumerate(marks):
        votes = {}
        for face in tip.link_faces:
            position = index_of.get(face)
            if position is not None:
                votes[position] = votes.get(position, 0) + 1
        if not votes:
            return None
        column = max(votes.items(), key=lambda entry: (entry[1], -entry[0]))[0]
        if column in seeds:
            return None
        seeds[column] = order
    links = column_links(columns)
    label = dict(seeds)
    frontier = sorted(seeds)
    while frontier:
        following = []
        for index in frontier:
            for other in sorted(links.get(index, ())):
                if other in label:
                    continue
                label[other] = label[index]
                following.append(other)
        frontier = sorted(following)
    if len(label) < len(columns):
        return None
    groups = {}
    for index, owner in label.items():
        groups.setdefault(owner, set()).update(columns[index])
    if len(groups) != len(marks):
        return None
    ribbons = []
    for owner in sorted(groups):
        entry = ribbon_from_faces(groups[owner], matrix)
        if entry is None:
            return None
        ribbons.append(entry)
    return ribbons


def solution_cost(pieces):
    return max(ribbon_width(entry) for entry in pieces)


def solution_balance(pieces):
    widths = [ribbon_width(entry) for entry in pieces]
    top = max(widths)
    if top <= 1.0e-12:
        return 0.0
    return min(widths) / top


def split_by_tips_ladder(island, matrix):
    faces = set()
    for vertex in island:
        faces.update(vertex.link_faces)
    whole = ribbon_from_faces(faces, matrix)
    clustered = tip_clusters(island)
    tips = clustered if clustered is not None else tip_vertices(island, TIP_ANGLE_LIMIT)
    if len(tips) <= 1 and whole is not None:
        return [whole]
    if len(tips) >= 2 and whole is not None and tips_at_opposite_ends(whole, tips, matrix):
        folded = hairpin_split(whole, matrix)
        return folded if folded else [whole]
    solutions = []
    if len(tips) == 1 and whole is None:
        loose = ribbon_from_faces(faces, matrix, True)
        if loose is not None:
            return [loose]
    if len(tips) >= 2:
        options = []
        for builder in (partition_with_tips, grow_with_tips):
            produced = builder(faces, island, matrix, tips)
            if produced:
                options.append((builder.__name__, produced))
        produced = grow_faces_from_tips(faces, matrix, tips)
        if produced:
            options.append(("grow_faces_from_tips", produced))
        if options:
            if TIP_BUILDER_ORDER == "cost":
                options.sort(key=lambda entry: solution_cost(entry[1]))
            else:
                rank = TIP_BUILDER_ORDER.split(",")
                options.sort(key=lambda entry: rank.index(entry[0])
                             if entry[0] in rank else len(rank))
            return options[0][1]
    ceiling = len(tips)
    for limit in TIP_LIMIT_LADDER:
        if len(tip_vertices(island, limit)) > ceiling + TIP_LADDER_SLACK:
            continue
        pieces, target = try_partition(faces, island, matrix, limit)
        if pieces:
            solutions.append((solution_cost(pieces), len(pieces), pieces))
            continue
        grown = grow_from_tips(faces, island, matrix, limit)
        if grown:
            solutions.append((solution_cost(grown), len(grown), grown))
    if solutions:
        if TIP_PREFERENCE == "balanced":
            eligible = [entry for entry in solutions
                        if solution_balance(entry[2]) >= PIECE_BALANCE_FLOOR]
            if eligible:
                eligible.sort(key=lambda entry: (-entry[1], entry[0]))
                return eligible[0][2]
            solutions.sort(key=lambda entry: entry[1])
        elif TIP_PREFERENCE == "narrow":
            solutions.sort(key=lambda entry: (entry[0], entry[1]))
        elif TIP_PREFERENCE == "max":
            solutions.sort(key=lambda entry: -entry[1])
        else:
            solutions.sort(key=lambda entry: entry[1])
        return solutions[0][2]
    if whole is not None:
        return [whole]
    loose = fallback(faces, matrix)
    if len(tips) >= 2 and len(loose) > len(tips):
        loose = merge_to_target(loose, matrix, len(tips))
    return loose


def split_by_tips(island, matrix, limit=TIP_ANGLE_LIMIT):
    faces = set()
    for vertex in island:
        faces.update(vertex.link_faces)
    tips = tip_vertices(island, limit)
    target = len(tips)
    whole = ribbon_from_faces(faces, matrix)
    if target <= 1:
        if whole is not None:
            return [whole]
        loose = ribbon_from_faces(faces, matrix, True)
        if loose is not None:
            return [loose]
        return fallback(faces, matrix)
    if whole is not None and tips_at_opposite_ends(whole, tips, matrix):
        return [whole]
    rungs = classify_rungs(faces)
    if not rungs:
        return [whole] if whole is not None else fallback(faces, matrix)
    columns = columns_of(faces, rungs)
    if len(columns) < target:
        return [whole] if whole is not None else fallback(faces, matrix)
    index_of = {}
    for index, column in enumerate(columns):
        for face in column:
            index_of[face] = index
    tally = [0] * len(columns)
    for tip in tips:
        votes = {}
        for face in tip.link_faces:
            position = index_of.get(face)
            if position is not None:
                votes[position] = votes.get(position, 0) + 1
        if votes:
            tally[max(votes.items(), key=lambda entry: (entry[1], -entry[0]))[0]] += 1
    links = column_links(columns)
    best = None
    for order in column_orders(columns, links):
        counts = [tally[index] for index in order]
        if sum(counts) != target:
            continue
        for spans in partitions(counts, target):
            pieces = []
            for start, stop in spans:
                collected = set()
                for position in range(start, stop):
                    collected |= columns[order[position]]
                pieces.append(collected)
            ribbons = [ribbon_from_faces(piece, matrix) for piece in pieces]
            if any(entry is None for entry in ribbons):
                continue
            score = max(ribbon_width(entry) for entry in ribbons)
            if best is None or score < best[0]:
                best = (score, ribbons)
    if best is not None:
        return best[1]
    loose = fallback(faces, matrix)
    if len(loose) > target:
        loose = merge_to_target(loose, matrix, target)
    if len(loose) >= 2:
        return loose
    if whole is not None:
        return [whole]
    return loose


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
            found = split_by_tips_ladder(island, matrix)
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
