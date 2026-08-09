"""编辑模式一键接骨架链：tail 对齐子骨骼 head + use_connect，并把既有姿态/动画补偿回原样。

对标 better_fbx 的 Automatic Bone Orientation，差别：真正设 use_connect、多子骨骼按名字链/最远
子骨骼挑主链而不是无脑取平均、roll 用最小扭转保住原轴向、叶骨默认只改朝向不改长度、
可对已经导进来的骨架随时重跑。
"""

import re

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from ._compat import list_action_fcurves, new_fcurve

_DIGIT_GROUP = re.compile(r"\d+")

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


def _successor_names(name):
    """名字链后继候选：任一数字段 +1（保留零填充宽度）；整个名字没有数字时退化为追加 1。"""
    candidates = set()
    for match in _DIGIT_GROUP.finditer(name):
        raw = match.group()
        incremented = str(int(raw) + 1)
        for text in (incremented.zfill(len(raw)), incremented):
            candidates.add(name[:match.start()] + text + name[match.end():])
    if not candidates:
        candidates.update(name + suffix for suffix in ("1", "01", "_1", "_01"))
    return candidates


def _is_identity(matrix):
    for row in range(4):
        for column in range(4):
            expected = 1.0 if row == column else 0.0
            if abs(matrix[row][column] - expected) > _IDENTITY_TOLERANCE:
                return False
    return True


def _plan_chain_tail(bone, strategy):
    """返回 (新 tail 坐标, 作为主链下一节的子骨骼)；子骨骼为 None 表示不产生连接。"""
    children = bone.children
    if not children:
        return None, None
    if len(children) == 1:
        return children[0].head.copy(), children[0]
    if strategy == 'SKIP':
        return None, None
    if strategy == 'AVERAGE':
        point = Vector((0.0, 0.0, 0.0))
        for child in children:
            point += child.head
        return point / len(children), None

    successors = _successor_names(bone.name)
    for child in children:
        if child.name in successors:
            return child.head.copy(), child
    if strategy == 'NAME':
        return None, None
    child = max(children, key=lambda candidate: (candidate.head - bone.head).length_squared)
    return child.head.copy(), child


def _plan_leaf_tail(bone, mode, ratio):
    """叶骨没有子骨骼可指，沿着父骨骼→自己的方向续出去。"""
    if mode == 'SKIP' or bone.parent is None:
        return None
    direction = bone.head - bone.parent.head
    if direction.length < 1e-9:
        return None
    length = (bone.tail - bone.head).length if mode == 'KEEP' else direction.length * ratio
    if length < 1e-9:
        return None
    return bone.head + direction.normalized() * length


def _prepare_correction(correction):
    """一根骨骼算一次，避免每个关键帧都去做矩阵求逆。"""
    inverse = correction.inverted_safe()
    forward = correction.to_quaternion()
    return inverse.to_3x3(), inverse.translation.copy(), forward, forward.inverted()


