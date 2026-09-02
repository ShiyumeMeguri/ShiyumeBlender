"""共用网格同步: 用"记住来源 + 按需推拉"取代 Blender 的库链接。

为什么不用链接 (实测结论, 别再走回头路):
  形态键的**值**存在 Key 数据块上, Key 属于 mesh。mesh 一旦链接, Key 跟着是
  链接的, 本地怎么改都不写盘 —— 重开就掉回库里的值。而角色体型正是靠这些值
  区分的 (OldBody / Loli / ZMDLoli / Jsspsi ...)。三条路都试过:
    · 链接 mesh 数据          → 值丢
    · 链接物体 + 库覆盖        → 值同样丢, 还会把源文件的父骨架一起拖进来
    · 对 Key 单独 override_create → Blender 直接返回 None, 不支持
  所以"共享几何"和"每个文件自己的体型值"在链接模型下不可兼得。

这里的做法: **不链接**。物体上记一个来源指针 (文件路径 + 数据块名), 网格永远
是本地的、随时可编辑; 需要同步时按按钮, 起一个后台 Blender 把网格数据推过去
或拉过来。共享的是几何 / 拓扑 / 权重 / 形态键的**形状**; 每个文件自己的形态键
**值**在同步时原样保留 —— 那是本文件的视图状态, 不是共享内容。

权重存的是"组下标 → 权重", 组**名**存在物体上, 所以同步网格必须连同物体的
顶点组名表一起同步, 否则权重会静默错位。这一条由 worker 负责, 并且会报出来。
"""

import json
import os
import subprocess
import tempfile

import bpy

SOURCE_FILE_KEY = "shiyume_common_file"
SOURCE_MESH_KEY = "shiyume_common_mesh"
MARKER = "@SHIYUMESYNC "

WORKER = os.path.join(os.path.dirname(__file__), "common_sync_worker.py")


def binding_of(obj):
    """物体上记的来源指针 -> (绝对路径, 数据块名) 或 None。"""
    if obj is None or obj.type != 'MESH':
        return None
    path = obj.get(SOURCE_FILE_KEY)
    name = obj.get(SOURCE_MESH_KEY)
    if not path or not name:
        return None
    return os.path.abspath(bpy.path.abspath(path)), name


def append_meshes(path, names):
    """追加 (不是链接) 指定网格, 并清掉 append 留下的空库记录。

    `libraries.load(link=False)` 会在 bpy.data.libraries 里留一条来源记录。
    数据已经是本地的, 那条记录没有任何用户, 但会一直挂在文件里 —— 推送用的
    中转文件是临时的、事后就删, 留着它等于指向一个不存在的路径。
    """
    before = {lib.name_full for lib in bpy.data.libraries}
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        missing = [n for n in names if n not in src.meshes]
        if missing:
            raise KeyError("%s 里没有网格数据块 %s；现有: %s"
                           % (os.path.basename(path), missing, sorted(src.meshes)[:20]))
        dst.meshes = list(names)
    loaded = list(dst.meshes)
    for lib in list(bpy.data.libraries):
        if lib.name_full in before:
            continue
        if lib.users_id:
            continue
        bpy.data.libraries.remove(lib)
    return loaded


def _run_worker(payload):
    """起一个后台 Blender 执行 worker, 回传它打印的 JSON 结果。"""
    command = [bpy.app.binary_path, '-b', payload['blend'],
               '--python', WORKER, '--', json.dumps(payload, ensure_ascii=False)]
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
        tail = (completed.stderr or completed.stdout or '').strip().splitlines()[-6:]
        return {'ok': False, 'error': '后台 Blender 没有回传结果; 末尾输出:\n' + '\n'.join(tail)}
    return result


class _SyncBase:
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return binding_of(obj) is not None

    def _report_result(self, result):
        if not result.get('ok'):
            self.report({'ERROR'}, result.get('error', '未知错误'))
            return {'CANCELLED'}
        for note in result.get('notes', ()):
            self.report({'WARNING'}, note)
        self.report({'INFO'}, result.get('summary', '完成'))
        return {'FINISHED'}


