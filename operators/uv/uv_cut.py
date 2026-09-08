"""在 UV 编辑器里直接切割网格：等距网格下刀，或照参考孤岛的布线下刀。"""

import math

import bmesh
import bpy
from mathutils import Vector

from . import uv_islands
from .uv_knife import cut_faces, distance_to_segment


AXIS_INDEX = {"U": 0, "V": 1}
AXIS_SETS = {"U": ("U",), "V": ("V",), "BOTH": ("U", "V")}


# ---------------------------------------------------------------------------
# 刀路：等距网格
# ---------------------------------------------------------------------------


def _axis_line(axis_index, position, bounds, margin):
    other_index = 1 - axis_index
    start = Vector((0.0, 0.0))
    end = Vector((0.0, 0.0))
    start[axis_index] = position
    end[axis_index] = position
    start[other_index] = bounds[other_index] - margin
    end[other_index] = bounds[other_index + 2] + margin
    return [start, end]


def grid_polylines(bounds, axes, interval, align_to_island, tolerance):
    margin = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.5 + interval
    polylines = []
    for axis in axes:
        axis_index = AXIS_INDEX[axis]
        low = bounds[axis_index]
        high = bounds[axis_index + 2]
        origin = low if align_to_island else 0.0
        position = math.ceil((low - origin) / interval) * interval + origin
        if position - low <= tolerance:
            position += interval
        while position < high - tolerance:
            polylines.append(_axis_line(axis_index, position, bounds, margin))
            position += interval
    return polylines


# ---------------------------------------------------------------------------
# 刀路：参考孤岛的布线
# ---------------------------------------------------------------------------


def _vert_uv_map(faces, uv_layer):
    positions = {}
    for face in faces:
        for loop in face.loops:
            positions.setdefault(loop.vert, loop[uv_layer].uv.copy())
    return positions


def _interior_edges(faces):
    face_set = set(faces)
    edges = []
    seen = set()
    for face in faces:
        for loop in face.loops:
            edge = loop.edge
            if edge in seen:
                continue
            seen.add(edge)
            if len(edge.link_faces) != 2:
                continue
            if all(linked in face_set for linked in edge.link_faces):
                edges.append(edge)
    return edges


def _straightest_continuation(previous_vert, vert, adjacency, unused, positions):
    incoming = positions[vert] - positions[previous_vert]
    if incoming.length <= 0.0:
        return None
    incoming = incoming.normalized()

    best = None
    best_score = -2.0
    for edge, other_vert in adjacency.get(vert, ()):
        if edge not in unused:
            continue
        outgoing = positions[other_vert] - positions[vert]
        if outgoing.length <= 0.0:
            continue
        score = incoming.dot(outgoing.normalized())
        if score > best_score:
            best_score = score
            best = (edge, other_vert)
    return best


def _walk_chain(start_vert, edge, next_vert, adjacency, unused, positions):
    chain = [positions[start_vert]]
    current_vert = start_vert
    current_edge = edge
    following_vert = next_vert
    while True:
        unused.discard(current_edge)
        chain.append(positions[following_vert])
        continuation = _straightest_continuation(
            current_vert, following_vert, adjacency, unused, positions)
        if continuation is None:
            break
        current_edge, next_following = continuation
        current_vert = following_vert
        following_vert = next_following
    return chain


def _build_chains(edges, positions):
    adjacency = {}
    for edge in edges:
        first_vert, second_vert = edge.verts
        adjacency.setdefault(first_vert, []).append((edge, second_vert))
        adjacency.setdefault(second_vert, []).append((edge, first_vert))

    unused = set(edges)
    chains = []
    for vert, links in adjacency.items():
        if len(links) == 2:
            continue
        for edge, other_vert in links:
            if edge in unused:
                chains.append(_walk_chain(vert, edge, other_vert,
                                          adjacency, unused, positions))
    while unused:
        edge = next(iter(unused))
        first_vert, second_vert = edge.verts
        chains.append(_walk_chain(first_vert, edge, second_vert,
                                  adjacency, unused, positions))
    return chains


def _bounds_mapping(source_bounds, target_bounds):
    def transform(point):
        mapped = Vector((0.0, 0.0))
        for index in (0, 1):
            source_size = source_bounds[index + 2] - source_bounds[index]
            target_size = target_bounds[index + 2] - target_bounds[index]
            if source_size <= 0.0:
                mapped[index] = target_bounds[index]
                continue
            ratio = (point[index] - source_bounds[index]) / source_size
            mapped[index] = target_bounds[index] + ratio * target_size
        return mapped

    return transform


def reference_polylines(reference_faces, reference_uv_layer,
                        target_faces, target_uv_layer, fit_bounds):
    positions = _vert_uv_map(reference_faces, reference_uv_layer)
    chains = _build_chains(_interior_edges(reference_faces), positions)
    if not fit_bounds:
        return chains

    transform = _bounds_mapping(
        uv_islands.bounds(reference_faces, reference_uv_layer),
        uv_islands.bounds(target_faces, target_uv_layer))
    return [[transform(point) for point in chain] for chain in chains]


