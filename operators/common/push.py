"""推送: 把摘下来的数据块写回唯一源, 备份源的这一版历史, 再把链接接回去。

推送的范围是**传进来的那几个数据块**, 不是写死的"整个文件": 整角色推、只推手上这一个网格、
只推刚改完的那几件, 都是同一条路, 上面那层只决定名单。

顺序:

  1. 后台 Blender 写源, 跑在 `--factory-startup` 下 —— 它只做"链数据块 → 换 → 存盘",
     一个插件都用不上, 而加载整套插件是这一步的**全部**开销(实测 12.46s → 1.62s)。
     写之前把保存版本数钉成 1, 于是旧内容留成 `<源>.blend1`。因为不加载插件, 那边的
     RuriAutoSave 一定不在, 所以 `.blend1` 一定由**前台**按同一套规则收走 —— worker 照旧
     回报"收没收走", 前台照着办, 于是永远恰好收一次, 而且不再依赖后台碰巧装了什么。

  2. **存盘, 重新打开本文件。** 源刚被外面改过, 而 Blender 不会自己去重读已经载入的库;
     不重读就用旧内容建覆盖, 存盘重开时 resync 对不上, 覆盖会被整个丢掉 —— 表现是几何回不
     到刚推上去的那一版, 而且下次源再更新也不跟了。`wm.lib_reload` 要窗口上下文, 后台跑不
     起来也就验不了, 所以不用它: 重读整个文件是确定性的, 两种环境下行为一致。

  3. 在重读之后的干净状态里接回链接。

第 2 步之后 Python 这边的数据块引用全部失效, 所以名单不能拿对象存, 只能拿
**(源路径, 类型, 源里的名字)** 这组字符串存 —— 重读之后按它重新认人, 只接回这一次推上去的
那几个, 别人摘开的照旧摘着。

第 2 步会丢掉撤销历史, 但推送本来就是一个"落定"的动作, 而且这一步之前已经存过盘, 没有
数据会丢。
"""

import json
import os
import subprocess
import tempfile

import bpy

from . import linkage

MARKER = "@SHIYUMESYNC "
WORKER = os.path.join(os.path.dirname(__file__), "worker.py")


def detached_of(objects):
    """这些物体身上摘开待推送的数据块 (去重, 保持选中顺序)。"""
    found = []
    for obj in objects:
        datablock = obj.data
        if datablock is not None and linkage.is_detached(datablock) and datablock not in found:
            found.append(datablock)
    return found


def all_detached():
    """整个文件里摘开的数据块。"""
    return [datablock for _path, rows in linkage.detached_datablocks().items()
            for _kind, datablock, _name in rows]


def _grouped(datablocks):
    """{源路径: [(类型, 数据块, 源里的名字)]}; 问不出源的直接忽略。"""
    groups = {}
    for datablock in datablocks:
        kind = linkage.collection_of(datablock)
        reference = linkage.source_reference(datablock)
        if kind is None or reference is None:
            continue
        groups.setdefault(reference[0], []).append((kind, datablock, reference[1]))
    return groups


def _objects_using(datablock):
    return [obj for obj in bpy.data.objects if obj.data is datablock]


def _material_name(material):
    """这个材质在源文件里叫什么; 本文件自己造的就用它本地的名字。"""
    if material is None:
        return None
    reference = linkage.source_reference(material)
    return reference[1] if reference is not None else material.name


def _row(kind, datablock, source_name):
    row = {'carrier_name': datablock.name, 'source_name': source_name}
    if kind == 'meshes':
        users = _objects_using(datablock)
        row['vertex_groups'] = [group.name for group in users[0].vertex_groups] if users else []
        row['materials'] = [_material_name(material) for material in datablock.materials]
    return row


def _run_worker(blend, payload):
    handle, path = tempfile.mkstemp(suffix='.json', prefix='shiyume_payload_')
    with os.fdopen(handle, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False)
    # --factory-startup: worker 只做"链数据块 → 换 → 存盘", 一个插件都用不上, 而加载整套
    # 插件是这一步的**全部**开销 —— 实测同一台机器同一个源文件: 带插件启动 11.23s、
    # factory 0.49s; 开文件并存盘 12.46s vs 1.62s。快 7.7 倍, 而且省下的全是纯启动。
    command = [bpy.app.binary_path, '-b', '--factory-startup', blend,
               '--python', WORKER, '--', path]
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


