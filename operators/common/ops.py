"""共用角色数据的算子。

一个角色 = 骨架 + 蒙皮到它身上的网格。绑定是**逐物体**的指针, 所以整角色绑完之后,
任何一个子网格都可以单独解绑、单独推、单独拉, 互不影响。

拉取就地做 (append 来源物体 -> 换数据 -> 丢掉临时物体)。
推送必须起一个后台 Blender, 因为要写进一个没打开的文件; 整个角色一次调用, 存一次盘。
"""

import json
import os
import subprocess
import tempfile

import bpy

from . import binding
from . import mesh_data
from . import rig_data

MARKER = "@SHIYUMESYNC "
WORKER = os.path.join(os.path.dirname(__file__), "worker.py")
SKIP_PROPS = (binding.FILE_KEY, binding.NAME_KEY)


# ----------------------------------------------------------------- 角色与拉取

def active_character(context):
    """从当前选中推出角色: 选骨架就是它本身, 选网格就是它蒙皮的那副骨架。"""
    obj = context.active_object
    if obj is None:
        return None, []
    if obj.type == 'ARMATURE':
        return obj, binding.character_of(obj)
    if obj.type == 'MESH':
        rig = binding.rig_of(obj)
        if rig is not None:
            return rig, binding.character_of(rig)
    return None, []


def pull_one(obj):
    """把一个物体的数据从来源拉回来。返回 (总结, 提示列表)。"""
    path, source_name = binding.get(obj)
    if not os.path.isfile(path):
        raise FileNotFoundError("来源文件不存在: %s" % path)
    source, done = binding.borrow(path, source_name)
    try:
        if obj.type != source.type:
            raise TypeError("%s 是 %s, 来源的 %s 是 %s, 类型对不上"
                            % (obj.name, obj.type, source_name, source.type))
        if obj.type == 'MESH':
            return mesh_data.swap_mesh(obj, source.data,
                                       [g.name for g in source.vertex_groups])
        snap = rig_data.snapshot(source, skip_keys=SKIP_PROPS)
        # 拉取进本文件: 本地独有的骨不删 (场景里的机械骨/锚点骨主模型里没有)
        return "%s: %s" % (obj.name, rig_data.apply(obj, snap, remove_extra=False)), []
    finally:
        done()


def pull_many(objects):
    """逐个拉取, 单个失败不影响其它的。返回 (成功行, 提示, 失败行)。"""
    lines, notes, errors = [], [], []
    for obj in objects:
        if binding.get(obj) is None:
            continue
        try:
            summary, extra = pull_one(obj)
        except Exception as exc:                  # noqa: BLE001 逐个隔离, 失败要报出来
            errors.append("%s: %s" % (obj.name, exc))
            continue
        binding.stamp(obj)          # 已经和共用文件对齐了, 重新盖戳
        lines.append(summary)
        notes.extend("%s: %s" % (obj.name, n) for n in extra)
    return lines, notes, errors


# ----------------------------------------------------------------- 推送

def _run_worker(blend, payload):
    handle, path = tempfile.mkstemp(suffix='.json', prefix='shiyume_payload_')
    with os.fdopen(handle, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False)
    command = [bpy.app.binary_path, '-b', blend, '--python', WORKER, '--', path]
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace')
    finally:
        os.remove(path)
    for line in (completed.stdout or '').splitlines():
        if line.startswith(MARKER):
            try:
                return json.loads(line[len(MARKER):])
            except ValueError:
                pass
    tail = (completed.stderr or completed.stdout or '').strip().splitlines()[-8:]
    return {'ok': False, 'error': '后台 Blender 没有回传结果; 末尾输出:\n' + '\n'.join(tail)}