def _transform_channel(channel, values, prepared, rotation_mode, previous):
    """把一组通道值搬进新的静置空间。

    静置矩阵从 R 改成 R' 后，要让蒙皮形变与世界姿态都不变，局部姿态必须做共轭：
    B' = K⁻¹ B K，K = R⁻¹R'。位移与旋转互不耦合，缩放（均匀时）不变，所以可以逐通道算。
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

    # 轴角：共轭只旋转轴、不动角度
    axis = Vector(values[1:])
    if axis.length < 1e-9:
        return list(values), None
    return [values[0]] + list(backward @ axis), None


def _is_neutral_pose(pose_bone, rotation_channel):
    """静置姿态共轭之后还是静置，可以整根跳过，免得写进一堆浮点噪声。"""
    if pose_bone.location.length > 1e-9:
        return False
    if rotation_channel == 'rotation_quaternion':
        quaternion = pose_bone.rotation_quaternion
        return 1.0 - abs(quaternion.w) < 1e-9
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


class SHIYUME_OT_ConnectBoneChains(bpy.types.Operator):
    """一键接骨架链：把每根骨骼的 tail 拉到主链子骨骼的 head 上并勾选"连接"，
    叶骨沿父链方向续出去，roll 用最小扭转保住原来的轴向。
    专治别的软件导进来朝向丢失（手骨全朝上）、父子关系断开的骨架。
    head 一律不动，蒙皮绑定不受影响；既有姿态与本骨架用到的动作会被补偿回原样。
    编辑模式下有选中骨骼就只处理选中的，没选中就处理整副骨架。"""
    bl_idname = "shiyume.connect_bone_chains"
    bl_label = "一键接骨架链"
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
    multi_child_strategy: bpy.props.EnumProperty(
        name="多子骨骼",
        items=[
            ('NAME_FARTHEST', "名字链→最远", "先找名字递增的子骨骼，找不到就取离自己最远的那根"),
            ('NAME', "仅名字链", "只认名字递增的子骨骼，认不出就不动这根骨骼"),
            ('AVERAGE', "取平均", "tail 指向所有子骨骼 head 的平均位置（better_fbx 的做法，不产生连接）"),
            ('SKIP', "跳过", "多个子骨骼时完全不动这根骨骼"),
        ],
        default='NAME_FARTHEST',
    )
    leaf_mode: bpy.props.EnumProperty(
        name="叶骨",
        items=[
            ('KEEP', "只改朝向", "保留叶骨原长度，只把方向掰回父链方向"),
            ('RATIO', "按父骨比例", "长度 = 父骨长度 × 比例"),
            ('SKIP', "不动", "叶骨保持原样"),
        ],
        default='KEEP',
    )
    leaf_length_ratio: bpy.props.FloatProperty(name="叶骨长度比例", default=1.0, min=0.001, max=10.0)
    preserve_roll: bpy.props.BoolProperty(
        name="保住轴向(roll)",
        description="改朝向后用最小扭转把 Z 轴拉回原方向，而不是重算成全局轴",
        default=True,
    )
    set_connect: bpy.props.BoolProperty(
        name="勾选连接",
        description="给主链子骨骼打上 use_connect；关掉就只修朝向不建立连接",
        default=True,
    )
    preserve_animation: bpy.props.BoolProperty(
        name="补偿姿态与动画",
        description="静置朝向变了会让既有姿态/动作曲线错位，勾上会把它们换算回原来的效果",
        default=True,
    )
    minimum_length: bpy.props.FloatProperty(
        name="最短骨骼长度",
        description="目标点离 head 比这还近就跳过，避免造出零长度骨骼",
        default=0.0001, min=0.0, precision=6,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        edit_bones = obj.data.edit_bones

        original = {bone.name: (bone.matrix.copy(), bone.z_axis.copy()) for bone in edit_bones}

        targets = self._collect_targets(edit_bones)
        if not targets:
            self.report({'WARNING'}, "没有可处理的骨骼")
            return {'CANCELLED'}

        planned = {}
        chain_children = {}
        for bone in targets:
            if bone.children:
                point, child = _plan_chain_tail(bone, self.multi_child_strategy)
                if child is not None:
                    chain_children[bone.name] = child.name
            else:
                point = _plan_leaf_tail(bone, self.leaf_mode, self.leaf_length_ratio)
            if point is not None:
                planned[bone.name] = point

        oriented = 0
        degenerate = 0
        for name, point in planned.items():
            bone = edit_bones[name]
            if (point - bone.head).length < self.minimum_length:
                degenerate += 1
                chain_children.pop(name, None)
                continue
            bone.tail = point
            if self.preserve_roll:
                bone.align_roll(original[name][1])
            oriented += 1

        connected = 0
        kept_loose = 0
        if self.set_connect:
            # 连上之后这根骨骼的 location 通道就彻底失效了，有位移在用的一律不连
            live_locations = self._live_location_bones(obj) if self.preserve_animation else set()
            for parent_name, child_name in chain_children.items():
                parent = edit_bones[parent_name]
                child = edit_bones[child_name]
                # head 落不到父 tail 上就不连，否则 Blender 会拖着 head 走、毁掉蒙皮绑定
                if (child.head - parent.tail).length > 1e-6 or child.use_connect:
                    continue
                if child_name in live_locations:
                    kept_loose += 1
                    continue
                child.use_connect = True
                connected += 1

        corrections = {}
        for bone in edit_bones:
            change = original[bone.name][0].inverted_safe() @ bone.matrix
            if not _is_identity(change):
                corrections[bone.name] = change

        compensated_bones = 0
        compensated_curves = 0
        if self.preserve_animation and corrections:
            compensated_bones, compensated_curves = self._compensate(obj, corrections)

        message = f"接链 {connected} 处，改朝向 {oriented} 根"
        if kept_loose:
            message += f"，{kept_loose} 处有位移动画未连接"
        if degenerate:
            message += f"，跳过零长度 {degenerate} 根"
        if compensated_bones or compensated_curves:
            message += f"，补偿姿态 {compensated_bones} 根 / 曲线 {compensated_curves} 条"
        self.report({'INFO'}, message)
        return {'FINISHED'}

    def _collect_targets(self, edit_bones):
        selected = [bone for bone in edit_bones if bone.select]
        if self.scope == 'ALL' or (self.scope == 'AUTO' and not selected):
            return list(edit_bones)
        return selected

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