def _write_carrier(datablocks):
    handle, carrier = tempfile.mkstemp(suffix='.blend', prefix='shiyume_carrier_')
    os.close(handle)
    os.remove(carrier)
    bpy.data.libraries.write(carrier, set(datablocks), fake_user=True, compress=True)
    return carrier


def _archive_source(path, notes):
    """后台那边没人收 `.blend1` 时, 由这边按同一套规则收走。"""
    try:
        from RuriAutoSave import backup
    except ImportError:
        notes.append("RuriAutoSave 没装, %s 的上一版留在源旁边成了 .blend1"
                     % os.path.basename(path))
        return
    if backup.configured_roots() is None:
        notes.append("RuriAutoSave 没配备份根, %s 的上一版留在源旁边"
                     % os.path.basename(path))
        return
    status, landed = backup.harvest(path)
    if status == backup.STATUS_FAILED:
        notes.append("%s 的上一版没能备份到 %s" % (os.path.basename(path), landed))
    elif status != backup.STATUS_NOTHING_TO_MOVE:
        notes.append("源的上一版已备份到 %s" % landed)


def _write_sources(groups, notes):
    """把点到名的每个源各写一次。返回 (成功行, 失败结果或 None)。"""
    lines = []
    for path, rows in groups.items():
        if not os.path.isfile(path):
            return lines, {'ok': False, 'error': '源文件不存在: %s' % path}

        kinds = {}
        for kind, datablock, source_name in rows:
            kinds.setdefault(kind, []).append(_row(kind, datablock, source_name))
        carrier = _write_carrier(datablock for _kind, datablock, _name in rows)
        try:
            result = _run_worker(path, {'carrier': carrier, 'kinds': kinds})
        finally:
            if os.path.exists(carrier):
                os.remove(carrier)
        if not result.get('ok'):
            return lines, result
        if not result.get('archived'):
            _archive_source(path, notes)
        notes.extend(result.get('notes', ()))
        lines.append(result.get('summary', ''))
    return lines, None


def _reattach(datablocks, notes):
    """接回链接; 逐个隔离, 接不回去的点名说。返回 (成功数, 总数)。"""
    done = 0
    for datablock in datablocks:
        name = datablock.name
        try:
            linkage.reattach(datablock)
            done += 1
        except Exception as error:          # noqa: BLE001
            notes.append("%s 接不回链接: %s" % (name, error))
    return done, len(datablocks)


def push(datablocks):
    """把点到名的这几个摘开的数据块推回各自的源, 再接回链接。"""
    groups = _grouped(datablocks)
    if not groups:
        return {'ok': False, 'error': '点到名的东西里没有摘下来待推送的共用数据'}
    work = bpy.data.filepath
    if not work:
        return {'ok': False, 'error': '本文件还没存过盘; 推送之后要重新读它, 先存一次'}

    wanted = {(path, kind, source_name)
              for path, rows in groups.items() for kind, _db, source_name in rows}

    notes = []
    lines, failure = _write_sources(groups, notes)
    if failure is not None:
        return failure

    bpy.ops.wm.save_mainfile()
    bpy.ops.wm.open_mainfile(filepath=work)

    # 重读之后原来的引用全废了, 按名单里那组字符串重新认人
    coming_back = [datablock
                   for path, rows in linkage.detached_datablocks().items()
                   for kind, datablock, source_name in rows
                   if (path, kind, source_name) in wanted]
    done, total = _reattach(coming_back, notes)
    bpy.ops.wm.save_mainfile()

    left = sum(len(rows) for rows in linkage.detached_datablocks().values())
    lines.append("接回 %d/%d" % (done, total))
    if left:
        notes.append("这个文件里还有 %d 份摘开的没推" % left)
    return {'ok': True, 'notes': notes, 'summary': ' | '.join(line for line in lines if line)}


def discard(datablocks):
    """不推送, 丢掉本地改动直接接回源 —— 改错了要放弃时用。"""
    groups = _grouped(datablocks)
    if not groups:
        return {'ok': False, 'error': '点到名的东西里没有摘下来的共用数据'}
    notes = []
    done, total = _reattach(
        [datablock for rows in groups.values() for _kind, datablock, _name in rows], notes)
    return {'ok': True, 'notes': notes, 'summary': "已丢弃本地改动并接回 %d/%d 份" % (done, total)}
