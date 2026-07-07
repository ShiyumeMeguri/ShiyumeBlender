"""动画工具:一键清理(四类问题按需勾选)与关键帧批量偏移。"""

import re
from math import radians

import bpy
import numpy as np

from ..core.compat import get_active_action, iter_action_fcurves, list_action_fcurves

_BONE_PATH = re.compile(r'^pose\.bones\["([^"]+)"\]')


class SHIYUME_OT_CleanAnimation(bpy.types.Operator):
    """一键清理动画数据(按需勾选):
    烘焙残留的自定义属性关键帧、选中骨骼的位移/缩放、
    指向已改名/已删除骨骼的无效路径、指定骨骼集合的位移/缩放"""
    bl_idname = "shiyume.clean_animation"
    bl_label = "清理动画数据"
    bl_options = {'REGISTER', 'UNDO'}

    fix_bake: bpy.props.BoolProperty(
        name="烘焙残留",
        default=True,
        description="删除所有 Action 中烘焙产生的自定义属性关键帧(路径含 \"][\" 的嵌套属性)",
    )
    fix_paths: bpy.props.BoolProperty(
        name="无效骨骼路径",
        default=True,
        description="删除所有 Action 中指向当前骨架里不存在骨骼的曲线",
    )
    fix_transforms: bpy.props.BoolProperty(
        name="选中骨骼位移/缩放",
        default=True,
        description="仅姿态模式生效:删除激活 Action 中选中骨骼的位移与缩放曲线(保留旋转)",
    )
    fix_collections: bpy.props.BoolProperty(
        name="指定集合位移/缩放",
        default=False,
        description="删除所有 Action 中指定骨骼集合成员的位移与缩放曲线",
    )
    collection_names: bpy.props.StringProperty(
        name="集合名单",
        default="Body,Skirt,BackHair,FrontHair",
        description="逗号分隔的骨骼集合名",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        column = layout.column(heading="清理项")
        column.prop(self, "fix_bake")
        column.prop(self, "fix_paths")
        column.prop(self, "fix_transforms")
        column.prop(self, "fix_collections")
        row = layout.row()
        row.active = self.fix_collections
        row.prop(self, "collection_names")

    def execute(self, context):
        armature = context.active_object
        active_action = get_active_action(armature)

        pose_bone_names = set(armature.pose.bones.keys())

        selected_bone_names = set()
        if self.fix_transforms and context.mode == 'POSE' and context.selected_pose_bones:
            selected_bone_names = {bone.name for bone in context.selected_pose_bones}

        collection_bone_names = set()
        if self.fix_collections:
            for name in (part.strip() for part in self.collection_names.split(',')):
                collection = armature.data.collections.get(name) if name else None
                if collection:
                    collection_bone_names.update(bone.name for bone in collection.bones)

        removed = {"bake": 0, "paths": 0, "transforms": 0, "collections": 0}

        # 一趟扫完所有 Action,每条曲线按启用的规则裁决一次
        for action in bpy.data.actions:
            for owner, fcurve in list_action_fcurves(action):
                data_path = fcurve.data_path

                if self.fix_bake and '"]["' in data_path:
                    owner.remove(fcurve)
                    removed["bake"] += 1
                    continue

                match = _BONE_PATH.match(data_path)
                if match is None:
                    continue
                bone_name = match.group(1)
                is_location_or_scale = "location" in data_path or "scale" in data_path

                if self.fix_paths and bone_name not in pose_bone_names:
                    owner.remove(fcurve)
                    removed["paths"] += 1
                    continue

                if (self.fix_transforms and action is active_action
                        and bone_name in selected_bone_names and is_location_or_scale):
                    owner.remove(fcurve)
                    removed["transforms"] += 1
                    continue

                if (self.fix_collections and bone_name in collection_bone_names
                        and is_location_or_scale):
                    owner.remove(fcurve)
                    removed["collections"] += 1

        total = sum(removed.values())
        detail = " / ".join(
            text for text, count in (
                (f"烘焙残留 {removed['bake']}", removed["bake"]),
                (f"无效路径 {removed['paths']}", removed["paths"]),
                (f"位移缩放 {removed['transforms']}", removed["transforms"]),
                (f"集合变换 {removed['collections']}", removed["collections"]),
            ) if count
        )
        self.report({'INFO'}, f"已删除 {total} 条曲线" + (f"({detail})" if detail else ""))
        return {'FINISHED'}


class SHIYUME_OT_OffsetKeyframes(bpy.types.Operator):
    """批量偏移选中骨骼的关键帧(位置/旋转,支持帧区间与时间插值曲线)。
    常用于修正动作捕捉数据的局部偏差;手柄随关键帧同步平移,不破坏曲线形状"""
    bl_idname = "shiyume.offset_keyframes"
    bl_label = "偏移骨骼关键帧"
    bl_options = {'REGISTER', 'UNDO'}

    loc_offset: bpy.props.FloatVectorProperty(name="位置偏移", size=3, subtype='TRANSLATION')
    rot_offset: bpy.props.FloatVectorProperty(name="旋转偏移", size=3, subtype='EULER')
    frame_start: bpy.props.IntProperty(name="开始帧", default=0)
    frame_end: bpy.props.IntProperty(name="结束帧", default=0, description="开始/结束都为 0 时作用于全部帧")
    offset_mode: bpy.props.EnumProperty(
        name="插值模式",
        items=[
            ('constant', "恒定", "整个时间段保持相同的偏移量"),
            ('linear_increase', "线性增加", "偏移量随时间线性增加"),
            ('linear_decrease', "线性减少", "偏移量随时间线性减少"),
            ('smoothstep_increase', "平滑增加", "偏移量随时间平滑增加(S 形曲线)"),
            ('smoothstep_decrease', "平滑减少", "偏移量随时间平滑减少(S 形曲线)"),
        ],
        default='constant',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE' and context.mode == 'POSE'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "loc_offset")
        layout.prop(self, "rot_offset")
        column = layout.column(align=True)
        column.prop(self, "frame_start")
        column.prop(self, "frame_end")
        layout.prop(self, "offset_mode")

    def _channel_delta(self, fcurve, pose_bone, rot_offset_rad):
        """该曲线对应的偏移标量;不适用返回 None。"""
        data_path = fcurve.data_path
        index = fcurve.array_index
        if 'location' in data_path:
            return self.loc_offset[index]
        if 'rotation_euler' in data_path and pose_bone.rotation_mode == 'XYZ' and index < 3:
            return rot_offset_rad[index]
        if 'rotation_quaternion' in data_path and pose_bone.rotation_mode == 'QUATERNION' and 0 < index < 4:
            return rot_offset_rad[index - 1]
        return None

    def execute(self, context):
        action = get_active_action(context.active_object)
        if not action:
            self.report({'WARNING'}, "没有激活的 Action")
            return {'CANCELLED'}

        rot_offset_rad = tuple(radians(angle) for angle in self.rot_offset)
        full_range = self.frame_start == 0 and self.frame_end == 0
        span = self.frame_end - self.frame_start

        for pose_bone in context.selected_pose_bones:
            prefix = f'pose.bones["{pose_bone.name}"]'
            for _owner, fcurve in iter_action_fcurves(action):
                if not fcurve.data_path.startswith(prefix):
                    continue
                delta = self._channel_delta(fcurve, pose_bone, rot_offset_rad)
                if delta is None:
                    continue

                keyframes = fcurve.keyframe_points
                count = len(keyframes)
                if count == 0:
                    continue

                coordinates = np.empty(count * 2, dtype=np.float32)
                keyframes.foreach_get("co", coordinates)
                coordinates = coordinates.reshape(count, 2)
                frames = coordinates[:, 0]

                if full_range:
                    in_range = np.ones(count, dtype=np.bool_)
                    t = np.zeros(count, dtype=np.float32)
                else:
                    in_range = (frames >= self.frame_start) & (frames <= self.frame_end)
                    t = (frames - self.frame_start) / span if span != 0 else np.zeros(count, dtype=np.float32)

                if self.offset_mode == 'linear_increase':
                    factor = t
                elif self.offset_mode == 'linear_decrease':
                    factor = 1.0 - t
                elif self.offset_mode == 'smoothstep_increase':
                    factor = 3.0 * t * t - 2.0 * t * t * t
                elif self.offset_mode == 'smoothstep_decrease':
                    factor = 1.0 - (3.0 * t * t - 2.0 * t * t * t)
                else:
                    factor = np.ones(count, dtype=np.float32)

                value_delta = (delta * factor * in_range).astype(np.float32)
                coordinates[:, 1] += value_delta
                keyframes.foreach_set("co", coordinates.ravel())

                # 手柄随值同步平移,保持贝塞尔形状不被拉扯
                for handle_name in ("handle_left", "handle_right"):
                    handles = np.empty(count * 2, dtype=np.float32)
                    keyframes.foreach_get(handle_name, handles)
                    handles = handles.reshape(count, 2)
                    handles[:, 1] += value_delta
                    keyframes.foreach_set(handle_name, handles.ravel())

                fcurve.update()

        return {'FINISHED'}


classes = (
    SHIYUME_OT_CleanAnimation,
    SHIYUME_OT_OffsetKeyframes,
)
