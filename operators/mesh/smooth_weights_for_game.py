import bmesh
import bpy
import numpy

from . import game_weight_smoothing


GROUP_SELECT_MODES = [
    ("ACTIVE", "活动组", "只平滑活动顶点组"),
    ("BONE_SELECT", "选中骨骼的组", "只平滑与选中骨骼同名的顶点组"),
    ("BONE_DEFORM", "变形骨骼的组", "只平滑与变形骨骼同名的顶点组"),
    ("ALL", "全部组", "平滑全部顶点组"),
]


def subset_group_indices(obj, mode):
    armature = obj.find_armature()
    if mode == "ACTIVE":
        active = obj.vertex_groups.active_index
        return [] if active < 0 else [active]
    if mode == "ALL":
        return list(range(len(obj.vertex_groups)))
    if armature is None:
        return []
    if mode == "BONE_DEFORM":
        names = {bone.name for bone in armature.data.bones if bone.use_deform}
    else:
        names = {bone.name for bone in armature.data.bones if bone.select}
    return [group.index for group in obj.vertex_groups if group.name in names]


LIMIT_SCOPES = [
    ("SMOOTH_SET", "与平滑范围相同", "数量限制作用于参与平滑的那批顶点组"),
    ("DEFORM", "变形骨骼的组", "数量限制只作用于与变形骨骼同名的顶点组，其余组不计数也不删"),
    ("ALL", "全部组", "数量限制作用于全部顶点组，无论是否对应骨骼"),
]


def influence_group_indices(obj, scope, subset, locked):
    if scope == "SMOOTH_SET":
        indices = list(subset)
    elif scope == "ALL":
        indices = list(range(len(obj.vertex_groups)))
    else:
        armature = obj.find_armature()
        if armature is None:
            indices = list(range(len(obj.vertex_groups)))
        else:
            names = {bone.name for bone in armature.data.bones if bone.use_deform}
            indices = [group.index for group in obj.vertex_groups if group.name in names]
    return [index for index in indices if index not in locked]


