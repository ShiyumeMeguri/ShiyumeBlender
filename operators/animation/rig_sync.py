"""骨架的推送/拉取 —— 和 mesh/common_sync 同一套路子, 只是搬的是绑定而不是网格.

场景里的角色是 append 进来的**本地副本**(不是链接), 想怎么改就怎么改; 改完按
"推送骨架到共用文件", 后台起一个 Blender 把改动写回主模型并保存, 当前会话不中断.

搬的是: 骨骼静止姿态(父子/朝向/长度/形变标记)、骨骼集合归属与显示、姿势骨约束、
物体自定义属性(比如 ik_on)。

**不搬**场景专有的东西: 名字以 RuriRetarget 开头的约束是重定向绑到参考动画上的,
只活在场景里; RT./RL. 开头的辅助骨长在参考骨架上, 本来就不在角色身上;
Ref_ 开头的是从参考骨架移植过来给摄像机当锚点的, 只对这个场景有意义。
"""

import json
import os
import subprocess
import tempfile

import bpy

SOURCE_FILE_KEY = "shiyume_common_file"
SOURCE_RIG_KEY = "shiyume_common_rig"
MARKER = "@SHIYUMESYNC "
SCENE_ONLY_PREFIX = "RuriRetarget"
HELPER_PREFIXES = ("RT.", "RL.", "Ref_")

WORKER = os.path.join(os.path.dirname(__file__), "rig_sync_worker.py")

# 这些是只读的或者由别的字段决定, 写回去只会报错
CONSTRAINT_SKIP = {"rna_type", "is_valid", "error_location", "error_rotation",
                   "active", "is_override_data", "type"}


def binding_of(obj):
    """物体上记的来源指针 -> (绝对路径, 主文件里的骨架名) 或 None。"""
    if obj is None or obj.type != 'ARMATURE':
        return None
    path = obj.get(SOURCE_FILE_KEY)
    if not path:
        return None
    name = obj.get(SOURCE_RIG_KEY) or obj.name
    return os.path.abspath(bpy.path.abspath(path)), name


def _constraint_props(con):
    out = {}
    for prop in con.bl_rna.properties:
        key = prop.identifier
        if key in CONSTRAINT_SKIP or prop.is_readonly:
            continue
        value = getattr(con, key)
        if isinstance(value, (bool, int, float, str)):
            out[key] = value
        elif hasattr(value, "name"):                 # 指向 ID 的指针
            out["@" + key] = value.name
        elif hasattr(value, "__len__"):
            try:
                out[key] = [list(row) if hasattr(row, "__len__") else row for row in value]
            except (TypeError, ValueError):
                pass
    return out


def snapshot(rig):
    """把一个骨架的绑定读成纯数据, 好隔着进程搬。"""
    arm = rig.data
    bones = {}
    for bone in arm.bones:
        if bone.name.startswith(HELPER_PREFIXES):
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
        if pose_bone.name.startswith(HELPER_PREFIXES):
            continue
        rows = []
        for con in pose_bone.constraints:
            if con.name.startswith(SCENE_ONLY_PREFIX):
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
        # 只搬设置类的小属性; 导入器塞的那种几十万字符的元数据不是绑定的一部分
        "props": {k: v for k, v in rig.items()
                  if isinstance(v, (int, float, str))
                  and not (isinstance(v, str) and len(v) > 4096)
                  and k not in (SOURCE_FILE_KEY, SOURCE_RIG_KEY)},
    }


def apply_snapshot(rig, snap, self_name=None):
    """把 snapshot() 的结果写进一个骨架。返回一行人话总结。"""
    arm = rig.data
    mirror_was = arm.use_mirror_x
    arm.use_mirror_x = False                    # 否则半成品的写入会被镜像到对侧
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm.edit_bones
    from mathutils import Matrix

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

    n_con = 0
    for pose_bone in rig.pose.bones:
        if pose_bone.name.startswith(HELPER_PREFIXES):
            continue
        for con in list(pose_bone.constraints):
            if not con.name.startswith(SCENE_ONLY_PREFIX):
                pose_bone.constraints.remove(con)
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
                    ident = key[1:]
                    target = bpy.data.objects.get(value)
                    if target is None and value == snap["rig"]:
                        target = rig
                    if target is not None:
                        try:
                            setattr(con, ident, target)
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

    return ("%d 根骨骼, %d 条约束; 新增 %d 根, 删除 %d 根"
            % (len(snap["bones"]), n_con, len(added), len(removed)))


