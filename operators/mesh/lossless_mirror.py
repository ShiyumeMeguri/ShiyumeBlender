"""无损镜像: 保留选中顶点所在的一侧, 另一侧整个换成它的镜像。

做法与手工镜像带形态键的网格相同, 全是 C 层的批量操作: 删掉另一侧; 复制网格, 沿镜像轴
缩放 -1(形态键一起)并翻转面朝向; 复制件上把左右成对的顶点组与形态键改名对调; 合并回
原网格, 合并按名字对接顶点组与形态键。两个物体都放在单位变换下合并, 镜像那一半的坐标
逐位取反(物体级负缩放经合并换算会带进浮点误差)。

焊接不看距离, 只看是不是恰好落在镜像面上: 镜像面上只有另一侧的面在用的顶点属于另一侧,
删掉; 其余镜像面上的顶点一律与自己的镜像副本焊成一个(中缝本来断开的, 比如 UV 接缝把
中线拆成两列, 也就此并上)。副本与原顶点在镜像面上逐位重合, 焊接不移动任何位置;
离镜像面再近的顶点也不在镜像面上, 不会被焊。

阀门: 另一侧有东西时, 镜像面以外两侧的顶点数必须相同, 否则两侧拓扑不对称, 动手前直接
拒绝, 网格不动; 另一侧本来是空的(只有半个网格)就是补出另一半。

切空间自定义法线按平滑扇编码, 基准边取扇里面序最靠前的那个角 —— 删半边、合并、焊接
都会改面序, 原样搬过来的编码在中缝会解出别的方向, 这就是"合并后法线错乱"。目标法线
是确定的: 保留侧与跨中缝的扇 = 删除前缓存的法线, 镜像侧 = 源角删除前法线的镜像。每个
角在两份编码里取解码后离目标更近的一份: 流水线带过来的(跨中缝扇换成源角删除前的编码),
或按目标在最终拓扑上重编的。基准没变的扇因此逐位不动, 变了的落在编码精度内。
"""

import contextlib

import bmesh
import bpy
import numpy
from mathutils import Matrix


CUSTOM_NORMAL = "custom_normal"
SOURCE_CORNER = "shiyume_mirror_source_corner"
MIRRORED_FACE = "shiyume_mirror_mirrored_face"
TRACKING_ATTRIBUTES = (SOURCE_CORNER, MIRRORED_FACE)
SWAP_PREFIX = "shiyume_mirror_swap_"
VALUE_ACCESS = {
    'FLOAT': ("value", 1, numpy.float32),
    'INT': ("value", 1, numpy.int32),
    'INT8': ("value", 1, numpy.int32),
    'BOOLEAN': ("value", 1, bool),
    'FLOAT_VECTOR': ("vector", 3, numpy.float32),
    'FLOAT_COLOR': ("color", 4, numpy.float32),
    'BYTE_COLOR': ("color_srgb", 4, numpy.float32),
    'FLOAT2': ("vector", 2, numpy.float32),
    'INT16_2D': ("value", 2, numpy.int16),
    'INT32_2D': ("value", 2, numpy.int32),
    'QUATERNION': ("value", 4, numpy.float32),
    'FLOAT4X4': ("value", 16, numpy.float32),
}


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


def reflection(axis_index):
    return Matrix.Diagonal([-1.0 if index == axis_index else 1.0 for index in range(3)] + [1.0])


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
    """删除前定好: 哪些顶点删, 镜像面上哪些顶点与自己的副本焊回, 镜像面以外两侧各有多少顶点。"""

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
        self.other_side_empty = not self.delete.any()
        self.kept_off_plane = int(numpy.count_nonzero(side == 1))
        self.other_off_plane = int(numpy.count_nonzero(side == -1))
        self.kept_index = numpy.cumsum(~self.delete) - 1
        self.kept_vertex_count = int(numpy.count_nonzero(~self.delete))
        self.weld_vertices = self.kept_index[on_plane & ~self.delete]


