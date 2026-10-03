"""无损镜像: 保留选中顶点所在的一侧, 另一侧整个换成它的镜像。

镜像本身交给镜像修改器(顶点组左右翻转、属性拷贝都归它), 只关掉它的距离合并:
那个合并是"顶点离自己的镜像够近就焊", 嘴边离中线零点几毫米的顶点是常态,
任何阈值都会焊错。

哪些顶点该焊不看距离, 看删除前的拓扑。镜像面上的顶点:
- 两侧的面都在用(中缝连着), 或者一个面都没用: 留下, 与自己的镜像副本焊成一个;
- 只有保留侧的面在用(中缝本来就断开, 比如 UV 接缝把中线拆成两列): 留下, 不焊;
- 只有另一侧的面在用: 它属于另一侧, 删掉。
副本与原顶点在镜像面上逐位重合, 焊接不移动任何位置。

切空间自定义法线按平滑扇编码, 基准边取扇里面序最靠前的那个角 —— 删半边、镜像、
焊接都会改面序, 原样搬过来的编码在中缝和镜像侧近中缝处会解出别的方向, 这就是
"合并后法线错乱"。目标法线是确定的: 保留侧与跨中缝的扇 = 删除前的法线,
镜像侧 = 源角删除前法线的镜像。每个角在两份编码里取解码后离目标更近的一份:
流水线带过来的(保留侧原样; 跨中缝扇换成源角删除前的编码), 或按目标在最终
拓扑上重编的。基准没变的扇因此逐位不动, 变了的落在编码精度内。

整个过程在网格副本上做完; 镜像后顶点数与原来不同就整体放弃, 原网格不动。
"""

import contextlib

import bmesh
import bpy
import numpy


CUSTOM_NORMAL = "custom_normal"
SOURCE_VERTEX = "shiyume_mirror_source_vertex"
SOURCE_CORNER = "shiyume_mirror_source_corner"
WELD_VERTEX = "shiyume_mirror_weld_vertex"
MIRRORED_FACE = "shiyume_mirror_mirrored_face"
TRACKING_ATTRIBUTES = (SOURCE_VERTEX, SOURCE_CORNER, WELD_VERTEX, MIRRORED_FACE)


class MirrorRefusal(Exception):
    pass


def read_values(sequence, property_name, dtype, width=1):
    values = numpy.empty(len(sequence) * width, dtype=dtype)
    sequence.foreach_get(property_name, values)
    return values.reshape(-1, width) if width > 1 else values


def read_attribute(mesh, name):
    data = mesh.attributes[name].data
    values = numpy.empty(len(data), dtype=numpy.int32)
    data.foreach_get("value", values)
    return values


def write_attribute(mesh, name, domain, values):
    attribute = mesh.attributes.new(name, 'INT', domain)
    attribute.data.foreach_set("value", numpy.asarray(values, dtype=numpy.int32))


def read_encoded_normals(mesh):
    data = mesh.attributes[CUSTOM_NORMAL].data
    values = numpy.empty((len(data), 2), dtype=numpy.int16)
    data.foreach_get("value", values.ravel())
    return values


def write_encoded_normals(mesh, values):
    mesh.attributes[CUSTOM_NORMAL].data.foreach_set("value", values.ravel())


def normal_deviation(mesh, desired):
    normals = read_values(mesh.corner_normals, "vector", numpy.float32, 3)
    return numpy.abs(normals - desired).max(axis=1)


def faces_of_corners(face_sizes):
    return numpy.repeat(numpy.arange(len(face_sizes)), face_sizes)


def mirrored_corners(mesh):
    face_sizes = read_values(mesh.polygons, "loop_total", numpy.int32)
    return numpy.repeat(read_attribute(mesh, MIRRORED_FACE).astype(bool), face_sizes)


def reflected(vector, axis_index):
    mirrored = vector.copy()
    mirrored[axis_index] = -mirrored[axis_index]
    return mirrored


def kept_sign_from_selection(mesh, coordinates):
    selected = read_values(mesh.vertices, "select", bool)
    if not selected.any():
        raise MirrorRefusal("先选中要保留那一侧的任意一个顶点")
    positive = bool((coordinates[selected] > 0).any())
    negative = bool((coordinates[selected] < 0).any())
    if not positive and not negative:
        raise MirrorRefusal("选中的顶点都在镜像面上, 分不出要保留哪一侧")
    if positive and negative:
        raise MirrorRefusal("选中的顶点分在镜像面两侧, 只选要保留的那一侧")
    return 1 if positive else -1


