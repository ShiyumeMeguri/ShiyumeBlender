"""姿势层的同步: 约束、约束上的驱动器、开关类自定义属性。

骨架**数据块**挂到源上, 所以骨骼结构跟着源走, 开文件就是最新的。但姿势不在数据块上, 它在
**物体**上 —— 而物体永远是本地的, 链接一个字都带不过来。于是源里的控制网络和本地的姿势会
各走各的, 而且没有任何报错。

实测这条缝有多深: 源里新加的骨链接进来了, 本地那三条指着旧机械骨的 `Retarget offset` 却
还在, subtarget 落空之后 `COPY_TRANSFORMS` **不是失效而是退化成"拷贝目标物体的变换"**,
每一级再叠一遍物体世界矩阵 (Root 2 倍 / Center 3 倍 / Pelvis 4 倍), 整副骨架被甩到 550 m
外。全程零报错。所以这里补上源 -> 本地的姿势同步, 并且带四道闸门。

**不搬**只对这个场景成立的东西:
  · 指向别的骨架物体的约束 —— 跨角色互锁, 源文件里那个物体根本不存在
  · 指向本骨架、但 subtarget 是源没有的骨 —— 场景自己长出来的机械骨
  · 名字以 RuriRetarget 开头的 —— 重定向绑到参考动画上的

自定义属性只**补缺**不覆盖: 共享的是"有没有这个开关", 不是它现在拨到哪一档。`ik_on` 就是
典型 —— 场景里是 0 (曲线管四肢), 源里是 1; 照抄源的值会让 IK 当场接管四肢。
"""

import bpy
from mathutils import Matrix

from . import character

SCENE_ONLY_PREFIX = "RuriRetarget"
SCENE_ONLY_BONE_PREFIXES = ("RT.", "RL.", "Ref_")

# 只读的, 或者由别的字段决定的; 写回去只会报错
SKIP_PROPS = {"rna_type", "is_valid", "error_location", "error_rotation",
              "active", "is_override_data", "type"}

# 导入器会往物体上塞几十万字符的元数据, 那不是绑定的一部分
PROP_MAX_CHARS = 4096


# ----------------------------------------------------------------- 读

def is_scene_only(constraint, rig, source_bones):
    """这条约束是不是只属于当前场景 —— 源根本不知道它存在, 也就无权删它。"""
    if constraint.name.startswith(SCENE_ONLY_PREFIX):
        return True
    target = getattr(constraint, "target", None)
    if target is not None and target is not rig and target.type == 'ARMATURE':
        return True
    subtarget = getattr(constraint, "subtarget", "")
    if target is rig and subtarget and subtarget not in source_bones:
        return True
    return False


def _constraint_row(constraint):
    row = {}
    for prop in constraint.bl_rna.properties:
        key = prop.identifier
        if key in SKIP_PROPS or prop.is_readonly:
            continue
        value = getattr(constraint, key)
        if isinstance(value, (bool, int, float, str)):
            row[key] = value
        elif hasattr(value, "name"):                    # 指向 ID 的指针
            row["@" + key] = value.name
        elif hasattr(value, "__len__"):
            try:
                row[key] = [list(item) if hasattr(item, "__len__") else item for item in value]
            except (TypeError, ValueError):
                pass
    row["type"] = constraint.type
    return row


def _bone_of_path(data_path):
    """pose.bones["X"].constraints["Y"].influence -> X"""
    try:
        return data_path.split('"')[1]
    except IndexError:
        return None


def _driver_rows(rig):
    """约束上的驱动器。

    驱动器**不是约束的属性**: 重建约束它就没了, 而且没有任何报错 —— 实测同步一次就把 4 条
    ik_on 驱动器清零, IK 影响力从被驱动的 0 变成固定 1.0, IK 当场接管四肢。
    """
    animation = rig.animation_data
    rows = []
    for curve in (animation.drivers if animation else []):
        if ".constraints[" not in curve.data_path:
            continue
        driver = curve.driver
        rows.append({
            "path": curve.data_path, "index": curve.array_index,
            "kind": driver.type, "expression": driver.expression,
            "use_self": driver.use_self,
            "vars": [{"name": variable.name, "kind": variable.type,
                      "targets": [{"id_type": getattr(target, "id_type", 'OBJECT'),
                                   "id": target.id.name if target.id else None,
                                   "data_path": target.data_path,
                                   "bone_target": getattr(target, "bone_target", ""),
                                   "transform_type": getattr(target, "transform_type", 'LOC_X'),
                                   "transform_space": getattr(target, "transform_space",
                                                              'WORLD_SPACE'),
                                   "rotation_mode": getattr(target, "rotation_mode", 'AUTO')}
                                  for target in variable.targets]}
                     for variable in driver.variables],
        })
    return rows