def push_objects(objects):
    """把一批物体推回各自的来源文件。按文件分组, 一个文件起一个后台 Blender。"""
    groups = {}
    for obj in objects:
        bound = binding.get(obj)
        if bound is None:
            continue
        path, source_name = bound
        groups.setdefault(path, []).append((obj, source_name))
    if not groups:
        return {'ok': False, 'error': '选中的东西一个都没绑定共用来源'}

    lines, notes = [], []
    for path, rows in groups.items():
        if not os.path.isfile(path):
            return {'ok': False, 'error': '来源文件不存在: %s' % path}
        meshes = [(o, n) for o, n in rows if o.type == 'MESH']
        rigs = [(o, n) for o, n in rows if o.type == 'ARMATURE']
        payload = {
            'carrier': None,
            'meshes': [{'carrier_mesh': o.data.name, 'target_obj': n,
                        'vertex_groups': [g.name for g in o.vertex_groups]}
                       for o, n in meshes],
            'rigs': [{'target_obj': n,
                      'snapshot': rig_data.snapshot(o, skip_keys=SKIP_PROPS)}
                     for o, n in rigs],
        }
        carrier = None
        if meshes:
            handle, carrier = tempfile.mkstemp(suffix='.blend', prefix='shiyume_carrier_')
            os.close(handle)
            os.remove(carrier)
            # 只写网格数据块。连物体一起写会把骨架和它那条几百万关键帧的动作拖进来
            bpy.data.libraries.write(carrier, {o.data for o, _ in meshes},
                                     fake_user=True, compress=True)
            payload['carrier'] = carrier
        try:
            result = _run_worker(path, payload)
        finally:
            if carrier and os.path.exists(carrier):
                os.remove(carrier)
        if not result.get('ok'):
            return result
        for obj, _n in rows:
            binding.stamp(obj)      # 共用文件刚被我们写过, 戳要跟上新的修改时间
        lines.append(result.get('summary', ''))
        notes.extend(result.get('notes', ()))
    return {'ok': True, 'notes': notes, 'summary': ' | '.join(lines)}


# ----------------------------------------------------------------- 公共基类

class _Reporting:
    def _done(self, result):
        if not result.get('ok'):
            self.report({'ERROR'}, result.get('error', '未知错误'))
            return {'CANCELLED'}
        for note in result.get('notes', ())[:12]:
            self.report({'WARNING'}, note)
        self.report({'INFO'}, result.get('summary', '完成'))
        return {'FINISHED'}

    def _from_pull(self, lines, notes, errors):
        for note in notes[:12]:
            self.report({'WARNING'}, note)
        for err in errors:
            self.report({'ERROR'}, err)
        if not lines:
            self.report({'ERROR'}, '没有拉取到任何东西' if not errors else '全部失败')
            return {'CANCELLED'}
        self.report({'INFO'}, "拉取 %d 项: %s" % (len(lines), ' | '.join(lines[:4])
                                                  + (' ...' if len(lines) > 4 else '')))
        return {'FINISHED'}


# ----------------------------------------------------------------- 绑定

_ITEM_CACHE = {}


def _source_enum(self, context):
    """枚举回调返回的列表必须自己留引用, 否则 Blender 会拿到被回收的字符串 (会崩)。"""
    path = os.path.abspath(bpy.path.abspath(self.filepath)) if self.filepath else ""
    key = (path, self.kind)
    if key not in _ITEM_CACHE:
        try:
            names, meshes, arms = binding.source_names(path)
        except Exception:                          # noqa: BLE001 读不出就给空列表
            names, meshes, arms = [], set(), set()
        pool = meshes if self.kind == 'MESH' else arms
        items = [(n, n, "") for n in names if n in pool] or [(n, n, "") for n in names]
        _ITEM_CACHE[key] = items or [("", "（该文件里没有可用物体）", "")]
    return _ITEM_CACHE[key]


class SHIYUME_OT_CommonBindPick(bpy.types.Operator):
    """从来源文件里实际存在的物体中选一个（下拉，不用打字）。"""
    bl_idname = "shiyume.common_bind_pick"
    bl_label = "选择来源物体"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    filepath: bpy.props.StringProperty(options={'HIDDEN'})
    kind: bpy.props.StringProperty(default='MESH', options={'HIDDEN'})
    use_relative: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    source_name: bpy.props.EnumProperty(name="来源物体", items=_source_enum)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in binding.KINDS

    def invoke(self, context, event):
        _ITEM_CACHE.clear()                        # 换文件后要重新读目录
        self.kind = context.active_object.type
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, context):
        self.layout.label(text=os.path.basename(self.filepath), icon='FILE_BLEND')
        self.layout.prop(self, "source_name")

    def execute(self, context):
        if not self.source_name:
            self.report({'ERROR'}, "该文件里没有可绑定的物体")
            return {'CANCELLED'}
        obj = context.active_object
        stored = binding.put(obj, os.path.abspath(bpy.path.abspath(self.filepath)),
                             self.source_name, self.use_relative)
        self.report({'INFO'}, "已绑定 %s -> %s / %s" % (obj.name, stored, self.source_name))
        return {'FINISHED'}