def select_faces(mesh, faces, corner_vertices, corner_faces):
    corners = faces[corner_faces]
    vertices = numpy.zeros(len(mesh.vertices), dtype=bool)
    vertices[corner_vertices[corners]] = True
    edges = numpy.zeros(len(mesh.edges), dtype=bool)
    edges[read_values(mesh.loops, "edge_index", numpy.int32)[corners]] = True
    mesh.vertices.foreach_set("select", vertices)
    mesh.edges.foreach_set("select", edges)
    mesh.polygons.foreach_set("select", faces)


class SeamPlan:
    """删除前按拓扑定好: 哪些顶点删, 镜像面上哪些顶点与自己的副本焊回。"""

    def __init__(self, mesh, axis_index):
        coordinates = read_values(mesh.vertices, "co", numpy.float32, 3)[:, axis_index]
        self.kept_sign = kept_sign_from_selection(mesh, coordinates)
        side = (numpy.sign(coordinates) * self.kept_sign).astype(numpy.int8)
        corner_vertices = read_values(mesh.loops, "vertex_index", numpy.int32)
        corner_faces = faces_of_corners(read_values(mesh.polygons, "loop_total", numpy.int32))
        corner_sides = side[corner_vertices]
        face_count = len(mesh.polygons)
        face_kept = numpy.bincount(corner_faces, weights=corner_sides == 1, minlength=face_count) > 0
        face_other = numpy.bincount(corner_faces, weights=corner_sides == -1, minlength=face_count) > 0
        straddling = face_kept & face_other
        if straddling.any():
            select_faces(mesh, straddling, corner_vertices, corner_faces)
            raise MirrorRefusal(
                f"{numpy.count_nonzero(straddling)} 个面横跨镜像面(已选中), 先在镜像面上切出中线")
        vertex_count = len(mesh.vertices)
        used_by_kept = numpy.bincount(
            corner_vertices, weights=face_kept[corner_faces], minlength=vertex_count) > 0
        used_by_other = numpy.bincount(
            corner_vertices, weights=face_other[corner_faces], minlength=vertex_count) > 0
        on_plane = side == 0
        self.delete = (side == -1) | (on_plane & used_by_other & ~used_by_kept)
        self.weld = on_plane & (used_by_kept == used_by_other)


class MirrorLayout:
    """核对修改器输出是"原样一份 + 镜像一份"且逐个对应, 并给出焊接对与焊后会与原面重合的镜像面。"""

    def __init__(self, half_mesh, result, axis_index):
        self.vertex_count = len(half_mesh.vertices)
        self.face_count = len(half_mesh.polygons)
        positions = read_values(result.vertices, "co", numpy.float32, 3)
        sources = read_attribute(result, SOURCE_VERTEX)
        corner_vertices = read_values(result.loops, "vertex_index", numpy.int32)
        face_sizes = read_values(result.polygons, "loop_total", numpy.int32)
        corner_faces = faces_of_corners(face_sizes)
        expected = positions[:self.vertex_count].copy()
        expected[:, axis_index] *= -1
        if (len(positions) != 2 * self.vertex_count or len(face_sizes) != 2 * self.face_count
                or not numpy.array_equal(positions[self.vertex_count:], expected)
                or not numpy.array_equal(sources[:self.vertex_count], sources[self.vertex_count:])
                or not numpy.array_equal(corner_faces >= self.face_count,
                                         corner_vertices >= self.vertex_count)):
            raise MirrorRefusal("镜像修改器的输出不是原样与镜像逐个对应的两份, 未作改动")
        weld = read_attribute(result, WELD_VERTEX).astype(bool)
        self.weld_vertices = numpy.flatnonzero(weld[:self.vertex_count])
        all_welded = numpy.bincount(
            corner_faces, weights=weld[corner_vertices], minlength=len(face_sizes)) == face_sizes
        self.duplicate_faces = numpy.flatnonzero(all_welded[self.face_count:]) + self.face_count
        write_attribute(result, MIRRORED_FACE, 'FACE', numpy.arange(len(face_sizes)) >= self.face_count)


@contextlib.contextmanager
def scratch_object(context, mesh):
    work_mesh = mesh.copy()
    work_object = bpy.data.objects.new(work_mesh.name, work_mesh)
    context.scene.collection.objects.link(work_object)
    try:
        yield work_object
    finally:
        bpy.data.objects.remove(work_object)
        bpy.data.meshes.remove(work_mesh)


