"""顶点组 / 权重工具:清理、限幅、匹配、按组焊接。"""

import bmesh
import bpy
import numpy as np
from mathutils import Vector, kdtree

from ..core import batch


def _armature_bone_names(obj):
    """物体绑定的骨架骨骼名集合;找不到骨架返回 None。"""
    armature = obj.find_armature()
    if armature is None and obj.parent and obj.parent.type == 'ARMATURE':
        armature = obj.parent
    if armature is None:
        return None
    return {bone.name for bone in armature.data.bones}


class SHIYUME_OT_CleanVertexGroups(bpy.types.Operator):
    """清理顶点组(按需勾选):删除骨架里没有同名骨骼的组、
    删除最大权重不超过阈值的空组;白名单里的组永不删除"""
    bl_idname = "shiyume.clean_vertex_groups"
    bl_label = "清理顶点组"
    bl_options = {'REGISTER', 'UNDO'}

    remove_non_bone: bpy.props.BoolProperty(
        name="非骨骼组", default=True,
        description="删除骨架中没有同名骨骼的顶点组(需要物体绑定骨架)",
    )
    remove_empty: bpy.props.BoolProperty(
        name="空组", default=True,
        description="删除最大权重不超过阈值的顶点组",
    )
    empty_threshold: bpy.props.FloatProperty(
        name="空组阈值", default=0.0, min=0.0, max=1.0,
        description="组内最大权重不超过该值即视为空组",
    )
    whitelist: bpy.props.StringProperty(
        name="白名单", default="Alpha,Red,Green,Blue",
        description="逗号分隔;这些名字的组永不删除",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        column = layout.column(heading="清理项")
        column.prop(self, "remove_non_bone")
        column.prop(self, "remove_empty")
        row = layout.row()
        row.active = self.remove_empty
        row.prop(self, "empty_threshold")
        layout.prop(self, "whitelist")

    def execute(self, context):
        protected = {name.strip() for name in self.whitelist.split(',') if name.strip()}
        removed_total = 0

        for obj in context.selected_objects:
            if obj.type != 'MESH' or not obj.vertex_groups:
                continue

            bone_names = _armature_bone_names(obj) if self.remove_non_bone else None
            if self.remove_non_bone and bone_names is None:
                self.report({'WARNING'}, f"'{obj.name}' 未绑定骨架,跳过非骨骼组清理")

            # 一趟扫过所有形变条目,得到每组的最大权重
            group_count = len(obj.vertex_groups)
            max_weights = np.zeros(group_count, dtype=np.float32)
            if self.remove_empty:
                for vertex in obj.data.vertices:
                    for entry in vertex.groups:
                        if entry.weight > max_weights[entry.group]:
                            max_weights[entry.group] = entry.weight

            to_remove = []
            for group in obj.vertex_groups:
                if group.name in protected:
                    continue
                if bone_names is not None and group.name not in bone_names:
                    to_remove.append(group.index)
                    continue
                if self.remove_empty and max_weights[group.index] <= self.empty_threshold:
                    to_remove.append(group.index)

            for index in sorted(to_remove, reverse=True):
                obj.vertex_groups.remove(obj.vertex_groups[index])
            removed_total += len(to_remove)

        self.report({'INFO'}, f"已删除 {removed_total} 个顶点组")
        return {'FINISHED'}


class SHIYUME_OT_LimitWeights(bpy.types.Operator):
    """修剪顶点权重:先剔除低于最小权重的影响,再按最大组数保留最大的几个,
    最后可选归一化。游戏引擎通常限制每顶点 4 根骨骼"""
    bl_idname = "shiyume.limit_weights"
    bl_label = "修剪权重"
    bl_options = {'REGISTER', 'UNDO'}

    max_groups: bpy.props.IntProperty(
        name="最大组数", default=4, min=1,
        description="每个顶点保留的最大权重条目数",
    )
    min_weight: bpy.props.FloatProperty(
        name="最小权重", default=0.01, min=0.0, max=1.0,
        description="低于此值的权重直接剔除",
    )
    selected_only: bpy.props.BoolProperty(
        name="仅选中顶点", default=False,
        description="只处理编辑模式下选中的顶点",
    )
    bone_only: bpy.props.BoolProperty(
        name="仅骨骼组", default=False,
        description="只处理与骨架骨骼同名的顶点组,遮罩类组不受影响",
    )
    normalize: bpy.props.BoolProperty(
        name="归一化", default=True,
        description="修剪后把参与处理的组的权重归一化到 1",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        column = layout.column(align=True)
        column.prop(self, "max_groups")
        column.prop(self, "min_weight")
        column = layout.column(heading="范围")
        column.prop(self, "selected_only")
        column.prop(self, "bone_only")
        layout.prop(self, "normalize")

    def execute(self, context):
        obj = context.active_object
        in_edit = obj.mode == 'EDIT'

        if in_edit:
            working = bmesh.from_edit_mesh(obj.data)
        else:
            working = bmesh.new()
            working.from_mesh(obj.data)

        deform_layer = working.verts.layers.deform.active
        if deform_layer is None:
            if not in_edit:
                working.free()
            self.report({'ERROR'}, "物体没有顶点组")
            return {'CANCELLED'}

        scope_indices = None
        if self.bone_only:
            bone_names = _armature_bone_names(obj)
            if bone_names:
                scope_indices = {
                    group.index for group in obj.vertex_groups if group.name in bone_names
                }

        pruned_vertices = 0
        for vertex in working.verts:
            if self.selected_only and not vertex.select:
                continue
            deform = vertex[deform_layer]
            entries = [
                (group, weight) for group, weight in deform.items()
                if scope_indices is None or group in scope_indices
            ]
            if not entries:
                continue

            for group, weight in entries:
                if weight < self.min_weight:
                    del deform[group]
            entries = [
                (group, weight) for group, weight in deform.items()
                if scope_indices is None or group in scope_indices
            ]

            if len(entries) > self.max_groups:
                entries.sort(key=lambda pair: pair[1], reverse=True)
                for group, _weight in entries[self.max_groups:]:
                    del deform[group]
                entries = entries[:self.max_groups]

            if self.normalize:
                total = sum(weight for _group, weight in entries)
                if total > 0.0:
                    for group, weight in entries:
                        deform[group] = weight / total
            pruned_vertices += 1

        if in_edit:
            bmesh.update_edit_mesh(obj.data)
        else:
            working.to_mesh(obj.data)
            working.free()
            obj.data.update()

        self.report({'INFO'}, f"已修剪 {pruned_vertices} 个顶点的权重")
        return {'FINISHED'}


class SHIYUME_OT_MatchWeightsActive(bpy.types.Operator):
    """把激活顶点的全部权重复制到其他选中顶点,
    并删除这些顶点上激活顶点没有的组 —— 快速统一一片顶点的权重"""
    bl_idname = "shiyume.match_weights_active"
    bl_label = "权重匹配激活点"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        obj = context.active_object
        working = bmesh.from_edit_mesh(obj.data)

        deform_layer = working.verts.layers.deform.active
        if deform_layer is None:
            self.report({'WARNING'}, "物体没有顶点组")
            return {'CANCELLED'}

        active_vertex = working.select_history.active
        if not isinstance(active_vertex, bmesh.types.BMVert):
            self.report({'WARNING'}, "需要一个激活顶点(最后点选的顶点)")
            return {'CANCELLED'}

        active_weights = dict(active_vertex[deform_layer].items())
        matched = 0
        for vertex in working.verts:
            if not vertex.select or vertex is active_vertex:
                continue
            deform = vertex[deform_layer]
            for group in [group for group in deform.keys() if group not in active_weights]:
                del deform[group]
            for group, weight in active_weights.items():
                deform[group] = weight
            matched += 1

        bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'}, f"已匹配 {matched} 个顶点")
        return {'FINISHED'}


class SHIYUME_OT_WeldByVertexGroup(bpy.types.Operator):
    """按顶点组伪焊接:指定组内权重达标的顶点,把彼此距离小于阈值的
    聚成一簇并全部移到簇质心 —— 看起来焊上了,拓扑仍是分开的。
    KD 树近邻 + 并查集聚类,复杂度 O(n log n)"""
    bl_idname = "shiyume.weld_by_vertex_group"
    bl_label = "按顶点组伪焊接"
    bl_options = {'REGISTER', 'UNDO'}

    vertex_group: bpy.props.StringProperty(
        name="顶点组", default="Edge",
        description="参与焊接的顶点组名",
    )
    min_weight: bpy.props.FloatProperty(
        name="最小权重", default=0.1, min=0.0, max=1.0,
        description="组内权重超过该值的顶点才参与焊接",
    )
    distance: bpy.props.FloatProperty(
        name="距离阈值", default=0.001, min=0.0, precision=5, unit='LENGTH',
        description="彼此距离小于该值的顶点归为一簇",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop_search(self, "vertex_group", context.active_object, "vertex_groups")
        layout.prop(self, "min_weight")
        layout.prop(self, "distance")

    def execute(self, context):
        obj = context.active_object
        group_index = obj.vertex_groups.find(self.vertex_group)
        if group_index == -1:
            self.report({'WARNING'}, f"未找到顶点组 '{self.vertex_group}'")
            return {'CANCELLED'}

        was_edit = obj.mode == 'EDIT'
        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')

        mesh = obj.data
        coordinates = batch.read_float(mesh.vertices, "co", 3)

        candidates = [
            vertex.index
            for vertex in mesh.vertices
            for entry in vertex.groups
            if entry.group == group_index and entry.weight > self.min_weight
        ]

        moved = 0
        if len(candidates) >= 2:
            tree = kdtree.KDTree(len(candidates))
            for local, vertex_index in enumerate(candidates):
                tree.insert(Vector(coordinates[vertex_index]), local)
            tree.balance()

            clusters = batch.UnionFind(len(candidates))
            for local, vertex_index in enumerate(candidates):
                for _position, other_local, _distance in tree.find_range(
                        Vector(coordinates[vertex_index]), self.distance):
                    if other_local != local:
                        clusters.union(local, other_local)

            members_by_root = {}
            for local in range(len(candidates)):
                members_by_root.setdefault(clusters.find(local), []).append(local)

            for members in members_by_root.values():
                if len(members) < 2:
                    continue
                vertex_indices = [candidates[local] for local in members]
                centroid = coordinates[vertex_indices].mean(axis=0)
                coordinates[vertex_indices] = centroid
                moved += len(vertex_indices)

            batch.write_float(mesh.vertices, "co", coordinates)
            mesh.update()

        if was_edit:
            bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, f"已聚拢 {moved} 个顶点")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_CleanVertexGroups,
    SHIYUME_OT_LimitWeights,
    SHIYUME_OT_MatchWeightsActive,
    SHIYUME_OT_WeldByVertexGroup,
)