def _stem(name):
    """去掉 Blender 的 .001 / .002 重名后缀。"""
    head, _dot, tail = name.rpartition('.')
    return head if head and tail.isdigit() and len(tail) == 3 else name


def _bind_by_name(objects, path, relative):
    """按物体名去来源文件里对号入座。返回 (命中, 去后缀命中, 未命中)。

    先精确匹配物体名。对不上的再去掉 `.001` 这类重名后缀比一次 —— 但**只在
    来源里恰好只有一个同词干的物体时才认**, 有歧义宁可报未命中让人手选, 也不瞎猜。
    """
    names, _meshes, _arms = binding.source_names(path)
    pool = set(names)
    by_stem = {}
    for n in names:
        by_stem.setdefault(_stem(n), []).append(n)
    hit, fuzzy, miss = [], [], []
    for obj in objects:
        if obj.name in pool:
            binding.put(obj, path, obj.name, relative)
            hit.append(obj.name)
            continue
        candidates = by_stem.get(_stem(obj.name), [])
        if len(candidates) == 1:
            binding.put(obj, path, candidates[0], relative)
            fuzzy.append("%s -> %s" % (obj.name, candidates[0]))
        else:
            miss.append(obj.name)
    return hit, fuzzy, miss


class SHIYUME_OT_CharBind(bpy.types.Operator):
    """选一个主模型文件，把整个角色（骨架 + 全部蒙皮子网格）一次绑过去。

    按**物体名**对号入座：append 进场景之后数据块名必然带 .001 后缀，物体名才是
    稳定的那一头（实测按数据块名 17 个只能命中 1 个，按物体名命中 15 个）。
    对不上的会列出来，用子网格自己的"换来源物体"下拉单独指定即可。"""
    bl_idname = "shiyume.char_bind"
    bl_label = "绑定整个角色到主模型"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})
    use_relative: bpy.props.BoolProperty(
        name="相对路径", default=True,
        description="按 // 相对当前文件保存路径，整个项目搬家后依然有效")

    @classmethod
    def poll(cls, context):
        rig, _ = active_character(context)
        return rig is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig, meshes = active_character(context)
        if rig is None:
            self.report({'ERROR'}, "当前选中推不出角色（选骨架或它的子网格）")
            return {'CANCELLED'}
        target = os.path.abspath(bpy.path.abspath(self.filepath))
        if not os.path.isfile(target):
            self.report({'ERROR'}, "来源文件不存在: %s" % target)
            return {'CANCELLED'}
        if bpy.data.filepath and os.path.samefile(target, bpy.data.filepath):
            self.report({'ERROR'}, "来源不能是当前文件本身")
            return {'CANCELLED'}
        try:
            hit, fuzzy, miss = _bind_by_name([rig] + meshes, target, self.use_relative)
        except Exception as exc:                   # noqa: BLE001
            self.report({'ERROR'}, "读不出 %s: %s" % (os.path.basename(target), exc))
            return {'CANCELLED'}
        for row in fuzzy[:8]:
            self.report({'WARNING'}, "去后缀才对上: %s" % row)
        if miss:
            self.report({'WARNING'}, "对不上的 %d 个, 用「换来源物体」手选: %s"
                        % (len(miss), ', '.join(miss[:8])))
        self.report({'INFO'}, "%s: 绑定 %d 个 (同名 %d + 去后缀 %d), 未命中 %d 个"
                    % (os.path.basename(target), len(hit) + len(fuzzy),
                       len(hit), len(fuzzy), len(miss)))
        return {'FINISHED'}


class SHIYUME_OT_CommonUnbind(bpy.types.Operator):
    """只解除当前这一个物体的共用绑定（指针删掉，数据一点不动）。"""
    bl_idname = "shiyume.common_unbind"
    bl_label = "解除这一个的绑定"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return binding.get(context.active_object) is not None

    def execute(self, context):
        obj = context.active_object
        binding.clear(obj)
        self.report({'INFO'}, "已解除 %s 的绑定，它不再跟主模型同步" % obj.name)
        return {'FINISHED'}