def mirror_half(context, work_object, axis_index, plan):
    """删掉另一侧, 交给关掉合并的镜像修改器, 取回求值结果。"""
    work_mesh = work_object.data
    write_attribute(work_mesh, SOURCE_VERTEX, 'POINT', numpy.arange(len(work_mesh.vertices)))
    write_attribute(work_mesh, WELD_VERTEX, 'POINT', plan.weld)
    write_attribute(work_mesh, SOURCE_CORNER, 'CORNER', numpy.arange(len(work_mesh.loops)))
    half = bmesh.new()
    half.from_mesh(work_mesh)
    half.verts.ensure_lookup_table()
    doomed = [half.verts[index] for index in numpy.flatnonzero(plan.delete).tolist()]
    bmesh.ops.delete(half, geom=doomed, context='VERTS')
    half.to_mesh(work_mesh)
    half.free()
    modifier = work_object.modifiers.new("Mirror", 'MIRROR')
    modifier.use_axis = [index == axis_index for index in range(3)]
    modifier.use_mirror_merge = False
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = work_object.evaluated_get(depsgraph)
    result = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        layout = MirrorLayout(work_mesh, result, axis_index)
        whole = bmesh.new()
        whole.from_mesh(result)
    finally:
        evaluated.to_mesh_clear()
    return whole, layout


def reflect_free_normals(whole, layout, axis_index):
    """自由法线(float3)修改器原样拷贝不翻转: 镜像那一份按源重写成翻转后的值。"""
    vertex_layer = whole.verts.layers.float_vector.get(CUSTOM_NORMAL)
    if vertex_layer is not None:
        for index in range(layout.vertex_count):
            source = whole.verts[index][vertex_layer]
            whole.verts[index + layout.vertex_count][vertex_layer] = reflected(source, axis_index)
    corner_layer = whole.loops.layers.float_vector.get(CUSTOM_NORMAL)
    face_layer = whole.faces.layers.float_vector.get(CUSTOM_NORMAL)
    if corner_layer is None and face_layer is None:
        return
    source_corner = whole.loops.layers.int[SOURCE_CORNER]
    kept_corners = {corner[source_corner]: corner
                    for index in range(layout.face_count) for corner in whole.faces[index].loops}
    for index in range(layout.face_count, 2 * layout.face_count):
        face = whole.faces[index]
        for corner in face.loops:
            source = kept_corners[corner[source_corner]]
            if corner_layer is not None:
                corner[corner_layer] = reflected(source[corner_layer], axis_index)
            if face_layer is not None:
                face[face_layer] = reflected(source.face[face_layer], axis_index)


def weld_seam(whole, layout, axis_index):
    """把该焊的副本焊回原顶点; 焊后会与原面重合的镜像面先删掉, 原面原样保留。"""
    whole.verts.ensure_lookup_table()
    whole.faces.ensure_lookup_table()
    reflect_free_normals(whole, layout, axis_index)
    seam = {whole.verts[index + layout.vertex_count]: whole.verts[index]
            for index in layout.weld_vertices.tolist()}
    duplicates = [whole.faces[index] for index in layout.duplicate_faces.tolist()]
    bmesh.ops.delete(whole, geom=duplicates, context='FACES_ONLY')
    bmesh.ops.weld_verts(whole, targetmap=seam)
    return list(seam.values())


def find_root(roots, key):
    while roots[key] != key:
        key = roots[key]
    return key


def smooth_fans(vertex):
    """与 Blender 求角法线同一判据: 边不锐、两侧面都平滑、恰好两个面且绕向一致, 才把两边的角连成一把扇。"""
    corners = {corner.face.index: corner for corner in vertex.link_loops}
    roots = {face_index: face_index for face_index in corners}
    for edge in vertex.link_edges:
        if edge.smooth and edge.is_contiguous and all(face.smooth for face in edge.link_faces):
            first, second = (find_root(roots, face.index) for face in edge.link_faces)
            roots[first] = second
    fans = {}
    for face_index, corner in corners.items():
        fans.setdefault(find_root(roots, face_index), []).append(corner)
    return fans.values()


def crossing_fan_sources(whole, seam_vertices):
    """跨中缝的平滑扇里, 镜像角的源角编号。"""
    whole.faces.index_update()
    mirrored_face = whole.faces.layers.int[MIRRORED_FACE]
    source_corner = whole.loops.layers.int[SOURCE_CORNER]
    crossing = set()
    for vertex in seam_vertices:
        for fan in smooth_fans(vertex):
            mirrored = [corner for corner in fan if corner.face[mirrored_face]]
            if mirrored and len(mirrored) < len(fan):
                crossing.update(corner[source_corner] for corner in mirrored)
    return crossing


