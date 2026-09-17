"""推送: 把摘下来的数据块写回唯一源, 备份源的这一版历史, 再把链接接回去。

一次推整个文件, 不是推选中的那几个 —— "始终只有一个源"这句话要成立, 文件里就不能留着
一份摘开的数据块不管它。摘开的那份是这个文件私有的岔路, 推完必须收回去。

顺序:

  1. 后台 Blender 写源。写之前把保存版本数钉成 1, 于是旧内容留成 `<源>.blend1`。那一下是
     货真价实的保存, 后台那边的 RuriAutoSave 自己就会收走它 —— 但它读的是**存盘的**
     userpref, 前台这个会话里刚改过还没存的备份设置它看不见。所以 worker 回报"收没收走",
     没收走这边才按同一套规则补一次, 于是永远恰好收一次。

  2. **存盘, 重新打开本文件。** 源刚被外面改过, 而 Blender 不会自己去重读已经载入的库;
     不重读就用旧内容建覆盖, 存盘重开时 resync 对不上, 覆盖会被整个丢掉 —— 表现是几何回不
     到刚推上去的那一版, 而且下次源再更新也不跟了。`wm.lib_reload` 要窗口上下文, 后台跑不
     起来也就验不了, 所以不用它: 重读整个文件是确定性的, 两种环境下行为一致。

  3. 在重读之后的干净状态里逐个 reattach, 再存一次。

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


def _objects_using(datablock):
    return [obj for obj in bpy.data.objects if obj.data is datablock]


def _row(kind, datablock, source_name):
    row = {'carrier_name': datablock.name, 'source_name': source_name}
    if kind == 'meshes':
        users = _objects_using(datablock)
        row['vertex_groups'] = [group.name for group in users[0].vertex_groups] if users else []
    return row


def _run_worker(blend, payload):
    handle, path = tempfile.mkstemp(suffix='.json', prefix='shiyume_payload_')
    with os.fdopen(handle, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False)
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
    """把每个源各写一次。返回 (成功行, 失败结果或 None)。"""
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
        lines.append(result.get('summary', ''))
    return lines, None


def reattach_detached(notes):
    """把文件里所有摘开的数据块接回源。返回 (接回数, 总数)。"""
    groups = linkage.detached_datablocks()
    total = sum(len(rows) for rows in groups.values())
    done = 0
    for path, rows in groups.items():
        if not os.path.isfile(path):
            notes.append("源文件不存在, 接不回去: %s" % path)
            continue
        for _kind, datablock, _source_name in rows:
            name = datablock.name
            try:
                linkage.reattach(datablock)
                done += 1
            except Exception as error:      # noqa: BLE001 逐个隔离: 接不回去要点名说
                notes.append("%s 接不回链接: %s" % (name, error))
    return done, total


def push_all():
    """把整个文件里摘开的数据块推回各自的源, 再接回链接。"""
    groups = linkage.detached_datablocks()
    if not groups:
        return {'ok': False, 'error': '这个文件里没有摘下来待推送的共用数据'}
    work = bpy.data.filepath
    if not work:
        return {'ok': False, 'error': '本文件还没存过盘; 推送之后要重新读它, 先存一次'}

    notes = []
    lines, failure = _write_sources(groups, notes)
    if failure is not None:
        return failure

    bpy.ops.wm.save_mainfile()
    bpy.ops.wm.open_mainfile(filepath=work)

    done, total = reattach_detached(notes)
    bpy.ops.wm.save_mainfile()
    lines.append("接回 %d/%d" % (done, total))
    return {'ok': True, 'notes': notes, 'summary': ' | '.join(line for line in lines if line)}


def discard_local():
    """不推送, 只把摘开的数据块丢掉本地改动接回源 —— 改错了要放弃时用。"""
    if not linkage.detached_datablocks():
        return {'ok': False, 'error': '这个文件里没有摘下来的共用数据'}
    notes = []
    done, total = reattach_detached(notes)
    return {'ok': True, 'notes': notes, 'summary': "已丢弃本地改动并接回 %d/%d 份" % (done, total)}
