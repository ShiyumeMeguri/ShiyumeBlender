"""后台执行体: 在唯一源里用推上来的数据块整份替换同名那几份, 然后存一次盘。

由 push.py 以 `blender -b <源文件> --python worker.py -- <payload.json>` 启动。跑在干净的
后台进程里, 不 import 插件的任何东西 —— 它要做的事只是"换数据块", 不需要知道链接那一套。

为什么是整份替换而不是逐项合并: 工作文件里那份本来就是从源上摘下来的同一份, 血统一致,
不存在"两边各改了一半要对齐"的问题。合并代码全删了。

`dst.<类型>` 的有序返回是唯一可靠的回查方式: append 撞名会加 `.001` 后缀, 按名字回查
会认错人。

存盘前把保存版本数钉成 1, 于是 Blender 自己把旧内容留成 `<源>.blend1`。**收走它的不是这里**
—— 这一下是一次货真价实的保存, RuriAutoSave 自己的 save_post 会把那份旧内容按它那一套规则
收进备份树。备份的规则只有它那一份, 这边再收一次就是第二处真源。

这里只做一件事: 存完看一眼 `.blend1` 还在不在, 把结论回传。它还在就说明没人收 —— 那是
RuriAutoSave 没装或没配备份根, 得让人知道, 而不是当作备份成功了。

**存盘之前先核对, 对不上就炸, 绝不退而求其次。** 源是唯一真源, 一次静默的缺斤少两会顺着
链接扩散到每一个子文件, 还要等下次打开才看得见。所以这里没有任何"尽力而为"的分支: 顶点数、
带权重的顶点数、权重条数、顶点组名单, 有一项对不上就 fail 并且**不存盘**, 源文件一个字节
都不动。材质槽在源里找不到名字同理 —— 接上去等于把源那几个槽清空, 也是炸。
"""

import json
import os
import sys

import bpy

MARKER = "@SHIYUMESYNC "
REQUIRED_SAVE_VERSION = 1


def emit(payload):
    print(MARKER + json.dumps(payload, ensure_ascii=False))


def fail(message):
    emit({'ok': False, 'error': message})
    sys.exit(0)


def take(carrier, wanted):
    """把中转文件里点名的数据块 append 进来, 按请求顺序返回 {类型: [数据块]}。"""
    before = {library.name_full for library in bpy.data.libraries}
    with bpy.data.libraries.load(carrier, link=False) as (source, target):
        for kind, names in wanted.items():
            available = getattr(source, kind)
            missing = [name for name in names if name not in available]
            if missing:
                fail("中转文件的 %s 里没有 %s; 现有 %s"
                     % (kind, missing, sorted(available)[:20]))
            setattr(target, kind, list(names))
    loaded = {kind: list(getattr(target, kind)) for kind in wanted}
    for library in list(bpy.data.libraries):
        if library.name_full not in before and not library.users_id:
            bpy.data.libraries.remove(library)
    return loaded


def shape_values(datablock):
    keys = getattr(datablock, "shape_keys", None)
    return {block.name: block.value for block in keys.key_blocks} if keys else {}


def apply_shape_values(datablock, values):
    keys = getattr(datablock, "shape_keys", None)
    if keys is None:
        return
    for name, value in values.items():
        block = keys.key_blocks.get(name)
        if block is not None:
            block.value = value


def replace(kind, source_name, incoming):
    """源里那份让位给推上来的这份: 先把用户接过去, 再删旧的, 最后把名字让出来。

    顺序不能换。旧的还在的时候改名会让新的拿到 `.001`, 而名字正是下一次推送回查的依据。
    返回改名之前用着旧数据块的那些物体。

    形态键的**形状**是源的资产, 跟着数据块过去; **值**是每个文件自己的体型设定, 所以源上
    原来是多少, 换完还得是多少 —— 不接这一手, 推一次就把源的体型按成工作文件的。
    """
    collection = getattr(bpy.data, kind)
    existing = collection.get(source_name)
    if existing is None:
        fail("源文件的 %s 里没有 %r" % (kind, source_name))
    if existing.library is not None:
        fail("源文件里的 %s / %r 自己也是链接来的, 不能在这里改" % (kind, source_name))
    if existing is incoming:
        fail("源里那份和推上来的是同一个数据块 %r" % source_name)

    users = [obj for obj in bpy.data.objects if obj.data is existing]
    kept = shape_values(existing)
    existing.user_remap(incoming)
    collection.remove(existing)
    incoming.name = source_name
    apply_shape_values(incoming, kept)
    return users


