"""骨架绑定的读写: 把一副骨架读成纯数据, 或者把纯数据写进一副骨架。

搬的是: 骨骼静止姿态 (父子/朝向/长度/形变标记)、骨骼集合归属与显示、姿势骨约束、
物体上的设置类自定义属性 (比如 ik_on)。

**不搬**只对某个场景有意义的东西:
  · 名字以 RuriRetarget 开头的约束 —— 重定向绑到参考动画上的, 只活在场景里
  · RT. / RL. 开头的骨 —— 长在参考骨架上, 本来就不在角色身上
  · Ref_ 开头的骨 —— 从参考骨架移植过来给摄像机当锚点的, 只对那个场景有意义
"""

import bpy
from mathutils import Matrix

SCENE_ONLY_CONSTRAINT_PREFIX = "RuriRetarget"
SCENE_ONLY_BONE_PREFIXES = ("RT.", "RL.", "Ref_")

# 只读的, 或者由别的字段决定的; 写回去只会报错
CONSTRAINT_SKIP = {"rna_type", "is_valid", "error_location", "error_rotation",
                   "active", "is_override_data", "type"}

# 导入器会往物体上塞几十万字符的元数据, 那不是绑定的一部分
PROP_MAX_CHARS = 4096


def is_scene_only(con, rig, known_bones):
    """这条约束是不是只属于当前场景 —— 主模型根本不知道它存在。

    判据是"它指向的东西主模型里有没有", 不是名字:
      · 指向别的骨架物体 -> 跨角色锁 (男女互锁), 主模型里那个物体不存在
      · 指向本骨架、但 subtarget 是主模型没有的骨 -> 例如 Retarget offset 指向 MCH_*
      · 名字以 RuriRetarget 开头 -> 重定向绑到参考动画上的
    这三类既不该被推上去 (推上去就是一条断了目标的死约束), 也不该在拉取时被删掉。
    """
    if con.name.startswith(SCENE_ONLY_CONSTRAINT_PREFIX):
        return True
    target = getattr(con, "target", None)
    if target is not None and target is not rig and target.type == 'ARMATURE':
        return True
    sub = getattr(con, "subtarget", "")
    if target is rig and sub and sub not in known_bones:
        return True
    return False


def _constraint_props(con):
    out = {}
    for prop in con.bl_rna.properties:
        key = prop.identifier
        if key in CONSTRAINT_SKIP or prop.is_readonly:
            continue
        value = getattr(con, key)
        if isinstance(value, (bool, int, float, str)):
            out[key] = value
        elif hasattr(value, "name"):                    # 指向 ID 的指针
            out["@" + key] = value.name
        elif hasattr(value, "__len__"):
            try:
                out[key] = [list(row) if hasattr(row, "__len__") else row for row in value]
            except (TypeError, ValueError):
                pass
    return out


def snapshot(rig, skip_keys=()):
    """把一副骨架读成纯数据, 好隔着进程搬。"""
    arm = rig.data
    bones = {}
    for bone in arm.bones:
        if bone.name.startswith(SCENE_ONLY_BONE_PREFIXES):
            continue
        bones[bone.name] = {
            "parent": bone.parent.name if bone.parent else None,
            "matrix_local": [list(row) for row in bone.matrix_local],
            "length": bone.length,
            "use_deform": bone.use_deform,
            "use_connect": bone.use_connect,
            "collections": [c.name for c in bone.collections],
        }
    constraints = {}
    for pose_bone in rig.pose.bones:
        if pose_bone.name.startswith(SCENE_ONLY_BONE_PREFIXES):
            continue
        rows = []
        for con in pose_bone.constraints:
            if is_scene_only(con, rig, bones):
                continue
            row = _constraint_props(con)
            row["type"] = con.type
            rows.append(row)
        if rows:
            constraints[pose_bone.name] = rows
    return {
        "rig": rig.name,
        "bones": bones,
        "collections": [{"name": c.name, "is_visible": c.is_visible}
                        for c in arm.collections_all],
        "constraints": constraints,
        "props": {k: v for k, v in rig.items()
                  if isinstance(v, (int, float, str))
                  and not (isinstance(v, str) and len(v) > PROP_MAX_CHARS)
                  and k not in skip_keys},
    }