class SHIYUME_OT_SmoothWeightsForGame(bpy.types.Operator):
    """平滑权重（游戏）：与 Blender 自带的「平滑顶点权重」逐位同算法，但每个顶点最终至多保留 N 个影响。
    平滑先不受限地算到底，再对每个顶点取最大的 N 个组，并按欧氏距离最小的方式把被丢掉的权重摊给它们，
    所以不会像自带平滑那样不断吸收周围的组而膨胀，小权重也照样能扩散，平滑效果不打折。
    只改写选中的顶点（编辑模式或带顶点选择遮罩的权重绘制），其余模式处理全部顶点；锁定的组不动。
    N 限制只计数变形骨骼对应的顶点组（没有骨架时计数全部组）。"""
    bl_idname = "shiyume.smooth_weights_for_game"
    bl_label = "平滑权重 (游戏)"
    bl_options = {'REGISTER', 'UNDO'}

    group_select_mode: bpy.props.EnumProperty(
        name="顶点组", items=GROUP_SELECT_MODES, default="ALL",
        description="参与平滑的顶点组范围")
    factor: bpy.props.FloatProperty(name="系数", default=0.5, min=0.0, max=1.0)
    repeat: bpy.props.IntProperty(name="迭代次数", default=1, min=1, max=10000, soft_max=200)
    expand: bpy.props.FloatProperty(
        name="扩张/收缩", default=0.0, min=-1.0, max=1.0, description="与自带平滑相同：正值扩张权重，负值收缩权重")
    keep_total: bpy.props.BoolProperty(
        name="保持权重总量", default=True,
        description="平滑和限制数量之后，把每个顶点受限顶点组的权重总和恢复成平滑前的值，平滑只重新分配、不削弱影响力；关闭则总量随平滑自然衰减，与自带平滑一致")
    preserve_features: bpy.props.BoolProperty(
        name="保持尖锐特征", default=True,
        description="开启后权重断崖两侧的传导按差异衰减，断崖在整个迭代里不被抹平；关闭则与自带平滑完全一致")
    feature_threshold: bpy.props.FloatProperty(
        name="特征阈值", default=1.5, min=0.2, max=10.0,
        description="相邻顶点权重差异超过这片区域典型差异（90 分位）的这么多倍时视为尖锐特征并停止在此处平滑；越小保护越多，越大越接近普通平滑")
    limit_scope: bpy.props.EnumProperty(
        name="数量限制范围", items=LIMIT_SCOPES, default="DEFORM",
        description="哪些顶点组计入最大影响数；被锁定的顶点组永远既不平滑也不计数，遮罩之类的组请先锁定")
    max_influences: bpy.props.IntProperty(
        name="最大影响数", default=4, min=1, max=64, description="每个顶点最多保留的骨骼权重数量")
    normalize: bpy.props.BoolProperty(
        name="归一化到 1", default=False,
        description="开启时把每个顶点受限顶点组的权重总和固定为 1，优先于「保持权重总量」")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and len(obj.vertex_groups) > 0

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        in_edit_mode = obj.mode == 'EDIT'
        use_selection = in_edit_mode or (obj.mode == 'WEIGHT_PAINT' and mesh.use_paint_mask_vertex)

        if in_edit_mode:
            bm = bmesh.from_edit_mesh(mesh)
        else:
            bm = bmesh.new()
            bm.from_mesh(mesh)
        bm.verts.index_update()

        deform_layer = bm.verts.layers.deform.active
        if deform_layer is None:
            self.report({'ERROR'}, "网格没有顶点权重")
            return self._finish(bm, mesh, in_edit_mode, False, {'CANCELLED'})

        locked = {group.index for group in obj.vertex_groups if group.lock_weight}
        subset = [index for index in subset_group_indices(obj, self.group_select_mode) if index not in locked]
        if not subset:
            self.report({'WARNING'}, "没有可平滑的顶点组（模式里没有匹配的组，或全部被锁定）")
            return self._finish(bm, mesh, in_edit_mode, False, {'CANCELLED'})
        influence = set(influence_group_indices(obj, self.limit_scope, subset, locked))
        subset_set = set(subset)
        group_count = len(obj.vertex_groups)
        vertex_count = len(bm.verts)

        entry_rows = []
        entry_groups = []
        entry_values = []
        for vertex in bm.verts:
            for group, weight in vertex[deform_layer].items():
                entry_rows.append(vertex.index)
                entry_groups.append(group)
                entry_values.append(weight)
        rows = numpy.array(entry_rows, dtype=numpy.int64)
        groups = numpy.array(entry_groups, dtype=numpy.int64)
        values = numpy.array(entry_values, dtype=numpy.float64)

        if use_selection:
            writable = numpy.array([vertex.select for vertex in bm.verts], dtype=bool)
            readable = numpy.array([not vertex.hide for vertex in bm.verts], dtype=bool)
        else:
            writable = numpy.ones(vertex_count, dtype=bool)
            readable = numpy.ones(vertex_count, dtype=bool)
        edges = numpy.array([(edge.verts[0].index, edge.verts[1].index) for edge in bm.edges],
                            dtype=numpy.int64).reshape(-1, 2)
        graph = game_weight_smoothing.SmoothingGraph(vertex_count, edges, writable, readable)
        if not writable.any():
            self.report({'WARNING'}, "没有选中的顶点")
            return self._finish(bm, mesh, in_edit_mode, False, {'CANCELLED'})

        in_subset = numpy.isin(groups, subset)
        smoothed_keys, smoothed_values = game_weight_smoothing.smooth(
            graph, group_count, rows[in_subset] * group_count + groups[in_subset], values[in_subset],
            self.factor, self.repeat, self.expand,
            self.feature_threshold if self.preserve_features else 0.0)
        smoothed_rows = smoothed_keys // group_count
        smoothed_groups = smoothed_keys % group_count

        influence_list = list(influence)
        in_influence = numpy.isin(groups, influence_list)
        carried_all = in_influence & ~in_subset
        counted_all = numpy.isin(smoothed_groups, influence_list)
        full_keys = numpy.concatenate((smoothed_keys[counted_all], rows[carried_all] * group_count + groups[carried_all]))
        full_values = numpy.concatenate((smoothed_values[counted_all], values[carried_all]))
        score_keys, score_values = game_weight_smoothing.support_scores(graph, group_count, full_keys, full_values)

        original_mass = numpy.bincount(rows[in_influence], values[in_influence], minlength=vertex_count)
        union_keys = numpy.unique(numpy.concatenate((full_keys, score_keys)))
        union_keys = union_keys[writable[union_keys // group_count]]
        counted_rows = union_keys // group_count
        counted_groups = union_keys % group_count
        counted_values = game_weight_smoothing.lookup(numpy.sort(full_keys), full_values[numpy.argsort(full_keys, kind="stable")], union_keys)
        counted_ranking = game_weight_smoothing.lookup(score_keys, score_values, union_keys)

        mass = None
        if self.normalize:
            mass = numpy.where(original_mass > 0.0, 1.0, 0.0)
        elif self.keep_total:
            mass = original_mass
        before_over = int((numpy.bincount(counted_rows[counted_values > 0.0], minlength=vertex_count)
                           > self.max_influences).sum())
        limited_rows, limited_groups, limited_values = game_weight_smoothing.limit_influences(
            vertex_count, counted_rows, counted_groups, counted_values, counted_ranking, self.max_influences, mass)

        on_written = writable[smoothed_rows]
        free = on_written & ~counted_all
        free_rows = smoothed_rows[free]
        free_groups = smoothed_groups[free]
        free_values = smoothed_values[free]
        final_rows = numpy.concatenate((limited_rows, free_rows))
        final_groups = numpy.concatenate((limited_groups, free_groups))
        final_values = numpy.concatenate((limited_values, free_values))

        touched = sorted(subset_set | influence)
        by_row = {}
        for row, group, weight in zip(final_rows.tolist(), final_groups.tolist(), final_values.tolist()):
            by_row.setdefault(row, []).append((group, weight))
        for vertex in bm.verts:
            if not writable[vertex.index]:
                continue
            deform = vertex[deform_layer]
            for group in touched:
                if group in deform:
                    del deform[group]
            for group, weight in by_row.get(vertex.index, ()):
                deform[group] = weight

        self.report({'INFO'}, "平滑了 %d 个顶点；处理范围内共有 %d 个顶点超过 %d 个影响（含原本就超限的），已全部按最优投影收敛" % (
            int(graph.used.sum()), before_over, self.max_influences))
        return self._finish(bm, mesh, in_edit_mode, True, {'FINISHED'})

    @staticmethod
    def _finish(bm, mesh, in_edit_mode, changed, result):
        if in_edit_mode:
            if changed:
                bmesh.update_edit_mesh(mesh)
        else:
            if changed:
                bm.to_mesh(mesh)
            bm.free()
        return result
