"""描边平滑法线烘焙：平滑法线转进每个角自己的切线空间，XY 写进 UV 层（默认 UV2），Z 由着色器现算。

切线框和 EEVEE 画这张网格时是同一套 MikkTSpace（渲染激活的 UV、角法线）；多边形超过四个角时 calc_tangents 拒绝算，先在副本上把
它们三角化再按角下标搬回。平滑法线有三个来源：面法线（游戏的算法）、网格上现成的向量属性、代理物体表面上最近点的法线。
全部在物体的局部空间里算，读的是网格数据本身（不带修改器、不带形态键混合）。
"""

from collections import namedtuple

import bmesh
import bpy
import numpy as np
from mathutils import kdtree

from ...uv.uv_transfer import mesh_bind
from ..endfield_highlight import bake as highlight_bake
from . import kernel

Frame = namedtuple("Frame", ("normal", "tangent", "bitangent"))
Corners = namedtuple("Corners", ("vertex", "position", "previous_position", "next_position", "face_normal"))
Outcome = namedtuple("Outcome", ("corners", "behind", "unsmoothed", "tilt_mean", "tilt_p90", "created"))
Verification = namedtuple("Verification", ("corners", "error_median", "error_max", "behind"))

CORNER_LAYER = "shiyume_corner"
MAX_POLYGON_CORNERS = 4
MAX_UV_LAYERS = 8
VECTOR_TYPES = ('FLOAT_VECTOR', 'FLOAT_COLOR', 'BYTE_COLOR')


class BakeError(Exception):
    pass


def _read(owner, name, shape, dtype=np.float64):
    values = np.empty(int(np.prod(shape)), dtype=dtype)
    owner.foreach_get(name, values)
    return values.reshape(shape)


def _frame_of(mesh, uv_name):
    mesh.calc_tangents(uvmap=uv_name)
    try:
        count = len(mesh.loops)
        normal = kernel.unit(_read(mesh.loops, "normal", (count, 3)))
        tangent = kernel.unit(_read(mesh.loops, "tangent", (count, 3)))
        sign = _read(mesh.loops, "bitangent_sign", count)
    finally:
        mesh.free_tangents()
    return Frame(normal, tangent, kernel.unit(np.cross(normal, tangent) * sign[:, None]))


def _triangulated(mesh):
    """超过四个角的多边形三角化后的副本，每个 loop 带着它在原网格里的下标。"""
    builder = bmesh.new()
    builder.from_mesh(mesh)
    layer = builder.loops.layers.int.new(CORNER_LAYER)
    index = 0
    for face in builder.faces:
        for loop in face.loops:
            loop[layer] = index
            index += 1
    bmesh.ops.triangulate(builder, faces=[face for face in builder.faces if len(face.verts) > MAX_POLYGON_CORNERS],
                          quad_method='BEAUTY', ngon_method='BEAUTY')
    copy = bpy.data.meshes.new("shiyume_outline_frame")
    builder.to_mesh(copy)
    builder.free()
    return copy


def frame_of(mesh, uv_name):
    """每个 loop 的切线框（法线、切线、副切线 = 符号 * cross(法线, 切线)），副切线的符号就是着色器里那一个。"""
    totals = _read(mesh.polygons, "loop_total", len(mesh.polygons), np.int64)
    if totals.max() <= MAX_POLYGON_CORNERS:
        return _frame_of(mesh, uv_name)
    copy = _triangulated(mesh)
    try:
        frame = _frame_of(copy, uv_name)
        origin = _read(copy.attributes[CORNER_LAYER].data, "value", len(copy.loops), np.int64)
    finally:
        bpy.data.meshes.remove(copy)
    count = len(mesh.loops)
    normal, tangent, bitangent = (np.zeros((count, 3)) for _ in range(3))
    normal[origin] = frame.normal
    tangent[origin] = frame.tangent
    bitangent[origin] = frame.bitangent
    return Frame(normal, tangent, bitangent)


def corners_of(mesh):
    """每个角的顶点下标、位置、同一多边形里前后两个角的位置，以及所在多边形的几何法线。"""
    loop_count = len(mesh.loops)
    polygon_count = len(mesh.polygons)
    vertex = _read(mesh.loops, "vertex_index", loop_count, np.int64)
    positions = _read(mesh.vertices, "co", (len(mesh.vertices), 3))
    start = _read(mesh.polygons, "loop_start", polygon_count, np.int64)
    total = _read(mesh.polygons, "loop_total", polygon_count, np.int64)
    polygon = np.repeat(np.arange(polygon_count), total)
    offset = np.arange(loop_count) - start[polygon]
    following = start[polygon] + (offset + 1) % total[polygon]
    preceding = start[polygon] + (offset - 1) % total[polygon]
    face_normal = _read(mesh.polygons, "normal", (polygon_count, 3))
    return Corners(vertex, positions[vertex], positions[vertex[preceding]], positions[vertex[following]], face_normal[polygon])


