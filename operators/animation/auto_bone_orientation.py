"""编辑模式修骨骼朝向：移植自 better_fbx 的 Automatic Bone Orientation。

算法逐行照抄 better_fbx importer.py:770-803（tail 取子骨骼 head 平均、叶骨沿父链续、
1e-3 零长度兜底、可选 calculate_roll），差别只有三处：
① 能对已经导进来的骨架随时重跑，不必重新导入；
② 单子骨骼链额外勾上 use_connect（多子骨骼一律不连，朝向本来就是猜的）；
③ 静置朝向变了会让既有姿态/动作错位，这里把它们换算回原样（对应 better_fbx 导入时的 CorrectPose）。
"""

import bpy
from mathutils import Euler, Quaternion, Vector

from ._compat import list_action_fcurves, new_fcurve

_LEAF_BONE_SCALE = {'Long': 1.0, 'Short': 0.1}

# better_fbx importer.py:790 的零长度判据
_MINIMUM_LENGTH = 1e-3

_CHANNEL_SIZE = {
    'location': 3,
    'rotation_quaternion': 4,
    'rotation_euler': 3,
    'rotation_axis_angle': 4,
}

_ROTATION_CHANNEL = {
    'QUATERNION': 'rotation_quaternion',
    'AXIS_ANGLE': 'rotation_axis_angle',
}

_EULER_ORDERS = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}

_IDENTITY_TOLERANCE = 1e-6


def _is_identity(matrix):
    for row in range(4):
        for column in range(4):
            expected = 1.0 if row == column else 0.0
            if abs(matrix[row][column] - expected) > _IDENTITY_TOLERANCE:
                return False
    return True


def _plan_tail(bone, leaf_scale):
    """better_fbx importer.py:777-788：有子骨骼取其 head 平均，叶骨沿父→自己方向续，根叶骨不动。"""
    children = bone.children
    if len(children) > 0:
        point = Vector((0.0, 0.0, 0.0))
        for child in children:
            point += child.head
        return point / len(children)
    if bone.parent:
        return bone.head + (bone.head - bone.parent.head) * leaf_scale
    return bone.tail.copy()


def _prepare_correction(correction):
    """一根骨骼算一次，避免每个关键帧都去做矩阵求逆。"""
    inverse = correction.inverted_safe()
    forward = correction.to_quaternion()
    return inverse.to_3x3(), inverse.translation.copy(), forward, forward.inverted()


def _transform_channel(channel, values, prepared, rotation_mode, previous):
    """把一组通道值搬进新的静置空间。

    静置矩阵从 R 改成 R' 后，要让蒙皮形变与世界姿态都不变，局部姿态必须做共轭：
    B' = K⁻¹ B K，K = R⁻¹R'。位移与旋转互不耦合，均匀缩放不变，所以可以逐通道算。
    这与 better_fbx importer.py:1048-1052 的 CorrectPose（旋转轴、角度不变）是同一件事。
    返回 (新值, 供下一帧做连续性判断的对象)。
    """
    inverse_basis, inverse_offset, forward, backward = prepared
    if channel == 'location':
        return list(inverse_basis @ Vector(values) + inverse_offset), None

    if channel == 'rotation_quaternion':
        result = backward @ Quaternion(values) @ forward
        if previous is not None and result.dot(previous) < 0.0:
            result.negate()
        return [result.w, result.x, result.y, result.z], result

    if channel == 'rotation_euler':
        order = rotation_mode if rotation_mode in _EULER_ORDERS else 'XYZ'
        rotated = backward @ Euler(values, order).to_quaternion() @ forward
        result = rotated.to_euler(order, previous if previous is not None else Euler((0.0, 0.0, 0.0), order))
        return list(result), result

    axis = Vector(values[1:])
    if axis.length < 1e-9:
        return list(values), None
    return [values[0]] + list(backward @ axis), None


def _is_neutral_pose(pose_bone, rotation_channel):
    """静置姿态共轭之后还是静置，可以整根跳过，免得写进一堆浮点噪声。"""
    if pose_bone.location.length > 1e-9:
        return False
    if rotation_channel == 'rotation_quaternion':
        return 1.0 - abs(pose_bone.rotation_quaternion.w) < 1e-9
    if rotation_channel == 'rotation_axis_angle':
        return abs(pose_bone.rotation_axis_angle[0]) < 1e-9
    return max(abs(value) for value in pose_bone.rotation_euler) < 1e-9


def _write_curve(fcurve, times, values):
    """按时间写回取值：已有关键帧就地改，缺的补插；贝塞尔手柄交给自动重算。"""
    existing = {round(point.co.x, 4): point for point in fcurve.keyframe_points}
    for time, value in zip(times, values):
        point = existing.get(time)
        if point is None:
            point = fcurve.keyframe_points.insert(time, value, options={'FAST'})
        else:
            point.co.y = value
        if point.interpolation == 'BEZIER':
            point.handle_left_type = 'AUTO_CLAMPED'
            point.handle_right_type = 'AUTO_CLAMPED'
    fcurve.update()


