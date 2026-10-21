import base64
import json
import zlib
from collections import deque
from contextlib import contextmanager

import bpy
import numpy as np

STRAND_ATTRIBUTE = "shiyume_hair_strand"
RING_ATTRIBUTE = "shiyume_hair_ring"
KEYS_PROPERTY = "shiyume_hair_strand_keys"
SNAPSHOT_PROPERTY = "shiyume_hair_snapshot"
DEFAULT_PREFIX = "HairToPath_"
MATCH_TOLERANCE = 2.0e-5
DEGENERATE_LENGTH = 1.0e-9
QUERY_CHUNK = 512


class Strand(object):
    """一根发丝：每个求值截面的原点、两根截面轴和这根发丝的截面轮廓点。"""

    def __init__(self, key, origins, axes_x, axes_y, profile):
        self.key = key
        self.origins = origins
        self.axes_x = axes_x
        self.axes_y = axes_y
        self.profile = profile
        self.basis = frame_basis(axes_x, axes_y)

    @property
    def ring_count(self):
        return len(self.origins)

    def ring_points(self):
        offsets_x = self.profile[None, :, 0, None] * self.axes_x[:, None, :]
        offsets_y = self.profile[None, :, 1, None] * self.axes_y[:, None, :]
        return self.origins[:, None, :] + offsets_x + offsets_y


def frame_basis(axes_x, axes_y):
    """截面轴补出法向得到 3x3 基（列 = X、Y、Z）。退化截面（发尖半径为零）借最近的好截面的方向。"""
    count = len(axes_x)
    length_x = np.linalg.norm(axes_x, axis=1)
    length_y = np.linalg.norm(axes_y, axis=1)
    normal = np.cross(axes_x, axes_y)
    length_normal = np.linalg.norm(normal, axis=1)
    valid = (length_x > DEGENERATE_LENGTH) & (length_y > DEGENERATE_LENGTH)         & (length_normal > DEGENERATE_LENGTH * DEGENERATE_LENGTH)
    basis = np.zeros((count, 3, 3))
    if not valid.any():
        basis[:] = np.eye(3)
        return basis
    unit_x = axes_x / np.where(valid, length_x, 1.0)[:, None]
    unit_y = axes_y / np.where(valid, length_y, 1.0)[:, None]
    unit_normal = normal / np.where(valid, length_normal, 1.0)[:, None]
    scale = np.where(valid, np.sqrt(np.where(valid, length_x * length_y, 1.0)), 1.0)[:, None]
    indices = np.arange(count)
    good = np.flatnonzero(valid)
    position = np.searchsorted(good, indices)
    after = good[np.clip(position, 0, len(good) - 1)]
    before = good[np.clip(position - 1, 0, len(good) - 1)]
    pick = np.where(np.abs(indices - before) <= np.abs(after - indices), before, after)
    pick = np.where(valid, indices, pick)
    basis[:, :, 0] = unit_x[pick] * scale
    basis[:, :, 1] = unit_y[pick] * scale
    basis[:, :, 2] = unit_normal[pick] * scale
    return basis


def unit_columns(basis):
    lengths = np.linalg.norm(basis, axis=1, keepdims=True)
    return basis / np.where(lengths > DEGENERATE_LENGTH, lengths, 1.0)


def create_probe_object():
    curve = bpy.data.curves.new("ShiyumeHairProbe", 'CURVE')
    curve.dimensions = '2D'
    spline = curve.splines.new('POLY')
    spline.points.add(2)
    for index, point in enumerate(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))):
        spline.points[index].co = (point[0], point[1], 0.0, 1.0)
    spline.use_cyclic_u = False
    return bpy.data.objects.new("ShiyumeHairProbe", curve)


def profile_points(profile_object):
    points = []
    for spline in profile_object.data.splines:
        if spline.type == 'BEZIER':
            points.extend((point.co[0], point.co[1]) for point in spline.bezier_points)
        else:
            points.extend((point.co[0], point.co[1]) for point in spline.points)
    return np.array(points, dtype=np.float64).reshape(-1, 2)