def _run_worker(blend, payload_path, mode):
    command = [bpy.app.binary_path, '-b', blend, '--python', WORKER, '--',
               json.dumps({'mode': mode, 'payload': payload_path}, ensure_ascii=False)]
    completed = subprocess.run(command, capture_output=True, text=True,
                               encoding='utf-8', errors='replace')
    result = None
    for line in (completed.stdout or '').splitlines():
        if line.startswith(MARKER):
            try:
                result = json.loads(line[len(MARKER):])
            except ValueError:
                pass
    if result is None:
        tail = (completed.stderr or completed.stdout or '').strip().splitlines()[-8:]
        return {'ok': False, 'error': '后台 Blender 没有回传结果; 末尾输出:\n' + '\n'.join(tail)}
    return result


class _RigSyncBase:
    @classmethod
    def poll(cls, context):
        return binding_of(context.active_object) is not None

    def _report(self, result):
        if not result.get('ok'):
            self.report({'ERROR'}, result.get('error', '未知错误'))
            return {'CANCELLED'}
        for note in result.get('notes', ()):
            self.report({'WARNING'}, note)
        self.report({'INFO'}, result.get('summary', '完成'))
        return {'FINISHED'}


class SHIYUME_OT_RigBind(bpy.types.Operator):
    """记下这个骨架的主模型文件, 之后就能推送/拉取"""
    bl_idname = "shiyume.rig_bind"
    bl_label = "绑定骨架主模型"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    rig_name: bpy.props.StringProperty(name="主文件里的骨架名", default="")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'ARMATURE'

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = context.active_object
        target = os.path.abspath(bpy.path.abspath(self.filepath))
        if not os.path.isfile(target):
            self.report({'ERROR'}, "找不到文件: %s" % target)
            return {'CANCELLED'}
        stored = target
        if bpy.data.filepath:
            try:
                stored = bpy.path.relpath(target)
            except ValueError:
                stored = target          # 跨盘符时 relpath 会失败
        rig[SOURCE_FILE_KEY] = stored
        rig[SOURCE_RIG_KEY] = self.rig_name or rig.name
        self.report({'INFO'}, "%s -> %s / %s" % (rig.name, os.path.basename(target),
                                                 rig[SOURCE_RIG_KEY]))
        return {'FINISHED'}


class SHIYUME_OT_RigPush(_RigSyncBase, bpy.types.Operator):
    """把这个骨架的绑定推送到主模型文件并保存(后台执行, 不打断当前会话)。

    推送骨骼静止姿态、骨骼集合、姿势骨约束和物体自定义属性; 场景专有的
    RuriRetarget 约束和 RT./RL. 辅助骨不参与。
    """
    bl_idname = "shiyume.rig_push"
    bl_label = "推送骨架到主模型"
    bl_options = {'REGISTER'}

    def execute(self, context):
        rig = context.active_object
        blend, rig_name = binding_of(rig)
        if not os.path.isfile(blend):
            self.report({'ERROR'}, "主模型文件不在: %s" % blend)
            return {'CANCELLED'}
        snap = snapshot(rig)
        snap["rig"] = rig_name
        handle, path = tempfile.mkstemp(suffix=".json", prefix="shiyume_rig_")
        os.close(handle)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snap, fh)
        try:
            result = _run_worker(blend, path, 'push')
        finally:
            os.remove(path)
        return self._report(result)


class SHIYUME_OT_RigPull(_RigSyncBase, bpy.types.Operator):
    """从主模型文件把绑定拉回这个骨架, 场景里的重定向约束原样保留。"""
    bl_idname = "shiyume.rig_pull"
    bl_label = "从主模型拉取骨架"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = context.active_object
        blend, rig_name = binding_of(rig)
        if not os.path.isfile(blend):
            self.report({'ERROR'}, "主模型文件不在: %s" % blend)
            return {'CANCELLED'}
        handle, path = tempfile.mkstemp(suffix=".json", prefix="shiyume_rig_")
        os.close(handle)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"rig": rig_name}, fh)
        try:
            result = _run_worker(blend, path, 'dump')
            if result.get('ok'):
                with open(result['snapshot'], encoding="utf-8") as fh:
                    snap = json.load(fh)
                os.remove(result['snapshot'])
                summary = apply_snapshot(rig, snap)
                result = {'ok': True, 'summary': "从 %s 拉取: %s"
                          % (os.path.basename(blend), summary)}
        finally:
            if os.path.exists(path):
                os.remove(path)
        return self._report(result)