def mesh_names_in(path):
    """列出某个 blend 文件里的网格数据块名 —— 只读目录, 不加载任何东西。"""
    with bpy.data.libraries.load(path) as (src, _dst):
        return sorted(src.meshes)


# 枚举回调返回的列表必须自己留引用, 否则 Blender 会拿到被回收的字符串 (会崩)
_ITEM_CACHE = {}


def _mesh_enum_items(self, context):
    path = os.path.abspath(bpy.path.abspath(self.filepath)) if self.filepath else ""
    if path not in _ITEM_CACHE:
        try:
            names = mesh_names_in(path)
        except Exception:
            names = []
        _ITEM_CACHE[path] = ([(n, n, "") for n in names]
                             or [("", "（该文件里没有网格数据块）", "")])
    return _ITEM_CACHE[path]


def store_binding(obj, target, mesh_name, relative=True):
    stored = target
    if relative and bpy.data.filepath:
        try:
            stored = bpy.path.relpath(target)
        except ValueError:
            stored = target          # 跨盘符时 relpath 会失败, 退回绝对路径
    obj[SOURCE_FILE_KEY] = stored
    obj[SOURCE_MESH_KEY] = mesh_name
    return stored


class SHIYUME_OT_CommonBindPick(bpy.types.Operator):
    """从来源文件里实际存在的网格数据块中选一个（下拉，不用打字）。"""
    bl_idname = "shiyume.common_bind_pick"
    bl_label = "选择数据块"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    filepath: bpy.props.StringProperty(options={'HIDDEN'})
    use_relative: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    mesh_name: bpy.props.EnumProperty(
        name="数据块", items=_mesh_enum_items,
        description="来源文件里的网格数据块")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def invoke(self, context, event):
        _ITEM_CACHE.clear()          # 换文件后要重新读目录
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.label(text=os.path.basename(self.filepath), icon='FILE_BLEND')
        layout.prop(self, "mesh_name")

    def execute(self, context):
        if not self.mesh_name:
            self.report({'ERROR'}, "该文件里没有网格数据块")
            return {'CANCELLED'}
        obj = context.active_object
        stored = store_binding(obj, os.path.abspath(bpy.path.abspath(self.filepath)),
                               self.mesh_name, self.use_relative)
        self.report({'INFO'}, "已绑定 %s -> %s / %s" % (obj.name, stored, self.mesh_name))
        return {'FINISHED'}


class SHIYUME_OT_CommonBind(bpy.types.Operator):
    """浏览选择来源 blend 文件，把当前网格物体关联过去。

    只在物体上记一个指针（文件路径 + 数据块名），不产生任何 Blender 链接：
    网格仍然是本地的，随时可以进编辑模式改。
    选完文件后按同名自动匹配；同名的找不到才弹出下拉让你从该文件里实际存在的
    网格数据块中选 —— 全程不需要手打名字。"""
    bl_idname = "shiyume.common_bind"
    bl_label = "绑定共用网格来源"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})
    use_relative: bpy.props.BoolProperty(
        name="相对路径", default=True,
        description="按 // 相对当前文件保存路径，整个项目搬家后依然有效")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = context.active_object
        if not self.filepath:
            self.report({'ERROR'}, "没有选择来源文件")
            return {'CANCELLED'}
        target = os.path.abspath(bpy.path.abspath(self.filepath))
        if not os.path.isfile(target):
            self.report({'ERROR'}, "来源文件不存在: %s" % target)
            return {'CANCELLED'}
        if bpy.data.filepath and os.path.samefile(target, bpy.data.filepath):
            self.report({'ERROR'}, "来源不能是当前文件本身")
            return {'CANCELLED'}

        try:
            names = mesh_names_in(target)
        except Exception as exc:
            self.report({'ERROR'}, "读不出 %s 的内容: %s" % (os.path.basename(target), exc))
            return {'CANCELLED'}
        if not names:
            self.report({'ERROR'}, "%s 里没有网格数据块" % os.path.basename(target))
            return {'CANCELLED'}

        if obj.data.name in names:
            stored = store_binding(obj, target, obj.data.name, self.use_relative)
            self.report({'INFO'}, "已绑定 %s -> %s / %s（同名自动匹配）"
                        % (obj.name, stored, obj.data.name))
            return {'FINISHED'}

        # 同名的没有 -> 弹下拉让用户从这个文件里实际有的网格中选
        bpy.ops.shiyume.common_bind_pick(
            'INVOKE_DEFAULT', filepath=target, use_relative=self.use_relative)
        return {'FINISHED'}