def delete_other_side(mesh, plan):
    half = bmesh.new()
    try:
        half.from_mesh(mesh)
        half.verts.ensure_lookup_table()
        doomed = [half.verts[index] for index in numpy.flatnonzero(plan.delete).tolist()]
        bmesh.ops.delete(half, geom=doomed, context='VERTS')
        half.to_mesh(mesh)
    finally:
        half.free()


def swap_flipped_names(collection):
    names = {item.name for item in collection}
    pairs = [(item, bpy.utils.flip_name(item.name)) for item in collection]
    pairs = [(item, flipped) for item, flipped in pairs if flipped != item.name and flipped in names]
    for index, (item, _) in enumerate(pairs):
        item.name = f"{SWAP_PREFIX}{index}"
    for item, flipped in pairs:
        item.name = flipped


@contextlib.contextmanager
def distinct_material_slots(mesh):
    """合并会把重复的材质槽(含空槽)去重, 连带截掉用户物体的物体级槽: 期间每个槽换成各不相同的占位材质。"""
    slots = list(mesh.materials)
    placeholders = [bpy.data.materials.new(f"{SWAP_PREFIX}{index}") for index in range(len(slots))]
    try:
        for index, placeholder in enumerate(placeholders):
            mesh.materials[index] = placeholder
        yield
    finally:
        for index, material in enumerate(slots):
            mesh.materials[index] = material
        for placeholder in placeholders:
            bpy.data.materials.remove(placeholder)


def join_mirrored_copy(context, mesh, axis_index):
    """复制、取反、翻面、左右名对调, 再合并回原网格。"""
    with distinct_material_slots(mesh):
        mirrored = mesh.copy()
        mirrored.transform(reflection(axis_index), shape_keys=True)
        mirrored.flip_normals()
        write_attribute(mesh, MIRRORED_FACE, 'FACE', numpy.zeros(len(mesh.polygons)))
        write_attribute(mirrored, MIRRORED_FACE, 'FACE', numpy.ones(len(mirrored.polygons)))
        target = bpy.data.objects.new(mesh.name, mesh)
        source = bpy.data.objects.new(mirrored.name, mirrored)
        source_name = source.name
        context.scene.collection.objects.link(target)
        context.scene.collection.objects.link(source)
        try:
            swap_flipped_names(source.vertex_groups)
            if mirrored.shape_keys is not None:
                swap_flipped_names(mirrored.shape_keys.key_blocks)
            with context.temp_override(active_object=target, object=target, selected_objects=[target, source],
                                       selected_editable_objects=[target, source]):
                bpy.ops.object.join()
        finally:
            leftover = bpy.data.objects.get(source_name)
            if leftover is not None:
                bpy.data.objects.remove(leftover)
            bpy.data.objects.remove(target)
            bpy.data.meshes.remove(mirrored)


def settle_mirrored_half(mesh, kept_vertex_count, kept_face_count, axis_index):
    """合并后核对镜像那一半逐位取反; 面数据写回源面的值(合并会错开面组编号);
    自由法线写成源的镜像。"""
    positions = read_values(mesh.vertices, "co", numpy.float32, 3)
    expected = positions[:kept_vertex_count].copy()
    expected[:, axis_index] *= -1
    if (len(positions) != 2 * kept_vertex_count or len(mesh.polygons) != 2 * kept_face_count
            or not numpy.array_equal(positions[kept_vertex_count:], expected)):
        raise RuntimeError("合并出的镜像一半与保留的一半不是逐位镜像")
    face_attributes = [attribute.name for attribute in mesh.attributes
                       if attribute.domain == 'FACE' and attribute.data_type in VALUE_ACCESS
                       and attribute.name not in TRACKING_ATTRIBUTES]
    for name in face_attributes:
        data = mesh.attributes[name].data
        property_name, width, dtype = VALUE_ACCESS[mesh.attributes[name].data_type]
        values = numpy.empty(len(data) * width, dtype=dtype)
        data.foreach_get(property_name, values)
        values = values.reshape(len(data), width)
        values[kept_face_count:] = values[:kept_face_count]
        data.foreach_set(property_name, values.ravel())
    attribute = mesh.attributes.get(CUSTOM_NORMAL)
    if attribute is None or attribute.data_type != 'FLOAT_VECTOR':
        return
    values = read_values(attribute.data, "vector", numpy.float32, 3)
    half = len(values) // 2
    sources = numpy.arange(half)
    if attribute.domain == 'CORNER':
        corner_sources = read_attribute(mesh, SOURCE_CORNER)
        row_of_source = numpy.empty(corner_sources.max() + 1, dtype=numpy.int64)
        row_of_source[corner_sources[:half]] = sources
        sources = row_of_source[corner_sources[half:]]
    mirrored = values[sources]
    mirrored[:, axis_index] *= -1
    values[half:] = mirrored
    mesh.attributes[CUSTOM_NORMAL].data.foreach_set("vector", values.ravel())


