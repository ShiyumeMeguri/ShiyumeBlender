"""共用角色数据的算子。

一个角色 = 骨架 + 蒙皮到它身上的网格。绑定是**逐物体**的指针, 所以整角色绑完之后,
任何一个子网格都可以单独解绑、单独推、单独拉, 互不影响。

拉取就地做 (append 来源物体 -> 换数据 -> 丢掉临时物体)。
推送必须起一个后台 Blender, 因为要写进一个没打开的文件; 整个角色一次调用, 存一次盘。
"""

import filecmp
import json
import os
import shutil
import subprocess
import tempfile

import bpy
import numpy

from . import binding
from . import mesh_data
from . import rig_data

MARKER = "@SHIYUMESYNC "
WORKER = os.path.join(os.path.dirname(__file__), "worker.py")
SKIP_PROPS = (binding.FILE_KEY, binding.NAME_KEY)
UDIM_TOKEN = "<UDIM>"                       # 平铺贴图的文件名占位, 一块砖一个文件


# ----------------------------------------------------------------- 贴图文件

def _autosave_backup():
    """RuriAutoSave 的备份模块 —— 它没装, 或者没开备份 / 没配备份根, 就返回 None。

    共用插件目录本来就在 sys.path 上, 所以按名 import 就行。不在模块头 import: 那样这个插件
    的能不能注册就绑在另一个插件在不在上了。
    """
    try:
        from RuriAutoSave import backup
    except ImportError:
        return None
    return backup if backup.configured_roots() is not None else None


def _image_files(image, path):
    """这张图实际压着盘上的哪几个文件 (平铺贴图是一块砖一个文件)。"""
    if image is not None and image.source == 'TILED':
        return [path.replace(UDIM_TOKEN, str(tile.number)) for tile in image.tiles]
    return [path]


def _pixels(path):
    """把一个图片文件解成像素数组; 解不出来 (坏文件 / 不认的格式) 返回 None。

    临时数据块用完必须删掉 —— 拉取是在用户正开着的文件里跑的, 留下来就跟着存进他的工程。
    """
    image = bpy.data.images.load(path, check_existing=False)
    try:
        if image.size[0] == 0 or image.size[1] == 0:
            return None
        buffer = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(buffer)
        return buffer
    finally:
        bpy.data.images.remove(image)


def _same_picture(source, target):
    """两个文件是不是同一张画面 —— 判据是像素, 不是修改时间。

    先比字节: 一样就必然是同一张, 这是同步过一次之后的常态, 省掉两次解码。字节不一样才真的
    解出来比像素 —— 重新导出一遍 (换了压缩、写了新时间戳) 但画面一个点没动的, 不该白搬一次,
    更不该在对面留一份看不出差别的备份。
    解不出来的当作不一样: 宁可多备份一次, 也不能拿一个读不出来的文件当"没变过"。
    """
    if filecmp.cmp(source, target, shallow=False):
        return True
    source_pixels = _pixels(source)
    target_pixels = _pixels(target)
    if source_pixels is None or target_pixels is None:
        return False
    return (source_pixels.shape == target_pixels.shape
            and bool(numpy.array_equal(source_pixels, target_pixels)))