class SHIYUME_OT_CommonUnbind(bpy.types.Operator):
    """解除共用网格来源的绑定（只删指针，不动网格）。"""
    bl_idname = "shiyume.common_unbind"
    bl_label = "解除绑定"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return binding_of(context.active_object) is not None

    def execute(self, context):
        obj = context.active_object
        for key in (SOURCE_FILE_KEY, SOURCE_MESH_KEY):
            if key in obj:
                del obj[key]
        self.report({'INFO'}, "已解除 %s 的绑定" % obj.name)
        return {'FINISHED'}


class SHIYUME_OT_CommonPush(_SyncBase, bpy.types.Operator):
    """把当前网格推送到来源文件并保存（后台执行，不打断当前会话）。

    推送的是几何/拓扑/权重/形态键的形状，以及物体的顶点组名表（权重存的是组
    下标，不带名表过去会静默错位）。来源文件里各形态键的**值**原样保留。"""
    bl_idname = "shiyume.common_push"
    bl_label = "推送到共用文件"
    bl_options = {'REGISTER'}

    def execute(self, context):
        obj = context.active_object
        binding = binding_of(obj)
        target_path, target_mesh = binding
        if not os.path.isfile(target_path):
            self.report({'ERROR'}, "来源文件不存在: %s" % target_path)
            return {'CANCELLED'}

        handle, temp = tempfile.mkstemp(suffix='.blend', prefix='shiyume_sync_')
        os.close(handle)
        os.remove(temp)
        bpy.data.libraries.write(temp, {obj.data}, fake_user=True, compress=True)

        payload = {
            'mode': 'push',
            'blend': target_path,
            'carrier': temp,
            'carrier_mesh': obj.data.name,
            'target_mesh': target_mesh,
            'vertex_groups': [g.name for g in obj.vertex_groups],
        }
        try:
            result = _run_worker(payload)
        finally:
            if os.path.exists(temp):
                os.remove(temp)
        return self._report_result(result)


class SHIYUME_OT_CommonPull(_SyncBase, bpy.types.Operator):
    """从来源文件把网格数据拉回当前文件（覆盖本地网格）。

    本地各形态键的**值**原样保留 —— 那是本文件自己的体型设定。"""
    bl_idname = "shiyume.common_pull"
    bl_label = "从共用文件拉取"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        target_path, target_mesh = binding_of(obj)
        if not os.path.isfile(target_path):
            self.report({'ERROR'}, "来源文件不存在: %s" % target_path)
            return {'CANCELLED'}

        try:
            incoming = append_meshes(target_path, [target_mesh])[0]
        except KeyError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        old = obj.data
        values = ({k.name: (k.value, k.mute) for k in old.shape_keys.key_blocks}
                  if old.shape_keys else {})
        groups = [g.name for g in obj.vertex_groups]

        obj.data = incoming
        notes = []
        if incoming.shape_keys:
            for block in incoming.shape_keys.key_blocks:
                if block.name in values:
                    block.value, block.mute = values[block.name]
                else:
                    notes.append("新形态键 %s（本地没有，用来源文件的值）" % block.name)
        incoming.name = old.name
        old.use_fake_user = False
        if old.users == 0:
            bpy.data.meshes.remove(old)

        new_groups = [g.name for g in obj.vertex_groups]
        if new_groups != groups:
            notes.append("顶点组名表变了（%d -> %d）" % (len(groups), len(new_groups)))
        return self._report_result({
            'ok': True,
            'notes': notes,
            'summary': "已从 %s 拉取 %s：%d 顶点，%d 形态键值已保留"
                       % (os.path.basename(target_path), target_mesh,
                          len(incoming.vertices), len(values)),
        })