def apply(rig, snap, remove_extra=True):
    """把 snapshot() 的结果写进一副骨架。返回一行人话总结。

    remove_extra 决定"本地有、来源没有"的骨怎么办:
      · 推送进主模型 -> True。推送方是权威, 主模型要变成推送方的样子。
      · 拉取进场景   -> False。场景里会有只属于场景的骨 (实测: MCH_Root/Center/Pelvis
        是为了让根链可拖动才建的机械骨, 主模型里没有), 删掉就毁了场景的绑定。
        不删, 但要在总结里报出来 —— 静默删骨是最坏的一种错。
    """
    arm = rig.data
    mirror_was = arm.use_mirror_x
    arm.use_mirror_x = False                # 否则半成品的写入会被镜像到对侧
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm.edit_bones

    # 一) 先建齐, 再把**全部**骨断开连接。
    #     连接骨的 head 是由父骨的 tail 决定的: 不先断开就写 head/matrix, 写进去的值
    #     会被 Blender 静默改掉, 一整条链跟着旧父级一路拖走 —— 实测 111 根骨掉到原点,
    #     157 根和来源对不上, 看上去就是一把放射状的乱骨。
    added = []
    for name in snap["bones"]:
        if edit_bones.get(name) is None:
            edit_bones.new(name)
            added.append(name)
    for bone in edit_bones:
        bone.use_connect = False

    # 二) 摆位。此刻没有任何连接关系能干扰 head/tail。
    for name, spec in snap["bones"].items():
        bone = edit_bones[name]
        bone.head = (0.0, 0.0, 0.0)
        bone.tail = (0.0, spec["length"], 0.0)
        bone.matrix = Matrix(spec["matrix_local"])
        bone.use_deform = spec["use_deform"]

    # 三) 接父级 (此时 use_connect 还是 False, 接父级不会挪动 head)
    for name, spec in snap["bones"].items():
        bone = edit_bones[name]
        parent = spec["parent"]
        bone.parent = edit_bones.get(parent) if parent else None
    extra = [b.name for b in list(edit_bones)
             if b.name not in snap["bones"]
             and not b.name.startswith(SCENE_ONLY_BONE_PREFIXES)]
    removed = extra if remove_extra else []
    for name in removed:
        edit_bones.remove(edit_bones[name])

    # 四) 最后才恢复 use_connect, 并当场检查有没有骨因此被拖走。
    #     置 True 会把 head 吸到父骨的 tail 上; 来源数据自洽的话一动不动, 不自洽就要报出来。
    snapped = []
    for name, spec in snap["bones"].items():
        if not spec["use_connect"]:
            continue
        bone = edit_bones[name]
        if bone.parent is None:
            continue
        before_head = bone.head.copy()
        bone.use_connect = True
        if (bone.head - before_head).length > 1e-6:
            snapped.append(name)
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.use_mirror_x = mirror_was

    for entry in snap["collections"]:
        coll = arm.collections_all.get(entry["name"])
        if coll is None:
            coll = arm.collections.new(entry["name"])
        coll.is_visible = entry["is_visible"]
    for name, spec in snap["bones"].items():
        bone = arm.bones[name]
        for coll in list(bone.collections):
            coll.unassign(bone)
        for cname in spec["collections"]:
            coll = arm.collections_all.get(cname)
            if coll is not None:
                coll.assign(bone)

    n_con = 0
    kept_scene_only = 0
    for pose_bone in rig.pose.bones:
        if pose_bone.name.startswith(SCENE_ONLY_BONE_PREFIXES):
            continue
        for con in list(pose_bone.constraints):
            if is_scene_only(con, rig, snap["bones"]):
                kept_scene_only += 1       # 主模型不知道它, 也就无权删它
                continue
            pose_bone.constraints.remove(con)
    for bone_name, rows in snap["constraints"].items():
        pose_bone = rig.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for row in rows:
            con = pose_bone.constraints.new(row["type"])
            for key, value in row.items():      # 先接 ID 指针, subtarget 靠它才有效
                if not key.startswith("@"):
                    continue
                target = bpy.data.objects.get(value)
                if target is None and value == snap["rig"]:
                    target = rig
                if target is not None:
                    try:
                        setattr(con, key[1:], target)
                    except (AttributeError, TypeError):
                        pass
            for key, value in row.items():
                if key == "type" or key.startswith("@"):
                    continue
                try:
                    if key in ("inverse_matrix", "matrix_inverse"):
                        setattr(con, key, Matrix(value))
                    else:
                        setattr(con, key, value)
                except (AttributeError, TypeError, ValueError):
                    pass
            n_con += 1
    for key, value in snap["props"].items():
        rig[key] = value

    tail = ("删除 %d 根" % len(removed) if remove_extra
            else "本地独有的 %d 根原样保留%s"
                 % (len(extra), (" (%s)" % ", ".join(extra[:6])) if extra else ""))
    warn = (("; 恢复连接时被父骨吸走的 %d 根: %s" % (len(snapped), ", ".join(snapped[:5])))
            if snapped else "")
    scene_only = ("; 场景专有的 %d 条约束原样保留" % kept_scene_only) if kept_scene_only else ""
    return ("%d 根骨骼, %d 条约束; 新增 %d 根, %s%s%s"
            % (len(snap["bones"]), n_con, len(added), tail, scene_only, warn))