def copy_image_files(rows, source_dir, target_dir):
    """把相对路径的贴图按**同一个相对位置**从 source_dir 复制到 target_dir 下。

    两个文件的目录结构是一样的 (两边都有 textures/), 所以同一个 `//textures/x.png` 在两边
    都成立 —— 前提是文件两边都真的有。缺了材质就是紫的, 所以这里负责把它补齐, 连目录一起建。
    绝对路径的不抄: 两边解出来本来就是同一个文件。打包进 .blend 的也不抄: 数据跟着数据块走。

    同名贴图先比像素: 画面一样就一步都不做 —— 不抄, 也不备份。画面真的变了才动手, 而且要
    盖掉的那份旧文件不是直接覆盖, 先交给 RuriAutoSave **移**进备份目录; 名字和落点全按它
    那一套规则, 这边不自己拼时刻。推、拉两个方向同一条规矩: 被盖掉的那份永远留得住。

    返回 (新建的, 换掉的, 提示列表)。
    """
    created, replaced, notes = [], [], []
    archiver = _autosave_backup()
    for name, path in sorted(rows.items()):
        if not path.startswith('//'):
            continue
        image = bpy.data.images.get((name, None))
        if image is not None and image.packed_file is not None:
            continue
        if image is not None and image.source == 'SEQUENCE':
            notes.append("%s 是图片序列, 只按当前这一帧的文件搬" % name)
        for relative in _image_files(image, path):
            source = bpy.path.abspath(relative, start=source_dir)
            target = bpy.path.abspath(relative, start=target_dir)
            if not os.path.isfile(source):
                notes.append("贴图 %s 在来源这边就找不到, 没搬: %s" % (name, source))
                continue
            if os.path.isfile(target):
                if _same_picture(source, target):
                    continue                       # 画面一样: 不抄, 也不留没差别的备份
                replaced.append(relative)
                if archiver is not None:
                    status, landed = archiver.archive(target)
                    if status == archiver.STATUS_FAILED:
                        raise OSError("旧贴图没能备份到 %s, 不盖它" % landed)
                    notes.append("旧的 %s 已备份到 %s" % (os.path.basename(target), landed))
            else:
                created.append(relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
    if archiver is None and replaced:
        notes.append("RuriAutoSave 没开备份, %d 张画面变了的旧贴图是直接盖掉的" % len(replaced))
    return created, replaced, notes


def _image_summary(created, replaced):
    """复制结果读成一句人话; 一张没动就返回 None。"""
    if not created and not replaced:
        return None
    return "贴图 新增 %d 张, 覆盖 %d 张: %s" % (len(created), len(replaced),
                                            ", ".join((created + replaced)[:4]))


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


def _borrowed_image_paths(images, source_dir):
    """借进来的图片: 把 append 重算过的相对路径还原成**来源文件里原本的那个写法**。

    重算保的是同一个绝对文件, 所以拿绝对路径再相对来源文件算一次, 就回到原来那个字符串。
    来源那边本来就写绝对路径的不动它 —— 两个文件解出来是同一个文件, 没必要改。
    """
    rows = {}
    for image in images:
        if not image.filepath.startswith('//'):
            continue
        try:
            rows[image.name] = bpy.path.relpath(bpy.path.abspath(image.filepath),
                                                start=source_dir)
        except ValueError:                         # 跨盘符算不出相对路径, 保持原样
            continue
    return rows


def pull_one(obj):
    """把一个物体的数据从来源拉回来。返回 (总结, 提示列表)。"""
    path, source_name = binding.get(obj)
    if not os.path.isfile(path):
        raise FileNotFoundError("来源文件不存在: %s" % path)
    known = mesh_data.known_names()          # borrow 之前的名录, 用来认出 append 带进来的
    source, done, origins = binding.borrow(path, source_name)
    try:
        if obj.type != source.type:
            raise TypeError("%s 是 %s, 来源的 %s 是 %s, 类型对不上"
                            % (obj.name, obj.type, source_name, source.type))
        # 借东西必然把材质 / 贴图 / 节点组另造一份带进来, 先让它们接管本地同名的那份:
        # 之后按名字查材质才查得准, 本地别的物体也跟着一起更新
        borrowed_images = mesh_data.appended_since(known)['images']
        adopted, notes = mesh_data.adopt_appended(known)
        if adopted:
            notes.append("按名覆盖 %d 份材质/贴图/节点组: %s"
                         % (len(adopted), ', '.join(adopted[:6])))
        # 贴图跟推送同一套: 路径写成来源那边的原样相对写法, 文件按同一相对位置抄到本文件这边,
        # 这样本文件用的是自己目录下的那份, 而不是隔着一条 `//../共用/textures/` 指过去
        image_rows = _borrowed_image_paths(borrowed_images, os.path.dirname(path))
        if image_rows and not bpy.data.filepath:
            notes.append("本文件还没存过盘, %d 张贴图先按绝对路径留着" % len(image_rows))
        elif image_rows:
            changed, path_notes = mesh_data.apply_image_paths(image_rows)
            notes.extend(path_notes)
            created, replaced, copy_notes = copy_image_files(
                image_rows, os.path.dirname(path), os.path.dirname(bpy.data.filepath))
            notes.extend(copy_notes)
            summary = _image_summary(created, replaced)
            if summary:
                notes.append("%s (路径写回 %d 张)" % (summary, changed))
        if obj.type == 'MESH':
            summary, extra = mesh_data.swap_mesh(
                obj, source.data, [g.name for g in source.vertex_groups],
                sum(1 for v in source.data.vertices if v.groups),
                mesh_data.slot_rows(source))
            return summary, notes + extra
        snap = rig_data.localize(rig_data.snapshot(source, skip_keys=SKIP_PROPS), origins)
        # 拉取进本文件: 本地独有的骨不删 (场景里的机械骨/锚点骨主模型里没有)
        return "%s: %s" % (obj.name, rig_data.apply(obj, snap, remove_extra=False)), notes
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
        # 'OBJECT' 那一路的材质挂在物体上, 不是网格的依赖, 只写网格是带不过去的, 要点名写
        object_materials = {slot.material for o, _ in meshes for slot in o.material_slots
                            if slot.link == 'OBJECT' and slot.material}
        payload = {
            'carrier': None,
            'images': {},
            'object_materials': sorted(m.name for m in object_materials),
            'meshes': [{'carrier_mesh': o.data.name, 'target_obj': n,
                        'vertex_groups': [g.name for g in o.vertex_groups],
                        'weighted': sum(1 for v in o.data.vertices if v.groups),
                        'slots': mesh_data.slot_rows(o)}
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
            # 只写网格数据块 (材质 / 贴图 / 节点组作为它的依赖自动跟着走)。连物体一起写会把
            # 骨架和它那条几百万关键帧的动作拖进来
            bpy.data.libraries.write(carrier,
                                     {o.data for o, _ in meshes} | object_materials,
                                     fake_user=True, compress=True)
            payload['carrier'] = carrier
            # 中转文件的目录就是这次推送的依赖闭包, 里面有哪些图就是哪些图要跟着走 ——
            # 不用自己去遍历节点树数, 那等于把 Blender 算过的依赖再算一遍
            with bpy.data.libraries.load(carrier) as (src, _dst):
                payload['images'] = mesh_data.image_paths(list(src.images))
            relative = [n for n, p in payload['images'].items() if p.startswith('//')]
            if relative and not bpy.data.filepath:
                return {'ok': False,
                        'error': '本文件还没存过盘, %d 张贴图的相对路径没有基准, 解不出来: %s'
                                 % (len(relative), ', '.join(sorted(relative)[:4]))}
            try:
                created, replaced, image_notes = copy_image_files(
                    payload['images'], os.path.dirname(bpy.data.filepath),
                    os.path.dirname(path))
            except OSError as exc:                 # noqa: BLE001 抄不过去就别动共用文件
                return {'ok': False, 'error': '贴图复制失败, 共用文件一个字没写: %s' % exc}
            notes.extend(image_notes)
            summary = _image_summary(created, replaced)
            if summary:
                lines.append(summary)
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

    材质槽、材质、贴图、节点组按名覆盖本地同名的那份 —— 本地别的物体用着同一份材质的,
    也跟着一起更新。走相对路径的贴图文件也按同一相对位置抄到本文件目录下, 本文件用的是
    自己那份, 不是隔着 `//../` 指到主模型目录去; 同名贴图先比像素, 画面一样就不动它,
    真的变了才换, 而被换掉的那份先按 RuriAutoSave 的规则移进备份目录。
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
    """把当前这一个物体推送到主模型并保存（后台执行，不打断当前会话）。

    几何 / 权重 / 形态键形状, 加上材质槽与材质本身（连贴图、节点组）一起过去; 主模型里
    同名的那份材质被就地覆盖, 名字不变, 主模型里用着它的别的物体也跟着更新。

    走相对路径的贴图**文件**会按同一个相对位置复制到主模型目录下（缺的目录自动建）。同名
    贴图先比像素：画面一样就一步都不做；真的变了才换，而且被换掉的那份先按 RuriAutoSave
    的规则移进备份目录，不直接盖。"""
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
    """一键拉取整个角色：骨架 + 全部子网格 + 材质。"""
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
    """一键推送整个角色到主模型（骨架 + 全部子网格 + 材质 + 贴图，一次后台调用，存一次盘）。

    材质、贴图、节点组按名就地覆盖主模型里同名的那份: 名字不漂（导出到引擎那头是按材质名
    对表的），主模型里用着同一份材质的别的物体也跟着更新。

    走相对路径的贴图**文件**按同一个相对位置复制到主模型目录下 —— 两边目录结构一样，所以
    `//textures/x.png` 在那边照样成立（不复制的话那边就是一片紫）。同名贴图先比像素，画面
    一样就不动；真的变了才换，被换掉的那份先按 RuriAutoSave 的规则移进备份目录。"""
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