class SHIYUME_OT_CharUnbind(bpy.types.Operator):
    """解除整个角色的绑定（骨架 + 全部子网格）。"""
    bl_idname = "shiyume.char_unbind"
    bl_label = "解除整个角色的绑定"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig, _ = active_character(context)
        return rig is not None

    def execute(self, context):
        rig, meshes = active_character(context)
        n = sum(1 for o in [rig] + meshes if binding.clear(o))
        self.report({'INFO'}, "已解除 %d 个物体的绑定" % n)
        return {'FINISHED'}


# ----------------------------------------------------------------- 推 / 拉

class SHIYUME_OT_CommonPull(_Reporting, bpy.types.Operator):
    """把当前这一个物体的数据从主模型拉回来（覆盖本地数据）。

    本地形态键的**值**原样保留 —— 那是本文件自己的体型设定。"""
    bl_idname = "shiyume.common_pull"
    bl_label = "拉取这一个"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return binding.get(context.active_object) is not None

    def execute(self, context):
        return self._from_pull(*pull_many([context.active_object]))


class SHIYUME_OT_CommonPush(_Reporting, bpy.types.Operator):
    """把当前这一个物体推送到主模型并保存（后台执行，不打断当前会话）。"""
    bl_idname = "shiyume.common_push"
    bl_label = "推送这一个"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return binding.get(context.active_object) is not None

    def execute(self, context):
        return self._done(push_objects([context.active_object]))


class SHIYUME_OT_CharPullMeshes(_Reporting, bpy.types.Operator):
    """一键拉取这个角色所有子对象的网格（不动骨架）。"""
    bl_idname = "shiyume.char_pull_meshes"
    bl_label = "一键拉取全部子网格"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig, meshes = active_character(context)
        return any(binding.get(o) is not None for o in meshes)

    def execute(self, context):
        _rig, meshes = active_character(context)
        return self._from_pull(*pull_many(meshes))


class SHIYUME_OT_CharPull(_Reporting, bpy.types.Operator):
    """一键拉取整个角色：骨架 + 全部子网格。"""
    bl_idname = "shiyume.char_pull"
    bl_label = "一键拉取整个角色"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig, meshes = active_character(context)
        return rig is not None and any(binding.get(o) is not None for o in [rig] + meshes)

    def execute(self, context):
        rig, meshes = active_character(context)
        # 先骨架后网格: 网格换完数据要按新的顶点组名表对齐, 骨架先到位才不会对着旧骨头
        return self._from_pull(*pull_many([rig] + meshes))


class SHIYUME_OT_CharPush(_Reporting, bpy.types.Operator):
    """一键推送整个角色到主模型（骨架 + 全部子网格，一次后台调用，存一次盘）。"""
    bl_idname = "shiyume.char_push"
    bl_label = "一键推送整个角色"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        rig, meshes = active_character(context)
        return rig is not None and any(binding.get(o) is not None for o in [rig] + meshes)

    def execute(self, context):
        rig, meshes = active_character(context)
        return self._done(push_objects([rig] + meshes))


class SHIYUME_OT_CommonMakeLocal(bpy.types.Operator):
    """把文件里残留的库链接全部本地化，之后一切靠这个插件同步。"""
    bl_idname = "shiyume.common_make_local"
    bl_label = "本地化全部链接数据"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.libraries)

    def execute(self, context):
        libs = [(lib.filepath, lib.name_full) for lib in bpy.data.libraries]
        bpy.ops.object.make_local(type='ALL')
        for lib in list(bpy.data.libraries):
            if not lib.users_id:
                bpy.data.libraries.remove(lib)
        left = [lib.filepath for lib in bpy.data.libraries]
        if left:
            self.report({'WARNING'}, "还剩 %d 个库没本地化: %s" % (len(left), left[:3]))
        self.report({'INFO'}, "本地化了 %d 个库: %s"
                    % (len(libs) - len(left), [os.path.basename(p) for p, _ in libs][:4]))
        return {'FINISHED'}


classes = (
    SHIYUME_OT_CommonBindPick,
    SHIYUME_OT_CharBind,
    SHIYUME_OT_CommonUnbind,
    SHIYUME_OT_CharUnbind,
    SHIYUME_OT_CommonPull,
    SHIYUME_OT_CommonPush,
    SHIYUME_OT_CharPullMeshes,
    SHIYUME_OT_CharPull,
    SHIYUME_OT_CharPush,
    SHIYUME_OT_CommonMakeLocal,
)