def weld_seam(mesh, plan):
    """把该焊的副本焊回原顶点; 焊后会与原面重合的镜像面先删掉, 原面原样保留。"""
    kept = plan.kept_vertex_count
    positions = read_values(mesh.vertices, "co", numpy.float32, 3)
    if not numpy.array_equal(positions[kept + plan.weld_vertices], positions[plan.weld_vertices]):
        raise RuntimeError("中缝焊接对的两个顶点不重合")
    corner_vertices = read_values(mesh.loops, "vertex_index", numpy.int32)
    face_sizes = read_values(mesh.polygons, "loop_total", numpy.int32)
    welded_copy = numpy.zeros(len(mesh.vertices), dtype=bool)
    welded_copy[kept + plan.weld_vertices] = True
    duplicates = numpy.bincount(faces_of_corners(face_sizes), weights=welded_copy[corner_vertices],
                                minlength=len(face_sizes)) == face_sizes
    whole = bmesh.new()
    try:
        whole.from_mesh(mesh)
        whole.verts.ensure_lookup_table()
        whole.faces.ensure_lookup_table()
        seam = {whole.verts[kept + index]: whole.verts[index] for index in plan.weld_vertices.tolist()}
        doomed = [whole.faces[index] for index in numpy.flatnonzero(duplicates).tolist()]
        bmesh.ops.delete(whole, geom=doomed, context='FACES_ONLY')
        bmesh.ops.weld_verts(whole, targetmap=seam)
        crossing = crossing_fan_sources(whole, seam.values())
        whole.to_mesh(mesh)
    finally:
        whole.free()
    return crossing


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
    source_corner = whole.loops.layers.int[SOURCE_CORNER]
    mirrored_face = whole.faces.layers.int[MIRRORED_FACE]
    crossing = set()
    for vertex in seam_vertices:
        for fan in smooth_fans(vertex):
            mirrored = [corner for corner in fan if corner.face[mirrored_face]]
            if mirrored and len(mirrored) < len(fan):
                crossing.update(corner[source_corner] for corner in mirrored)
    return crossing


def restore_tangent_normals(mesh, original_normals, crossing, axis_index):
    """切空间法线: 每个角在流水线带来的编码与按目标重编的编码里, 取解码后离目标近的一份。"""
    sources = read_attribute(mesh, SOURCE_CORNER)
    face_sizes = read_values(mesh.polygons, "loop_total", numpy.int32)
    mirrored = numpy.repeat(read_attribute(mesh, MIRRORED_FACE).astype(bool), face_sizes)
    crossing_corners = mirrored & numpy.isin(sources, numpy.fromiter(crossing, dtype=numpy.int32))
    desired = original_normals[sources]
    desired[mirrored & ~crossing_corners, axis_index] *= -1
    kept = numpy.flatnonzero(~mirrored)
    kept_corner_of_source = numpy.empty(len(original_normals), dtype=numpy.int64)
    kept_corner_of_source[sources[kept]] = kept
    inherited = read_encoded_normals(mesh)
    inherited[crossing_corners] = inherited[kept_corner_of_source[sources[crossing_corners]]]
    write_encoded_normals(mesh, inherited)
    inherited_error = normal_deviation(mesh, desired)
    sharp = read_values(mesh.edges, "use_edge_sharp", bool)
    mesh.normals_split_custom_set(desired.tolist())
    if not numpy.array_equal(sharp, read_values(mesh.edges, "use_edge_sharp", bool)):
        raise RuntimeError("还原中缝法线时 Blender 加了锐边: 目标法线在同一把扇里不一致")
    recoded = read_encoded_normals(mesh)
    recoded_error = normal_deviation(mesh, desired)
    keep_inherited = inherited_error <= recoded_error
    write_encoded_normals(mesh, numpy.where(keep_inherited[:, None], inherited, recoded))
    return numpy.where(keep_inherited, inherited_error, recoded_error)