def snapshot(rig):
    """把一副骨架的姿势层读成纯数据。"""
    return {
        "rig": rig.name,
        "bones": [bone.name for bone in rig.data.bones],
        "constraints": {pose_bone.name: [_constraint_row(c) for c in pose_bone.constraints]
                        for pose_bone in rig.pose.bones if pose_bone.constraints},
        "drivers": _driver_rows(rig),
        "props": {key: value for key, value in rig.items()
                  if isinstance(value, (int, float, str))
                  and not (isinstance(value, str) and len(value) > PROP_MAX_CHARS)},
    }


# ----------------------------------------------------------------- 写

def _local_object(name, rig, source_rig_name):
    """源里的物体名 -> 本文件里那个物体。

    先判自引用: 同步时源骨架是临时链进来的, `bpy.data.objects.get()` 按名字一查可能查到
    那个临时物体, 等它被清掉, 约束的 target 就全变成 None。然后只认**本地**物体 ——
    链接进来的那一份马上就要消失, 指过去等于指空。
    """
    if not name:
        return None
    if name == source_rig_name:
        return rig
    candidate = bpy.data.objects.get(name)
    if candidate is not None and candidate.library is None:
        return candidate
    for other in bpy.data.objects:
        if other.name == name and other.library is None:
            return other
    return None


def _apply_drivers(rig, rows, source_rig_name):
    """重建约束驱动器。先清掉约束范围内的旧驱动器, 再按快照建。"""
    animation = rig.animation_data or rig.animation_data_create()
    for curve in list(animation.drivers):
        if ".constraints[" in curve.data_path:
            animation.drivers.remove(curve)
    made = 0
    for row in rows:
        holder_path, _dot, prop = row["path"].rpartition(".")
        try:
            holder = rig.path_resolve(holder_path)
            # 标量属性传下标会报错, 数组属性不传又只建一条 —— 直接问 RNA
            length = holder.bl_rna.properties[prop].array_length
            curve = rig.driver_add(row["path"], row["index"] if length else -1)
        except (ValueError, TypeError, KeyError):
            continue                       # 约束没了就跳过, 不是致命错
        driver = curve.driver
        driver.type = row["kind"]
        driver.expression = row["expression"]
        driver.use_self = row["use_self"]
        for spec in row["vars"]:
            variable = driver.variables.new()
            variable.name = spec["name"]
            variable.type = spec["kind"]
            for index, target_spec in enumerate(spec["targets"]):
                if index >= len(variable.targets):
                    break
                target = variable.targets[index]
                if hasattr(target, "id_type"):
                    target.id_type = target_spec["id_type"]
                target.id = _local_object(target_spec["id"], rig, source_rig_name)
                target.data_path = target_spec["data_path"]
                if hasattr(target, "bone_target"):
                    target.bone_target = target_spec["bone_target"]
                for key in ("transform_type", "transform_space", "rotation_mode"):
                    if hasattr(target, key):
                        setattr(target, key, target_spec[key])
        made += 1
    return made


def _revive(rig):
    """把"这条约束是坏的"这个缓存标记冲掉。

    `is_valid` 会**存进 .blend**: 骨缺席那会儿被标成失效, 骨补回来之后它不会自己翻身, 约束
    继续被跳过, 而画面上看不出任何异常。重新赋一次 subtarget 逼 Blender 重解一遍。
    """
    revived = 0
    for pose_bone in rig.pose.bones:
        for constraint in pose_bone.constraints:
            subtarget = getattr(constraint, "subtarget", None)
            if subtarget:
                was_valid = constraint.is_valid
                constraint.subtarget = subtarget
                revived += (not was_valid)
    rig.update_tag()
    return revived