def evaluate_curve_frames(context, curve_object, probe_object):
    """用探针截面求值整条曲线，按样条切开，返回每根样条在世界空间里的 (原点, X 轴, Y 轴)。"""
    data = curve_object.data.copy()
    data.bevel_mode = 'OBJECT'
    data.bevel_object = probe_object
    data.use_fill_caps = False
    temporary = bpy.data.objects.new("ShiyumeHairFrames", data)
    context.scene.collection.objects.link(temporary)
    temporary.matrix_world = curve_object.matrix_world
    evaluated = None
    try:
        context.view_layer.update()
        evaluated = temporary.evaluated_get(context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        vertex_count = len(mesh.vertices)
        positions = np.empty(vertex_count * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", positions)
        edge_vertices = np.empty(len(mesh.edges) * 2, dtype=np.int32)
        mesh.edges.foreach_get("vertices", edge_vertices)
    finally:
        if evaluated is not None:
            evaluated.to_mesh_clear()
        context.scene.collection.objects.unlink(temporary)
        bpy.data.objects.remove(temporary)
        bpy.data.curves.remove(data)

    positions = positions.reshape(-1, 3).astype(np.float64)
    ring_count = vertex_count // 3
    low = np.minimum(edge_vertices[0::2], edge_vertices[1::2])
    high = np.maximum(edge_vertices[0::2], edge_vertices[1::2])
    linked = np.zeros(ring_count, dtype=bool)
    chain = (high - low == 3) & (low % 3 == 0)
    linked[low[chain] // 3] = True
    starts = [0] + [ring + 1 for ring in range(ring_count - 1) if not linked[ring]]
    stops = starts[1:] + [ring_count]

    matrix = np.array(curve_object.matrix_world, dtype=np.float64)
    linear = matrix[:3, :3]
    origins_all = positions[0::3] @ linear.T + matrix[:3, 3]
    axes_x_all = (positions[1::3] - positions[0::3]) @ linear.T
    axes_y_all = (positions[2::3] - positions[0::3]) @ linear.T
    return [(origins_all[start:stop], axes_x_all[start:stop], axes_y_all[start:stop])
            for start, stop in zip(starts, stops)]


def collect_strands(context, curve_objects, probe_object, report):
    strands = []
    for name in sorted(curve_objects):
        curve_object = curve_objects[name]
        bevel = curve_object.data.bevel_object
        if bevel is None:
            report({'WARNING'}, "曲线 %s 没有截面物体，已跳过" % name)
            continue
        profile = profile_points(bevel)
        frames = evaluate_curve_frames(context, curve_object, probe_object)
        if len(frames) != len(curve_object.data.splines):
            report({'WARNING'}, "曲线 %s 的求值截面链数 %d 与样条数 %d 不符，已跳过"
                   % (name, len(frames), len(curve_object.data.splines)))
            continue
        for index, (origins, axes_x, axes_y) in enumerate(frames):
            strands.append(Strand("%s|%d" % (name, index), origins, axes_x, axes_y, profile))
    return strands


def nearest_rows(queries, candidates):
    """每个查询点最近的候选点下标与距离。"""
    best = np.empty(len(queries), dtype=np.int64)
    distance = np.empty(len(queries))
    candidate_norm = (candidates * candidates).sum(axis=1)
    for start in range(0, len(queries), QUERY_CHUNK):
        chunk = queries[start:start + QUERY_CHUNK]
        squared = (chunk * chunk).sum(axis=1)[:, None] + candidate_norm[None, :] \
            - 2.0 * chunk @ candidates.T
        picked = squared.argmin(axis=1)
        best[start:start + QUERY_CHUNK] = picked
        distance[start:start + QUERY_CHUNK] = np.sqrt(
            np.maximum(squared[np.arange(len(chunk)), picked], 0.0))
    return best, distance


def mesh_world_positions(mesh_object):
    mesh = mesh_object.data
    local = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", local)
    matrix = np.array(mesh_object.matrix_world, dtype=np.float64)
    return local.reshape(-1, 3).astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3]


def vertex_adjacency(mesh):
    edge_vertices = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", edge_vertices)
    neighbours = [[] for _ in range(len(mesh.vertices))]
    for first, second in edge_vertices.reshape(-1, 2):
        neighbours[first].append(second)
        neighbours[second].append(first)
    return neighbours


def ensure_attribute(mesh, name, data_type, domain):
    existing = mesh.attributes.get(name)
    if existing is not None:
        mesh.attributes.remove(existing)
    return mesh.attributes.new(name, data_type, domain)


def encode_snapshot(rings, parts):
    raw = np.concatenate(parts).tobytes() if parts else b""
    return json.dumps({"rings": rings,
                       "data": base64.b64encode(zlib.compress(raw, 6)).decode("ascii")})


def pack_snapshot(strands):
    rings = []
    parts = []
    for strand in strands:
        rings.append(strand.ring_count)
        parts.append(strand.origins.astype(np.float32).ravel())
        parts.append(strand.basis.astype(np.float32).ravel())
    return encode_snapshot(rings, parts)


def unpack_snapshot(mesh):
    """网格当前对应的曲线截面坐标系：发丝名 -> (原点, 基)。"""
    keys = json.loads(mesh[KEYS_PROPERTY])
    packed = json.loads(mesh[SNAPSHOT_PROPERTY])
    values = np.frombuffer(zlib.decompress(base64.b64decode(packed["data"])), dtype=np.float32)
    frames = {}
    cursor = 0
    for key, rings in zip(keys, packed["rings"]):
        origins = values[cursor:cursor + rings * 3].reshape(rings, 3).astype(np.float64)
        cursor += rings * 3
        basis = values[cursor:cursor + rings * 9].reshape(rings, 3, 3).astype(np.float64)
        cursor += rings * 9
        frames[key] = (origins, basis)
    return frames


def sample_frames(origins, basis, fractions):
    count = len(origins)
    scaled = fractions.astype(np.float64) * (count - 1)
    scaled = np.where(np.abs(scaled - np.rint(scaled)) < 1.0e-3, np.rint(scaled), scaled)
    lower = np.clip(np.floor(scaled).astype(np.int64), 0, max(count - 2, 0))
    upper = np.minimum(lower + 1, count - 1)
    weight = np.clip(scaled - lower, 0.0, 1.0)[:, None]
    origin = origins[lower] * (1.0 - weight) + origins[upper] * weight
    mixed = basis[lower] * (1.0 - weight[:, :, None]) + basis[upper] * weight[:, :, None]
    return origin, mixed


def bind_mesh(mesh_object, strands):
    """把网格每个顶点绑到曲线截面坐标系：发丝号、沿线位置，并记下此刻网格所对应的截面坐标系快照。"""
    mesh = mesh_object.data
    positions = mesh_world_positions(mesh_object)
    count = len(positions)

    point_strand = []
    point_ring = []
    point_array = []
    for strand_index, strand in enumerate(strands):
        points = strand.ring_points()
        rings, profile_count = points.shape[0], points.shape[1]
        point_array.append(points.reshape(-1, 3))
        point_strand.append(np.full(rings * profile_count, strand_index, dtype=np.int64))
        point_ring.append(np.repeat(np.arange(rings, dtype=np.int64), profile_count))
    all_points = np.concatenate(point_array)
    all_strand = np.concatenate(point_strand)
    all_ring = np.concatenate(point_ring)

    nearest, distance = nearest_rows(positions, all_points)
    strand_of = all_strand[nearest].copy()
    ring_of = all_ring[nearest].copy()
    anchored = distance <= MATCH_TOLERANCE
    method = np.where(anchored, 0, -1)

    neighbours = vertex_adjacency(mesh)
    queue = deque(np.flatnonzero(anchored).tolist())
    inherited = np.full(count, -1, dtype=np.int64)
    inherited[anchored] = strand_of[anchored]
    while queue:
        vertex = queue.popleft()
        for other in neighbours[vertex]:
            if inherited[other] < 0:
                inherited[other] = inherited[vertex]
                method[other] = 1
                queue.append(other)

    propagated = np.flatnonzero(method == 1)
    for strand_index in np.unique(inherited[propagated]):
        members = propagated[inherited[propagated] == strand_index]
        points = strands[strand_index].ring_points()
        profile_count = points.shape[1]
        picked, _ = nearest_rows(positions[members], points.reshape(-1, 3))
        strand_of[members] = strand_index
        ring_of[members] = picked // profile_count

    free = method == -1
    strand_of[free] = -1
    unreached = int(np.count_nonzero(free))

    ring_fraction = np.zeros(count, dtype=np.float32)
    for strand_index in np.unique(strand_of[strand_of >= 0]):
        members = np.flatnonzero(strand_of == strand_index)
        ring_fraction[members] = ring_of[members] / max(strands[strand_index].ring_count - 1, 1)

    strand_attribute = ensure_attribute(mesh, STRAND_ATTRIBUTE, 'INT', 'POINT')
    strand_attribute.data.foreach_set("value", strand_of.astype(np.int32))
    ring_attribute = ensure_attribute(mesh, RING_ATTRIBUTE, 'FLOAT', 'POINT')
    ring_attribute.data.foreach_set("value", ring_fraction)
    mesh[KEYS_PROPERTY] = json.dumps([strand.key for strand in strands])
    mesh[SNAPSHOT_PROPERTY] = pack_snapshot(strands)

    mesh.update()
    return {"vertices": count, "anchored": int(np.count_nonzero(method == 0)),
            "propagated": int(np.count_nonzero(method == 1)), "unreached": unreached,
            "strands": int(len(np.unique(strand_of[strand_of >= 0])))}


def is_bound(mesh):
    return all(mesh.attributes.get(name) is not None for name in (STRAND_ATTRIBUTE, RING_ATTRIBUTE)) \
        and KEYS_PROPERTY in mesh.keys() and SNAPSHOT_PROPERTY in mesh.keys()


def retarget_mesh(mesh_object, strands, update_normals):
    """网格此刻相对上次同步的截面坐标系的偏移（含手工修改）原样搬到曲线当前的截面坐标系上，再把快照更新为当前曲线。"""
    mesh = mesh_object.data
    keys = json.loads(mesh[KEYS_PROPERTY])
    snapshot = unpack_snapshot(mesh)
    count = len(mesh.vertices)

    strand_of = np.empty(count, dtype=np.int32)
    mesh.attributes[STRAND_ATTRIBUTE].data.foreach_get("value", strand_of)
    ring_fraction = np.empty(count, dtype=np.float32)
    mesh.attributes[RING_ATTRIBUTE].data.foreach_get("value", ring_fraction)

    by_key = {strand.key: strand for strand in strands}
    positions = mesh_world_positions(mesh_object)
    old_basis = np.zeros((count, 3, 3), dtype=np.float64)
    new_basis = np.zeros((count, 3, 3), dtype=np.float64)
    moved = np.zeros(count, dtype=bool)
    missing = []
    for strand_index in np.unique(strand_of[strand_of >= 0]):
        key = keys[strand_index]
        strand = by_key.get(key)
        if strand is None:
            missing.append(key)
            continue
        members = np.flatnonzero(strand_of == strand_index)
        old_origin, old_frame = sample_frames(snapshot[key][0], snapshot[key][1], ring_fraction[members])
        delta = positions[members] - old_origin
        local = np.linalg.solve(old_frame, delta[:, :, None])[:, :, 0]
        new_origin, new_frame = sample_frames(strand.origins, strand.basis, ring_fraction[members])
        positions[members] = new_origin + np.einsum('vij,vj->vi', new_frame, local)
        old_basis[members] = old_frame
        new_basis[members] = new_frame
        moved[members] = True

    matrix = np.array(mesh_object.matrix_world, dtype=np.float64)
    carried = None
    if update_normals and mesh.has_custom_normals:
        loop_count = len(mesh.loops)
        loop_vertex = np.empty(loop_count, dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vertex)
        current = np.empty(loop_count * 3, dtype=np.float32)
        mesh.corner_normals.foreach_get("vector", current)
        carried = current.reshape(-1, 3).astype(np.float64)
        selected = moved[loop_vertex]
        world_normals = carried[selected] @ np.linalg.inv(matrix[:3, :3])
        world_normals /= np.maximum(np.linalg.norm(world_normals, axis=1, keepdims=True), 1.0e-12)
        old_unit = unit_columns(old_basis[loop_vertex[selected]])
        new_unit = unit_columns(new_basis[loop_vertex[selected]])
        local_normals = np.linalg.solve(old_unit, world_normals[:, :, None])[:, :, 0]
        rotated = np.einsum('lij,lj->li', new_unit, local_normals) @ matrix[:3, :3]
        rotated /= np.maximum(np.linalg.norm(rotated, axis=1, keepdims=True), 1.0e-12)
        carried[selected] = rotated

    inverse = np.linalg.inv(matrix)
    mesh_local = positions @ inverse[:3, :3].T + inverse[:3, 3]
    mesh.vertices.foreach_set("co", mesh_local.astype(np.float32).ravel())
    mesh.update()
    if carried is not None:
        mesh.normals_split_custom_set([tuple(row) for row in carried])
        mesh.update()

    rings = []
    parts = []
    for key in keys:
        strand = by_key.get(key)
        origins, basis = (strand.origins, strand.basis) if strand is not None else snapshot[key]
        rings.append(len(origins))
        parts.append(origins.astype(np.float32).ravel())
        parts.append(basis.astype(np.float32).ravel())
    mesh[SNAPSHOT_PROPERTY] = encode_snapshot(rings, parts)

    return {"moved": int(np.count_nonzero(moved)), "vertices": count, "missing": missing}


@contextmanager
def curve_objects_from_file(path, prefix):
    """把 .blend 里名字带前缀的物体临时追加进来，用完连同曲线数据一起删掉；名字映射回文件里的原名。"""
    with bpy.data.libraries.load(path, link=False) as (source, target):
        wanted = [name for name in source.objects if name.startswith(prefix)]
        target.objects = list(wanted)
    loaded = {name: obj for name, obj in zip(wanted, target.objects) if obj is not None}
    try:
        yield loaded
    finally:
        datablocks = []
        for obj in loaded.values():
            datablocks.append(obj)
            if obj.data is not None:
                datablocks.append(obj.data)
        bpy.data.batch_remove(datablocks)


def usable_curves(objects):
    return {name: obj for name, obj in objects.items()
            if obj.type == 'CURVE' and obj.data.bevel_object is not None}


def active_mesh(context):
    obj = context.active_object
    return obj if obj is not None and obj.type == 'MESH' else None


def run_with_curves(operator, context, selected_only, action):
    probe = create_probe_object()
    probe_data = probe.data
    context.scene.collection.objects.link(probe)
    try:
        if operator.curve_file:
            path = bpy.path.abspath(operator.curve_file)
            with curve_objects_from_file(path, operator.curve_prefix) as loaded:
                curves = usable_curves(loaded)
                strands = collect_strands(context, curves, probe, operator.report)
                return action(strands)
        if selected_only:
            pool = {obj.name: obj for obj in context.selected_objects}
        else:
            pool = {obj.name: obj for obj in bpy.data.objects
                    if obj.name.startswith(operator.curve_prefix)}
        curves = usable_curves(pool)
        strands = collect_strands(context, curves, probe, operator.report)
        return action(strands)
    finally:
        context.scene.collection.objects.unlink(probe)
        bpy.data.objects.remove(probe)
        bpy.data.curves.remove(probe_data)


class SHIYUME_OT_HairCurveBind(bpy.types.Operator):
    """把头发网格的每个顶点绑定到生成它的头发曲线上。
    绑定存在网格上：每个顶点的发丝号、沿发丝的截面位置，外加网格此刻所对应的曲线截面坐标系快照。
    UV、顶点组、材质、拓扑一概不动。
    顶点与曲线求值截面点逐位重合的先作锚点，被手工改过的顶点沿网格邻接继承锚点的发丝，
    再在该发丝上取最近截面，所以手工细修会跟着曲线一起走。"""
    bl_idname = "shiyume.hair_curve_bind"
    bl_label = "头发网格绑定到曲线"
    bl_options = {'REGISTER', 'UNDO'}

    curve_file: bpy.props.StringProperty(
        name="曲线文件",
        description="从这个 .blend 里临时读取头发曲线；留空则用当前文件里的曲线",
        subtype='FILE_PATH', default="")

    curve_prefix: bpy.props.StringProperty(
        name="曲线名前缀",
        description="只取名字带这个前缀的物体（曲线与它们的截面物体）",
        default=DEFAULT_PREFIX)

    @classmethod
    def poll(cls, context):
        return active_mesh(context) is not None

    def execute(self, context):
        mesh_object = active_mesh(context)
        result = run_with_curves(self, context, True, lambda strands: self.bind(mesh_object, strands))
        if result is None:
            return {'CANCELLED'}
        return {'FINISHED'}

    def bind(self, mesh_object, strands):
        if not strands:
            self.report({'ERROR'}, "没有可用的头发曲线：需要带截面物体的曲线")
            return None
        summary = bind_mesh(mesh_object, strands)
        self.report({'INFO'}, "绑定 %d 个顶点到 %d 根发丝：逐位重合 %d，沿邻接继承 %d，无锚点孤岛 %d（不绑定、不会被动）" % (
            summary["vertices"], summary["strands"], summary["anchored"],
            summary["propagated"], summary["unreached"]))
        return summary


class SHIYUME_OT_HairCurveRetarget(bpy.types.Operator):
    """按头发曲线当前的形状重新摆放已绑定的头发网格顶点。
    改曲线的控制点、半径、倾斜后不用重新网格化，UV、顶点组、材质、拓扑都原样保留，
    自定义法线跟随截面坐标系一起转动。每次都以网格此刻的位置为准，上次同步以来
    手工改过的顶点会带着它们相对曲线的偏移一起走；同步完快照更新为当前曲线。
    控制点数量变化时按沿线位置比例重新落点。"""
    bl_idname = "shiyume.hair_curve_retarget"
    bl_label = "曲线重定向头发网格"
    bl_options = {'REGISTER', 'UNDO'}

    curve_file: bpy.props.StringProperty(
        name="曲线文件",
        description="从这个 .blend 里临时读取头发曲线；留空则用当前文件里的曲线",
        subtype='FILE_PATH', default="")

    curve_prefix: bpy.props.StringProperty(
        name="曲线名前缀",
        description="只取名字带这个前缀的物体（曲线与它们的截面物体）",
        default=DEFAULT_PREFIX)

    update_normals: bpy.props.BoolProperty(
        name="法线跟随",
        description="自定义法线按截面坐标系一起转动",
        default=True)

    @classmethod
    def poll(cls, context):
        mesh_object = active_mesh(context)
        return mesh_object is not None and is_bound(mesh_object.data)

    def execute(self, context):
        mesh_object = active_mesh(context)
        result = run_with_curves(self, context, False, lambda strands: self.retarget(mesh_object, strands))
        if result is None:
            return {'CANCELLED'}
        return {'FINISHED'}

    def retarget(self, mesh_object, strands):
        summary = retarget_mesh(mesh_object, strands, self.update_normals)
        if summary["missing"]:
            self.report({'WARNING'}, "缺少 %d 根发丝的曲线，对应顶点未动：%s" % (
                len(summary["missing"]), ", ".join(summary["missing"][:6])))
        self.report({'INFO'}, "重定向 %d / %d 个顶点" % (summary["moved"], summary["vertices"]))
        return summary
