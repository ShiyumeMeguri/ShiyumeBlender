"""后台 Blender 执行体: 把骨架绑定写进主模型文件并保存, 或者把它读出来。

由 rig_sync 以
    blender -b <主模型文件> --python rig_sync_worker.py -- <{"mode":..,"payload":..} json>
启动。**不导入插件**, 只用 bpy —— 它跑在一个干净的后台进程里。

结果以一行 `@SHIYUMESYNC {json}` 回传, 调用方只解析这一行。
"""

import json
import os
import sys
import tempfile

import bpy

MARKER = "@SHIYUMESYNC "
SCENE_ONLY_PREFIX = "RuriRetarget"
HELPER_PREFIXES = ("RT.", "RL.", "Ref_")
CONSTRAINT_SKIP = {"rna_type", "is_valid", "error_location", "error_rotation",
                   "active", "is_override_data", "type"}


def emit(payload):
    print(MARKER + json.dumps(payload, ensure_ascii=False))


def fail(message):
    emit({'ok': False, 'error': message})
    sys.exit(0)


def constraint_props(con):
    out = {}
    for prop in con.bl_rna.properties:
        key = prop.identifier
        if key in CONSTRAINT_SKIP or prop.is_readonly:
            continue
        value = getattr(con, key)
        if isinstance(value, (bool, int, float, str)):
            out[key] = value
        elif hasattr(value, "name"):
            out["@" + key] = value.name
        elif hasattr(value, "__len__"):
            try:
                out[key] = [list(r) if hasattr(r, "__len__") else r for r in value]
            except (TypeError, ValueError):
                pass
    return out


def snapshot(rig):
    arm = rig.data
    bones = {}
    for bone in arm.bones:
        if bone.name.startswith(HELPER_PREFIXES):
            continue
        bones[bone.name] = {
            "parent": bone.parent.name if bone.parent else None,
            "matrix_local": [list(r) for r in bone.matrix_local],
            "length": bone.length,
            "use_deform": bone.use_deform,
            "use_connect": bone.use_connect,
            "collections": [c.name for c in bone.collections],
        }
    constraints = {}
    for pose_bone in rig.pose.bones:
        if pose_bone.name.startswith(HELPER_PREFIXES):
            continue
        rows = []
        for con in pose_bone.constraints:
            if con.name.startswith(SCENE_ONLY_PREFIX):
                continue
            row = constraint_props(con)
            row["type"] = con.type
            rows.append(row)
        if rows:
            constraints[pose_bone.name] = rows
    return {"rig": rig.name, "bones": bones, "constraints": constraints,
            "collections": [{"name": c.name, "is_visible": c.is_visible}
                            for c in arm.collections_all],
            "props": {k: v for k, v in rig.items() if isinstance(v, (int, float, str))
                      and not (isinstance(v, str) and len(v) > 4096)
                      and not k.startswith("shiyume_")}}


def apply_snapshot(rig, snap):
    from mathutils import Matrix
    arm = rig.data
    mirror_was = arm.use_mirror_x
    arm.use_mirror_x = False
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm.edit_bones
    added = []
    for name, spec in snap["bones"].items():
        bone = edit_bones.get(name)
        if bone is None:
            bone = edit_bones.new(name)
            added.append(name)
        bone.head = (0.0, 0.0, 0.0)
        bone.tail = (0.0, spec["length"], 0.0)
        bone.matrix = Matrix(spec["matrix_local"])
        bone.use_deform = spec["use_deform"]
        bone.use_connect = False
    for name, spec in snap["bones"].items():
        bone = edit_bones[name]
        parent = spec["parent"]
        bone.parent = edit_bones.get(parent) if parent else None
        bone.use_connect = spec["use_connect"] and bone.parent is not None
    removed = [b.name for b in list(edit_bones)
               if b.name not in snap["bones"] and not b.name.startswith(HELPER_PREFIXES)]
    for name in removed:
        edit_bones.remove(edit_bones[name])
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

    for pose_bone in rig.pose.bones:
        if pose_bone.name.startswith(HELPER_PREFIXES):
            continue
        for con in list(pose_bone.constraints):
            if not con.name.startswith(SCENE_ONLY_PREFIX):
                pose_bone.constraints.remove(con)
    n_con = 0
    for bone_name, rows in snap["constraints"].items():
        pose_bone = rig.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for row in rows:
            con = pose_bone.constraints.new(row["type"])
            for key, value in row.items():
                if key == "type":
                    continue
                if key.startswith("@"):
                    target = bpy.data.objects.get(value) or (rig if value == snap["rig"] else None)
                    if target is not None:
                        try:
                            setattr(con, key[1:], target)
                        except (AttributeError, TypeError):
                            pass
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
    return len(snap["bones"]), n_con, added, removed


def main():
    try:
        request = json.loads(sys.argv[sys.argv.index('--') + 1])
    except (ValueError, IndexError) as exc:
        fail("payload 解析失败: %s" % exc)
    with open(request['payload'], encoding='utf-8') as fh:
        payload = json.load(fh)

    name = payload['rig']
    rig = bpy.data.objects.get(name)
    if rig is None or rig.type != 'ARMATURE':
        fail("主模型里没有骨架 %r; 现有: %s"
             % (name, sorted(o.name for o in bpy.data.objects if o.type == 'ARMATURE')))

    if request['mode'] == 'dump':
        handle, out = tempfile.mkstemp(suffix=".json", prefix="shiyume_rigdump_")
        os.close(handle)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(snapshot(rig), fh)
        emit({'ok': True, 'snapshot': out,
              'summary': "读出 %d 根骨骼" % len(rig.data.bones)})
        return

    users = [o for o in bpy.data.objects
             if o.type == 'MESH' and any(m.type == 'ARMATURE' and m.object is rig
                                         for m in o.modifiers)]
    notes = []
    if not users:
        notes.append("主模型里没有网格绑在 %s 上, 还是写了 —— 确认一下推的是不是这个骨架" % name)

    before = len(rig.data.bones)
    n_bones, n_con, added, removed = apply_snapshot(rig, payload)
    if removed:
        notes.append("主模型里多出来的 %d 根骨骼被删了: %s" % (len(removed), removed[:8]))
    bpy.ops.wm.save_mainfile()
    emit({'ok': True, 'notes': notes,
          'summary': "推送到 %s: %d -> %d 根骨骼, %d 条约束, 新增 %d 根"
                     % (os.path.basename(bpy.data.filepath), before, n_bones, n_con, len(added))})


main()