def audit(rig):
    """四道闸门里的三道: 死约束 / 空靶 / 动作引用了骨架没有的骨。"""
    bones = set(rig.data.bones.keys())
    dead, orphan = [], []
    for pose_bone in rig.pose.bones:
        for constraint in pose_bone.constraints:
            target = getattr(constraint, "target", None)
            subtarget = getattr(constraint, "subtarget", "")
            if hasattr(constraint, "target") and target is None:
                orphan.append("%s/%s" % (pose_bone.name, constraint.name))
            elif subtarget and target is not None and target.type == 'ARMATURE' \
                    and subtarget not in target.data.bones:
                dead.append("%s/%s -> %s/%s" % (pose_bone.name, constraint.name,
                                                target.name, subtarget))
    missing_channels = set()
    animation = rig.animation_data
    action = animation.action if animation else None
    for curve in (action.fcurves if action else []):
        if not curve.data_path.startswith("pose.bones["):
            continue
        bone = _bone_of_path(curve.data_path)
        if bone is not None and bone not in bones:
            missing_channels.add(bone)
    return dead, orphan, sorted(missing_channels)


def apply(rig, snap):
    """把 snapshot() 的结果写进一副骨架的姿势层。返回 (一行总结, 提示列表)。"""
    source_bones = set(snap["bones"])
    kept = 0
    for pose_bone in rig.pose.bones:
        if pose_bone.name.startswith(SCENE_ONLY_BONE_PREFIXES):
            continue
        for constraint in list(pose_bone.constraints):
            if is_scene_only(constraint, rig, source_bones):
                kept += 1
                continue
            pose_bone.constraints.remove(constraint)

    made = 0
    for bone_name, rows in snap["constraints"].items():
        pose_bone = rig.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for row in rows:
            constraint = pose_bone.constraints.new(row["type"])
            for key, value in row.items():          # 先接 ID 指针, subtarget 靠它才有效
                if key.startswith("@"):
                    target = _local_object(value, rig, snap["rig"])
                    if target is not None:
                        try:
                            setattr(constraint, key[1:], target)
                        except (AttributeError, TypeError):
                            pass
            for key, value in row.items():
                if key == "type" or key.startswith("@"):
                    continue
                try:
                    if key in ("inverse_matrix", "matrix_inverse"):
                        setattr(constraint, key, Matrix(value))
                    else:
                        setattr(constraint, key, value)
                except (AttributeError, TypeError, ValueError):
                    pass
            made += 1

    drivers = _apply_drivers(rig, snap.get("drivers", []), snap["rig"])
    added = []
    for key, value in snap["props"].items():
        if key in (character.BOUND_SOURCE_KEY, character.BOUND_NAME_KEY) or key in rig.keys():
            continue
        rig[key] = value
        added.append(key)
    revived = _revive(rig)
    bpy.context.view_layer.update()

    dead, orphan, missing = audit(rig)
    notes = []
    if kept:
        notes.append("场景专有的 %d 条约束原样保留" % kept)
    if added:
        notes.append("新增开关 %s" % ", ".join(added))
    if revived:
        notes.append("冲掉 %d 条约束身上的过期失效标记" % revived)
    if dead:
        notes.append("★%d 条约束指向不存在的骨: %s" % (len(dead), ", ".join(dead[:4])))
    if orphan:
        notes.append("★%d 条约束的目标物体是空的: %s" % (len(orphan), ", ".join(orphan[:4])))
    if missing:
        notes.append("★动作里有 %d 根骨在骨架里不存在, 这些通道是死的: %s"
                     % (len(missing), ", ".join(missing[:6])))
    summary = "%s: 约束 %d 条, 驱动器 %d 条" % (rig.name, made, drivers)
    return summary, notes, bool(dead or orphan)


# ----------------------------------------------------------------- 从源同步

def sync(rig):
    """把源文件里那副骨架的姿势层搬到本地这一副上。返回 (总结, 提示, 是否有硬错)。"""
    binding = character.binding_of(rig)
    if binding is None:
        raise ValueError("%s 没有绑定到任何源" % rig.name)
    path, source_name = binding

    before = {obj.name_full for obj in bpy.data.objects}
    with bpy.data.libraries.load(path, link=True) as (source, target):
        if source_name not in source.objects:
            raise KeyError("%s 里没有物体 %r" % (bpy.path.basename(path), source_name))
        target.objects = [source_name]
    dragged = [obj for obj in bpy.data.objects if obj.name_full not in before]
    try:
        borrowed = next(obj for obj in dragged if obj.type == 'ARMATURE'
                        and obj.name == source_name)
        snap = snapshot(borrowed)
        snap["rig"] = source_name
        return apply(rig, snap)
    finally:
        for obj in dragged:
            if obj.name_full in {o.name_full for o in bpy.data.objects}:
                bpy.data.objects.remove(obj)
        for library in list(bpy.data.libraries):
            if not library.users_id:
                bpy.data.libraries.remove(library)