# ---------------------------------------------------------------------------
# 溶解被替换掉的旧布线
# ---------------------------------------------------------------------------


def _uv_continuous(edge, uv_layer, tolerance):
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


def _point_on_pattern(point, segments, tolerance):
    for start, end in segments:
        if distance_to_segment(point, start, end) <= tolerance:
            return True
    return False


def _nearest_segment_direction(point, segments):
    nearest = min(segments,
                  key=lambda segment: distance_to_segment(point, segment[0], segment[1]))
    direction = nearest[1] - nearest[0]
    if direction.length <= 0.0:
        return None
    return direction.normalized()


def dissolve_replaced_edges(bm, uv_layer, faces, polylines, parallel_angle, tolerance):
    segments = [(polyline[index], polyline[index + 1])
                for polyline in polylines
                for index in range(len(polyline) - 1)]
    if not segments:
        return 0

    face_set = set(faces)
    threshold = math.cos(parallel_angle)
    candidates = []
    seen = set()

    for face in faces:
        for loop in face.loops:
            edge = loop.edge
            if edge in seen:
                continue
            seen.add(edge)
            if edge.seam or len(edge.link_faces) != 2:
                continue
            if not all(linked in face_set for linked in edge.link_faces):
                continue
            if not _uv_continuous(edge, uv_layer, tolerance):
                continue

            start = loop[uv_layer].uv.copy()
            end = loop.link_loop_next[uv_layer].uv.copy()
            direction = end - start
            if direction.length <= tolerance:
                continue
            if (_point_on_pattern(start, segments, tolerance)
                    and _point_on_pattern(end, segments, tolerance)):
                continue

            segment_direction = _nearest_segment_direction((start + end) * 0.5, segments)
            if segment_direction is None:
                continue
            if abs(direction.normalized().dot(segment_direction)) < threshold:
                continue
            candidates.append(edge)

    if candidates:
        bmesh.ops.dissolve_edges(bm, edges=candidates, use_verts=True)
    return len(candidates)


# ---------------------------------------------------------------------------
# 算子
# ---------------------------------------------------------------------------


class EditMesh:
    """一个处于编辑模式的网格：算子要用的 bmesh 与活动 UV 层。"""

    __slots__ = ("object", "bm", "uv_layer")

    def __init__(self, mesh_object, bm, uv_layer):
        self.object = mesh_object
        self.bm = bm
        self.uv_layer = uv_layer