def restore_tangent_normals(staging, original_normals, crossing, axis_index):
    """切空间法线: 每个角在流水线带来的编码与按目标重编的编码里, 取解码后离目标近的一份。"""
    attribute = staging.attributes.get(CUSTOM_NORMAL)
    if attribute is None or attribute.data_type != 'INT16_2D':
        return None
    sources = read_attribute(staging, SOURCE_CORNER)
    mirrored = mirrored_corners(staging)
    crossing_corners = mirrored & numpy.isin(sources, numpy.fromiter(crossing, dtype=numpy.int32))
    desired = original_normals[sources]
    desired[mirrored & ~crossing_corners, axis_index] *= -1
    kept = numpy.flatnonzero(~mirrored)
    kept_corner_of_source = numpy.empty(len(original_normals), dtype=numpy.int64)
    kept_corner_of_source[sources[kept]] = kept
    inherited = read_encoded_normals(staging)
    inherited[crossing_corners] = inherited[kept_corner_of_source[sources[crossing_corners]]]
    write_encoded_normals(staging, inherited)
    inherited_error = normal_deviation(staging, desired)
    sharp = read_values(staging.edges, "use_edge_sharp", bool)
    staging.normals_split_custom_set(desired.tolist())
    if not numpy.array_equal(sharp, read_values(staging.edges, "use_edge_sharp", bool)):
        raise MirrorRefusal("中缝法线不加锐边就还原不了, 未作改动")
    recoded = read_encoded_normals(staging)
    recoded_error = normal_deviation(staging, desired)
    keep_inherited = inherited_error <= recoded_error
    write_encoded_normals(staging, numpy.where(keep_inherited[:, None], inherited, recoded))
    return numpy.where(keep_inherited, inherited_error, recoded_error)


def commit(source, target):
    transfer = bmesh.new()
    try:
        transfer.from_mesh(source)
        transfer.to_mesh(target)
    finally:
        transfer.free()


def mirror_mesh(context, mesh, axis_index):
    plan = SeamPlan(mesh, axis_index)
    original_normals = read_values(mesh.corner_normals, "vector", numpy.float32, 3)
    vertex_count, edge_count, face_count = len(mesh.vertices), len(mesh.edges), len(mesh.polygons)
    with scratch_object(context, mesh) as work_object:
        staging = work_object.data
        whole, layout = mirror_half(context, work_object, axis_index, plan)
        try:
            seam_vertices = weld_seam(whole, layout, axis_index)
            if len(whole.verts) != vertex_count:
                raise MirrorRefusal(
                    f"镜像后 {len(whole.verts)} 个顶点, 原来 {vertex_count} 个"
                    f"(差 {len(whole.verts) - vertex_count:+d}): 两侧拓扑不对称, 未作改动")
            crossing = crossing_fan_sources(whole, seam_vertices)
            whole.to_mesh(staging)
        finally:
            whole.free()
        errors = restore_tangent_normals(staging, original_normals, crossing, axis_index)
        corner_vertices = read_values(staging.loops, "vertex_index", numpy.int32)
        seam_corners = read_attribute(staging, WELD_VERTEX)[corner_vertices].astype(bool)
        for name in TRACKING_ATTRIBUTES:
            staging.attributes.remove(staging.attributes[name])
        commit(staging, mesh)
    side = ("+" if plan.kept_sign > 0 else "-") + "XYZ"[axis_index]
    summary = f"保留 {side} 侧镜像完成: 中缝焊回 {len(seam_vertices)} 个顶点, 顶点数 {vertex_count} 不变"
    if errors is not None and seam_corners.any():
        seam_errors = errors[seam_corners]
        summary += (f"; 中缝 {seam_errors.size} 个法线角与删除前最大偏差 {seam_errors.max():.1e}"
                    f"(逐位一致 {numpy.count_nonzero(seam_errors == 0)} 个)")
    edge_change, face_change = len(mesh.edges) - edge_count, len(mesh.polygons) - face_count
    if edge_change or face_change:
        summary += f"; 边 {edge_change:+d} 面 {face_change:+d}(两侧连线原本不对称)"
    return summary


class SHIYUME_OT_LosslessMirror(bpy.types.Operator):
    """无损镜像(保留选中侧)：编辑模式下，按选中顶点在镜像轴的哪一侧决定保留哪半，
    删掉另一半后用镜像修改器(不按距离合并)镜像过去，只把中缝上原本连着两侧的顶点
    与它自己的镜像副本焊回，中缝的自定义法线还原成删除前的样子。
    镜像后顶点数与原来不同就整体取消，网格不动"""
    bl_idname = "shiyume.lossless_mirror"
    bl_label = "无损镜像(保留选中侧)"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(
        name="镜像轴",
        items=(('X', "X", "沿局部 X 轴镜像"),
               ('Y', "Y", "沿局部 Y 轴镜像"),
               ('Z', "Z", "沿局部 Z 轴镜像")),
        default='X',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        mesh = context.edit_object.data
        if mesh.shape_keys is not None:
            self.report({'ERROR'}, "网格带形态键, 镜像修改器无法应用, 未作改动")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        try:
            summary = mirror_mesh(context, mesh, "XYZ".index(self.axis))
        except MirrorRefusal as refusal:
            self.report({'ERROR'}, str(refusal))
            return {'CANCELLED'}
        finally:
            bpy.ops.object.mode_set(mode='EDIT')
        self.report({'INFO'}, summary)
        return {'FINISHED'}