def mirror_mesh(context, mesh, axis_index):
    plan = SeamPlan(mesh, axis_index)
    vertex_count, edge_count, face_count = len(mesh.vertices), len(mesh.edges), len(mesh.polygons)
    if not plan.other_side_empty and plan.kept_off_plane != plan.other_off_plane:
        raise MirrorRefusal(
            f"镜像面以外保留侧 {plan.kept_off_plane} 个顶点, 另一侧 {plan.other_off_plane} 个"
            f"(差 {plan.other_off_plane - plan.kept_off_plane:+d}): 两侧拓扑不对称, 未作改动")
    custom = mesh.attributes.get(CUSTOM_NORMAL)
    tangent = custom is not None and custom.data_type == 'INT16_2D'
    original_normals = read_values(mesh.corner_normals, "vector", numpy.float32, 3) if tangent else None
    write_attribute(mesh, SOURCE_CORNER, 'CORNER', numpy.arange(len(mesh.loops)))
    if not plan.other_side_empty:
        delete_other_side(mesh, plan)
    kept_face_count = len(mesh.polygons)
    join_mirrored_copy(context, mesh, axis_index)
    settle_mirrored_half(mesh, plan.kept_vertex_count, kept_face_count, axis_index)
    crossing = weld_seam(mesh, plan)
    summary_errors = None
    if tangent:
        errors = restore_tangent_normals(mesh, original_normals, crossing, axis_index)
        seam_corners = numpy.isin(read_values(mesh.loops, "vertex_index", numpy.int32), plan.weld_vertices)
        summary_errors = errors[seam_corners]
    for name in TRACKING_ATTRIBUTES:
        mesh.attributes.remove(mesh.attributes[name])
    side = ("+" if plan.kept_sign > 0 else "-") + "XYZ"[axis_index]
    final_vertex_count = len(mesh.vertices)
    if (final_vertex_count, len(mesh.edges), len(mesh.polygons)) == (vertex_count, edge_count, face_count):
        counts = f"顶点数 {vertex_count} 不变"
    else:
        if plan.other_side_empty:
            reason = "另一侧原本是空的, 补出了另一半"
        elif final_vertex_count != vertex_count:
            reason = f"中线原本断开, 并上了 {vertex_count - final_vertex_count} 个顶点"
        else:
            reason = "两侧连线原本不对称"
        vertices = (f"顶点数 {vertex_count} 不变" if final_vertex_count == vertex_count
                    else f"顶点 {vertex_count} → {final_vertex_count}")
        counts = f"{vertices}, 边 {edge_count} → {len(mesh.edges)}, 面 {face_count} → {len(mesh.polygons)}({reason})"
    summary = f"保留 {side} 侧镜像完成: 中缝焊回 {len(plan.weld_vertices)} 个顶点, {counts}"
    if summary_errors is not None and summary_errors.size:
        summary += (f"; 中缝 {summary_errors.size} 个法线角与删除前最大偏差 {summary_errors.max():.1e}"
                    f"(逐位一致 {numpy.count_nonzero(summary_errors == 0)} 个)")
    return summary


class SHIYUME_OT_LosslessMirror(bpy.types.Operator):
    """无损镜像(保留选中侧)：编辑模式下，按选中顶点在镜像轴的哪一侧决定保留哪半，
    删掉另一半，复制保留的一半并沿镜像轴取反(形态键一起，左右成对的顶点组与形态键对调)，
    合并回来后把镜像面上的顶点与它自己的镜像副本焊回(中线原本断开的也并上)，中缝的自定义
    法线还原成删除前的样子。另一侧有东西时，镜像面以外两侧顶点数不同就直接拒绝，网格不动；
    只有半个网格时直接补出另一半"""
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