def weld_labels(positions, tolerance):
    """每个顶点的焊接组号：距离不超过 tolerance 的顶点同组（传递闭包）；tolerance 为 0 时每个顶点自成一组。"""
    count = len(positions)
    if tolerance <= 0.0:
        return np.arange(count)
    points = positions.tolist()
    tree = kdtree.KDTree(count)
    for index, point in enumerate(points):
        tree.insert(point, index)
    tree.balance()
    parent = list(range(count))

    def root(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for index, point in enumerate(points):
        for _location, other, _distance in tree.find_range(point, tolerance):
            first, second = root(index), root(other)
            if first != second:
                parent[max(first, second)] = min(first, second)
    return np.unique(np.array([root(index) for index in range(count)]), return_inverse=True)[1].reshape(-1)


def _face_smooth(mesh, frame, tolerance):
    corners = corners_of(mesh)
    labels = weld_labels(_read(mesh.vertices, "co", (len(mesh.vertices), 3)), tolerance)
    angle = kernel.corner_angles(corners.position, corners.previous_position, corners.next_position)
    smooth = kernel.weighted_smooth_normals(corners.face_normal, angle, labels[corners.vertex])
    empty = ~smooth.any(axis=1)
    smooth[empty] = frame.normal[empty]
    return smooth, int(empty.sum())


def _attribute_smooth(mesh, name):
    attribute = mesh.attributes.get(name)
    if attribute is None or attribute.data_type not in VECTOR_TYPES or attribute.domain not in ('CORNER', 'POINT'):
        raise BakeError("网格上没有角域或点域的向量属性 '%s'" % name)
    field = "vector" if attribute.data_type == 'FLOAT_VECTOR' else "color"
    width = 3 if attribute.data_type == 'FLOAT_VECTOR' else 4
    values = _read(attribute.data, field, (len(attribute.data), width))[:, :3]
    if attribute.domain == 'POINT':
        values = values[_read(mesh.loops, "vertex_index", len(mesh.loops), np.int64)]
    return kernel.unit(values)


def _proxy_smooth(obj, options, depsgraph):
    if options.proxy is None or not len(options.proxy.data.polygons):
        raise BakeError("来源是代理物体，但没有指定带面的代理物体")
    surface = highlight_bake.surface_of(options.proxy, obj, depsgraph)
    return kernel.unit(highlight_bake.nearest_normals(surface, corners_of(obj.data).position))


def smooth_normals(obj, options, depsgraph, frame):
    """每个角的平滑法线（局部空间，单位长度）和没法平均所以退回角法线的角数。"""
    mesh = obj.data
    if options.source == 'FACES':
        return _face_smooth(mesh, frame, options.weld_distance)
    if options.source == 'ATTRIBUTE':
        return _attribute_smooth(mesh, options.attribute), 0
    return _proxy_smooth(obj, options, depsgraph), 0


def _prepare(obj, options):
    mesh = obj.data
    if mesh.library is not None:
        raise BakeError("网格数据是 link 进来的，改不了")
    if not len(mesh.polygons):
        raise BakeError("没有面")
    uv_name = mesh_bind.render_uv_name(mesh)
    if not uv_name:
        raise BakeError("没有 UV 层，切线算不出来")
    if not options.layer.strip():
        raise BakeError("没有填写入的 UV 层名")
    if options.layer == uv_name:
        raise BakeError("写入的 UV 层不能是渲染用的 UV 层 '%s'" % uv_name)
    return mesh, uv_name


def _write(mesh, name, render_name, values):
    layer = mesh.uv_layers.get(name)
    created = layer is None
    if created:
        if len(mesh.uv_layers) >= MAX_UV_LAYERS:
            raise BakeError("UV 层已经有 %d 个，写不进新的" % MAX_UV_LAYERS)
        layer = mesh.uv_layers.new(name=name, do_init=False)
    layer.data.foreach_set("uv", np.ascontiguousarray(values, dtype=np.float32).reshape(-1))
    render = mesh.uv_layers[render_name]
    mesh.uv_layers.active = render
    render.active_render = True
    mesh.update()
    return created


def bake_object(obj, options, depsgraph):
    mesh, uv_name = _prepare(obj, options)
    frame = frame_of(mesh, uv_name)
    smooth, unsmoothed = smooth_normals(obj, options, depsgraph, frame)
    encoded, behind = kernel.encode(smooth, frame.tangent, frame.bitangent, frame.normal)
    created = _write(mesh, options.layer, uv_name, encoded)
    tilt = kernel.angle_degrees(smooth, frame.normal)
    return Outcome(len(encoded), int(behind.sum()), unsmoothed, float(tilt.mean()), float(np.percentile(tilt, 90)), created)


def verify_object(obj, options, depsgraph):
    """把已经烘焙进 UV 层的值按着色器的解码还原，和现在的来源重新编码再解码的结果比：网格或来源改过就会露出差。"""
    mesh, uv_name = _prepare(obj, options)
    baked = mesh_bind.read_uv(mesh, options.layer)
    if baked is None:
        raise BakeError("还没烘焙：没有 UV 层 '%s'" % options.layer)
    frame = frame_of(mesh, uv_name)
    smooth, _unsmoothed = smooth_normals(obj, options, depsgraph, frame)
    expected, behind = kernel.encode(smooth, frame.tangent, frame.bitangent, frame.normal)
    error = kernel.angle_degrees(kernel.decode(baked.astype(np.float64), frame.tangent, frame.bitangent, frame.normal),
                                 kernel.decode(expected, frame.tangent, frame.bitangent, frame.normal))
    return Verification(len(error), float(np.median(error)), float(error.max()), int(behind.sum()))


def clear_object(obj, options):
    """删掉写入的 UV 层，渲染用的 UV 层照旧；没有这一层返回 False。"""
    mesh, uv_name = _prepare(obj, options)
    layer = mesh.uv_layers.get(options.layer)
    if layer is None:
        return False
    mesh.uv_layers.remove(layer)
    render = mesh.uv_layers[uv_name]
    mesh.uv_layers.active = render
    render.active_render = True
    mesh.update()
    return True