class SHIYUME_OT_AutoBoneOrientation(bpy.types.Operator):
    """自动骨骼朝向：把每根骨骼的 tail 指向子骨骼（多个子骨骼取其 head 平均），
    叶骨沿父链方向续出去，专治别的软件导进来朝向丢失、骨头全朝一个方向的骨架。
    只有单子骨骼的一级链会额外勾上"连接"，多子骨骼不连。
    head 一律不动，蒙皮绑定不受影响；既有姿态与本骨架用到的动作会被换算回原样。
    编辑模式下有选中骨骼就只处理选中的，没选中就处理整副骨架。"""
    bl_idname = "shiyume.auto_bone_orientation"
    bl_label = "自动骨骼朝向"
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="处理范围",
        items=[
            ('AUTO', "自动", "有选中骨骼就只处理选中的，没选中就处理整副骨架"),
            ('SELECTED', "仅选中", "只处理选中的骨骼"),
            ('ALL', "整副骨架", "处理骨架里的全部骨骼"),
        ],
        default='AUTO',
    )
    leaf_bone: bpy.props.EnumProperty(
        name="叶骨长度",
        items=[
            ('Long', "Long", "父骨长度的 1/1"),
            ('Short', "Short", "父骨长度的 1/10"),
        ],
        default='Long',
    )
    calculate_roll: bpy.props.EnumProperty(
        name="重算 roll",
        description="改完朝向后按指定轴重算骨骼 roll；None 表示不动 roll",
        items=[(value, value, value) for value in (
            'None', 'POS_X', 'POS_Z', 'GLOBAL_POS_X', 'GLOBAL_POS_Y', 'GLOBAL_POS_Z',
            'NEG_X', 'NEG_Z', 'GLOBAL_NEG_X', 'GLOBAL_NEG_Y', 'GLOBAL_NEG_Z', 'ACTIVE', 'VIEW', 'CURSOR',
        )],
        default='None',
    )
    connect_single_chains: bpy.props.BoolProperty(
        name="连接单子骨骼链",
        description="只有一个子骨骼时 tail 正好落在子 head 上，给它勾上连接；多子骨骼一律不连",
        default=True,
    )
    preserve_animation: bpy.props.BoolProperty(
        name="补偿姿态与动画",
        description="静置朝向变了会让既有姿态/动作曲线错位，勾上会把它们换算回原来的效果",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        edit_bones = obj.data.edit_bones

        original = {bone.name: bone.matrix.copy() for bone in edit_bones}
        selection = {bone.name: bone.select for bone in edit_bones}

        targets = self._collect_targets(edit_bones, selection)
        if not targets:
            self.report({'WARNING'}, "没有可处理的骨骼")
            return {'CANCELLED'}

        leaf_scale = _LEAF_BONE_SCALE[self.leaf_bone]
        planned = {bone.name: _plan_tail(bone, leaf_scale) for bone in targets}

        oriented = 0
        shortened = 0
        for name, point in planned.items():
            bone = edit_bones[name]
            previous_tail = bone.tail.copy()
            if (point - bone.head).length > _MINIMUM_LENGTH:
                bone.tail = point
            else:
                # better_fbx 原式 `head + matrix @ Vector((0,1,0)) * 0.01` 会把 head 一起缩放
                # （mathutils 的 4x4 @ 3D 向量带平移），这里按其"造一根极短骨骼"的本意写
                bone.tail = bone.head + bone.y_axis * 0.01
                shortened += 1
            if (bone.tail - previous_tail).length > 1e-9:
                oriented += 1

        if self.calculate_roll != 'None':
            for bone in edit_bones:
                bone.select = bone.name in planned
            bpy.ops.armature.calculate_roll(type=self.calculate_roll)
            for bone in edit_bones:
                bone.select = selection[bone.name]

        connected = 0
        kept_loose = 0
        if self.connect_single_chains:
            # 连上之后这根骨骼的 location 通道就彻底失效了，有位移在用的一律不连
            live_locations = self._live_location_bones(obj) if self.preserve_animation else set()
            for name in planned:
                bone = edit_bones[name]
                if len(bone.children) != 1:
                    continue
                child = bone.children[0]
                if child.use_connect or (child.head - bone.tail).length > 1e-6:
                    continue
                if child.name in live_locations:
                    kept_loose += 1
                    continue
                child.use_connect = True
                connected += 1

        corrections = {}
        for bone in edit_bones:
            change = original[bone.name].inverted_safe() @ bone.matrix
            if not _is_identity(change):
                corrections[bone.name] = change

        compensated_bones = 0
        compensated_curves = 0
        if self.preserve_animation and corrections:
            compensated_bones, compensated_curves = self._compensate(obj, corrections)

        message = f"改朝向 {oriented} 根，接单链 {connected} 处"
        if kept_loose:
            message += f"，{kept_loose} 处有位移动画未连接"
        if shortened:
            message += f"，{shortened} 根退化成极短骨骼"
        if compensated_bones or compensated_curves:
            message += f"，补偿姿态 {compensated_bones} 根 / 曲线 {compensated_curves} 条"
        self.report({'INFO'}, message)
        return {'FINISHED'}

    def _collect_targets(self, edit_bones, selection):
        selected = [bone for bone in edit_bones if selection[bone.name]]
        if self.scope == 'ALL' or (self.scope == 'AUTO' and not selected):
            return list(edit_bones)
        return selected

    def _live_location_bones(self, obj):
        """location 通道真的在用的骨骼：静态位移非零，或动作里有非零位移关键帧。"""
        live = {bone.name for bone in obj.pose.bones if bone.location.length > 1e-9}
        for action in self._actions_driving(obj):
            for _owner, fcurve in list_action_fcurves(action):
                path = fcurve.data_path
                if not path.startswith('pose.bones["') or not path.endswith('.location'):
                    continue
                if any(abs(point.co.y) > 1e-9 for point in fcurve.keyframe_points):
                    live.add(path.split('"')[1])
        return live

    @staticmethod
    def _actions_driving(obj):
        actions = set()
        anim_data = obj.animation_data
        if anim_data is None:
            return actions
        if anim_data.action is not None:
            actions.add(anim_data.action)
        for track in anim_data.nla_tracks:
            for strip in track.strips:
                if strip.action is not None:
                    actions.add(strip.action)
        return actions

    def _compensate(self, obj, corrections):
        animated = {}
        curves = 0
        for action in self._actions_driving(obj):
            curves += self._compensate_action(action, corrections, obj.pose, animated)

        pending = self._plan_static(obj, corrections, animated)
        if pending:
            bpy.ops.object.mode_set(mode='OBJECT')
            for name, attribute, values in pending:
                setattr(obj.pose.bones[name], attribute, values)
            bpy.ops.object.mode_set(mode='EDIT')
        return len({name for name, _attribute, _values in pending}), curves

    def _compensate_action(self, action, corrections, pose, animated):
        groups = {}
        for owner, fcurve in list_action_fcurves(action):
            path = fcurve.data_path
            if not path.startswith('pose.bones["'):
                continue
            channel = path.rsplit('.', 1)[-1]
            if channel not in _CHANNEL_SIZE:
                continue
            bone_name = path.split('"')[1]
            if bone_name not in corrections:
                continue
            groups.setdefault((bone_name, path, channel), (owner, {}))[1][fcurve.array_index] = fcurve

        touched = 0
        for (bone_name, path, channel), (owner, existing) in groups.items():
            times = sorted({round(point.co.x, 4) for curve in existing.values() for point in curve.keyframe_points})
            if not times:
                continue
            pose_bone = pose.bones.get(bone_name)
            rotation_mode = pose_bone.rotation_mode if pose_bone else 'QUATERNION'
            defaults = self._channel_defaults(channel, pose_bone)
            prepared = _prepare_correction(corrections[bone_name])

            previous = None
            samples = []
            for time in times:
                values = [
                    existing[index].evaluate(time) if index in existing else defaults[index]
                    for index in range(_CHANNEL_SIZE[channel])
                ]
                transformed, previous = _transform_channel(channel, values, prepared, rotation_mode, previous)
                samples.append(transformed)

            for index in range(_CHANNEL_SIZE[channel]):
                if index not in existing:
                    existing[index] = new_fcurve(owner, path, index)
            for index, curve in existing.items():
                _write_curve(curve, times, [sample[index] for sample in samples])
                touched += 1
            animated.setdefault(bone_name, set()).add(channel)
        return touched

    def _plan_static(self, obj, corrections, animated):
        """没被曲线驱动的通道，姿态值也要跟着共轭一次，否则摆好的姿势会歪掉。"""
        pending = []
        for name, correction in corrections.items():
            pose_bone = obj.pose.bones.get(name)
            if pose_bone is None:
                continue
            driven = animated.get(name, ())
            rotation_channel = _ROTATION_CHANNEL.get(pose_bone.rotation_mode, 'rotation_euler')
            # head 没动时 K 的平移只剩浮点抵消残渣（约 1e-7 m），拿微米当判据
            if not driven and correction.translation.length < 1e-6 and _is_neutral_pose(pose_bone, rotation_channel):
                continue
            prepared = _prepare_correction(correction)
            for channel in ('location', rotation_channel):
                if channel in driven:
                    continue
                values = list(getattr(pose_bone, channel))
                transformed, _previous = _transform_channel(channel, values, prepared, pose_bone.rotation_mode, None)
                if any(abs(new - old) > 1e-7 for new, old in zip(transformed, values)):
                    pending.append((name, channel, transformed))
        return pending

    @staticmethod
    def _channel_defaults(channel, pose_bone):
        if pose_bone is not None:
            return list(getattr(pose_bone, channel))
        if channel == 'rotation_quaternion':
            return [1.0, 0.0, 0.0, 0.0]
        if channel == 'rotation_axis_angle':
            return [0.0, 0.0, 1.0, 0.0]
        return [0.0, 0.0, 0.0]