def apply_materials(mesh, names):
    """材质槽按**名字**在源里重新接一遍, 返回源里找不到的那些。

    工作文件里那些材质本来就是从这个源链接过去的, 写进中转文件时只留下一条"指向源文件的
    引用"; 把这个网格 append 回源自己身上, 那条引用就指向了自己, 解不开 —— 现场是源里的材质
    关联被打断, 重新打开工作文件报 `LIB: Material: 'X' missing`。

    材质槽是源的资产, 推送本来就不该改它, 所以这里按名字接回源自己那几份就是正解。源里没有
    的名字**不留空槽** —— 留空就是把源那个槽的材质抹了。返回给 main 当场 fail, 在存盘之前,
    所以这一次 clear/append 只发生在内存里, 源文件一个字节都没动。
    """
    missing = []
    mesh.materials.clear()
    for name in names:
        material = bpy.data.materials.get(name) if name else None
        if name and material is None:
            missing.append(name)
        mesh.materials.append(material)
    return missing


def mesh_facts(mesh, users):
    """一个网格身上"推送绝不许弄丢"的那几个数。两边用同一个函数量, 才比得出真差别。

    顶点组是**网格域**的 (实测: 两个物体共用一个网格, 一边加组另一边立刻看得见), 所以组名
    和权重都随网格一起走, 中转文件原样带得过去 —— 这里只负责核对, 不负责搬运。
    """
    return {
        'vertices': len(mesh.vertices),
        'weighted': sum(1 for vertex in mesh.vertices if vertex.groups),
        'weights': sum(len(vertex.groups) for vertex in mesh.vertices),
        'groups': [group.name for group in users[0].vertex_groups] if users else [],
    }


def verify(source_name, expected, actual):
    """落进源里的必须和推上来的一模一样, 差一个数就当场炸, **不存盘**。

    这里绝不"尽力而为": 源是唯一真源, 一次静默的缺斤少两会顺着链接扩散到每一个子文件, 而且
    要等下次打开才看得见。宁可推送失败让人重来, 也不能存一份少了东西的源。
    """
    if expected is None:
        return
    bad = [key for key in ('vertices', 'weighted', 'weights', 'groups')
           if expected.get(key) != actual.get(key)]
    if not bad:
        return
    detail = "; ".join(
        "%s 推上来 %r 落地却是 %r"
        % (key,
           len(expected[key]) if key == 'groups' else expected[key],
           len(actual[key]) if key == 'groups' else actual[key])
        for key in bad)
    fail("%s 落进源里之后对不上, 已放弃写入 (源文件一个字节都没动): %s" % (source_name, detail))


def main():
    try:
        with open(sys.argv[sys.argv.index('--') + 1], encoding='utf-8') as handle:
            payload = json.load(handle)
    except (ValueError, IndexError, OSError) as error:
        fail("payload 读取失败: %s" % error)

    kinds = payload.get('kinds', {})
    wanted = {kind: [row['carrier_name'] for row in rows]
              for kind, rows in kinds.items() if rows}
    if not wanted:
        fail("没有任何要推送的数据块")

    loaded = take(payload['carrier'], wanted)
    lines = []
    notes = []
    for kind, rows in kinds.items():
        if not rows:
            continue
        incoming_list = loaded[kind]
        if len(incoming_list) != len(rows):
            fail("中转文件里取回 %d 个 %s, 请求的是 %d 个"
                 % (len(incoming_list), kind, len(rows)))
        for row, incoming in zip(rows, incoming_list):
            users = replace(kind, row['source_name'], incoming)
            if row.get('materials') is not None:
                missing = apply_materials(incoming, row['materials'])
                if missing:
                    fail("%s 的材质槽在源里找不到 %s; 接上去会把源那几个槽清空, 已放弃写入 "
                         "(源文件一个字节都没动)。先把这些材质推/建到源里再来"
                         % (row['source_name'], ", ".join(missing)))
            expected = row.get('expect')
            if expected is not None:            # 只有网格有这几个数, 骨架/材质没有
                verify(row['source_name'], expected, mesh_facts(incoming, users))
            lines.append("%s/%s" % (kind, row['source_name']))

    bpy.context.preferences.filepaths.save_version = REQUIRED_SAVE_VERSION
    previous = bpy.data.filepath + str(REQUIRED_SAVE_VERSION)
    target = bpy.data.filepath
    bpy.ops.wm.save_mainfile()
    emit({
        'ok': True,
        'written': lines,
        'notes': notes,
        'archived': not os.path.exists(previous),
        'summary': "已写入 %s: %s" % (os.path.basename(target), ", ".join(lines)),
    })


try:
    main()
except SystemExit:
    raise
except Exception as error:      # noqa: BLE001 闸门抛出来的要原样传回去, 别只剩一截栈
    emit({'ok': False, 'error': "%s: %s" % (type(error).__name__, error)})