class SHIYUME_OT_UVCut(bpy.types.Operator):
    """在 UV 编辑器里直接切割网格。刀路写在 UV 平面上，新顶点的三维位置由所在面插值得到。
    等距网格：把选中孤岛按固定间隔切成等宽条带，并溶解掉被替换的旧布线。
    参考布线：选中两个形状一致的孤岛，照参考孤岛的布线切活动面所在的那个孤岛。"""

    bl_idname = "shiyume.uv_cut"
    bl_label = "UV 切割"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(
        name="刀路",
        items=[
            ("GRID", "等距网格", "按固定间隔在 UV 平面上等距下刀"),
            ("REFERENCE", "参考布线", "照另一个选中孤岛的布线下刀"),
        ],
        default="GRID",
    )
    axis: bpy.props.EnumProperty(
        name="方向",
        items=[
            ("U", "U", "沿 U 轴等距下刀（竖向切线）"),
            ("V", "V", "沿 V 轴等距下刀（横向切线）"),
            ("BOTH", "U + V", "两个方向都切"),
        ],
        default="U",
    )
    interval: bpy.props.FloatProperty(
        name="间隔",
        description="相邻两刀的距离（UV 单位）",
        default=0.01,
        min=0.00001,
        soft_max=1.0,
        precision=5,
    )
    align_to_island: bpy.props.BoolProperty(
        name="对齐到孤岛",
        description="勾选则每个孤岛从自己的边界起算，不勾选则对齐到 UV 原点的全局网格",
        default=False,
    )
    fit_bounds: bpy.props.BoolProperty(
        name="按包围盒对位",
        description="把参考孤岛的包围盒缩放平移到目标孤岛上；不勾选则直接用参考孤岛的 UV 坐标",
        default=True,
    )
    swap_reference: bpy.props.BoolProperty(
        name="对调参考与目标",
        description="默认切活动面所在的孤岛，勾选后改切另一个",
        default=False,
    )
    dissolve_old: bpy.props.BoolProperty(
        name="溶解旧布线",
        description="切完之后溶解掉与刀路同向、又不在刀路上的旧内部边",
        default=True,
    )
    parallel_angle: bpy.props.FloatProperty(
        name="同向判据",
        description="旧边与刀路夹角小于该值即视为同向，会被溶解",
        default=math.radians(45.0),
        min=0.0,
        max=math.radians(90.0),
        subtype="ANGLE",
    )
    tolerance: bpy.props.FloatProperty(
        name="容差",
        description="UV 平面上判定重合与共线的距离容差",
        default=0.00001,
        min=1e-9,
        precision=7,
    )

    @classmethod
    def poll(cls, context):
        return (context.mode == "EDIT_MESH"
                and context.active_object is not None
                and context.active_object.type == "MESH")

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "mode")
        if self.mode == "GRID":
            layout.prop(self, "axis", expand=True)
            layout.prop(self, "interval")
            layout.prop(self, "align_to_island")
        else:
            layout.prop(self, "fit_bounds")
            layout.prop(self, "swap_reference")
        layout.prop(self, "dissolve_old")
        column = layout.column()
        column.enabled = self.dissolve_old
        column.prop(self, "parallel_angle")
        layout.prop(self, "tolerance")

    def _collect_edit_meshes(self, context):
        edit_meshes = []
        for mesh_object in context.objects_in_mode_unique_data:
            if mesh_object.type != "MESH":
                continue
            bm = bmesh.from_edit_mesh(mesh_object.data)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                continue
            bm.faces.ensure_lookup_table()
            edit_meshes.append(EditMesh(mesh_object, bm, uv_layer))
        return edit_meshes

    def _cut_island(self, edit_mesh, work_faces, polylines):
        before = len(edit_mesh.bm.faces)
        faces = cut_faces(edit_mesh.bm, edit_mesh.uv_layer, work_faces,
                          polylines, self.tolerance)
        added = len(edit_mesh.bm.faces) - before
        uv_islands.select_faces(faces)
        dissolved = 0
        if self.dissolve_old:
            dissolved = dissolve_replaced_edges(
                edit_mesh.bm, edit_mesh.uv_layer, [face for face in faces if face.is_valid],
                polylines, self.parallel_angle, self.tolerance)
        return added, dissolved

    def _run_grid(self, context, edit_meshes):
        added = 0
        dissolved = 0
        island_count = 0
        axes = AXIS_SETS[self.axis]
        for edit_mesh in edit_meshes:
            selected = uv_islands.collect_selected_islands(
                edit_mesh.bm, edit_mesh.uv_layer, context.tool_settings)
            for island in selected:
                bounds = uv_islands.bounds(island.selected_faces, edit_mesh.uv_layer)
                polylines = grid_polylines(bounds, axes, self.interval,
                                           self.align_to_island, self.tolerance)
                if not polylines:
                    continue
                island_added, island_dissolved = self._cut_island(
                    edit_mesh, island.selected_faces, polylines)
                added += island_added
                dissolved += island_dissolved
                island_count += 1
        return island_count, added, dissolved

    def _find_active_island(self, context, islands):
        active_object = context.active_object
        for index, (edit_mesh, island) in enumerate(islands):
            if edit_mesh.object != active_object:
                continue
            active_face = edit_mesh.bm.faces.active
            if active_face is not None and active_face in set(island.faces):
                return index
        return None

    def _run_reference(self, context, edit_meshes):
        islands = []
        for edit_mesh in edit_meshes:
            for island in uv_islands.collect_selected_islands(
                    edit_mesh.bm, edit_mesh.uv_layer, context.tool_settings):
                islands.append((edit_mesh, island))

        if len(islands) != 2:
            self.report({"ERROR"},
                        f"参考布线需要正好选中 2 个 UV 孤岛，当前选中 {len(islands)} 个")
            return None

        active_index = self._find_active_island(context, islands)
        if active_index is None:
            self.report({"ERROR"},
                        "找不到活动面所在的孤岛：请在 UV 视图里点一下要被切的那个孤岛")
            return None

        target = islands[active_index]
        reference = islands[1 - active_index]
        if self.swap_reference:
            target, reference = reference, target

        target_mesh, target_island = target
        reference_mesh, reference_island = reference
        polylines = reference_polylines(
            reference_island.faces, reference_mesh.uv_layer,
            target_island.selected_faces, target_mesh.uv_layer,
            self.fit_bounds)
        if not polylines:
            self.report({"WARNING"}, "参考孤岛没有内部边，没有可用的布线")
            return None

        added, dissolved = self._cut_island(
            target_mesh, target_island.selected_faces, polylines)
        return 1, added, dissolved

    def execute(self, context):
        edit_meshes = self._collect_edit_meshes(context)
        if not edit_meshes:
            self.report({"ERROR"}, "编辑模式里没有带 UV 层的网格")
            return {"CANCELLED"}

        if self.mode == "GRID":
            result = self._run_grid(context, edit_meshes)
        else:
            result = self._run_reference(context, edit_meshes)
        if result is None:
            return {"CANCELLED"}

        island_count, added, dissolved = result
        if island_count == 0:
            self.report({"WARNING"}, "没有选中的 UV 孤岛，或间隔大于孤岛尺寸")
            return {"CANCELLED"}

        for edit_mesh in edit_meshes:
            bmesh.update_edit_mesh(edit_mesh.object.data)

        self.report(
            {"INFO"},
            f"切了 {island_count} 个孤岛：新增 {added} 个面，溶解 {dissolved} 条旧边")
        return {"FINISHED"}
