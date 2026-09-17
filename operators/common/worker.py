"""后台执行体: 在共用文件里落地一批推送, 然后保存一次。

由 ops.py 以
    blender -b <共用文件> --python worker.py -- <payload.json 路径>
启动。跑在一个干净的后台进程里, **不加载插件** —— 只按文件路径 import 两个纯数据
模块 (mesh_data / rig_data), 好让"怎么合并"这件事只有一份实现, 拉取和推送共用。

一次调用处理一整个角色 (骨架 + 全部子网格), 全部落地后只存一次盘。

结果以一行 `@SHIYUMESYNC {json}` 回传, 调用方只解析这一行。
"""

import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_data                                                  # noqa: E402
import rig_data                                                   # noqa: E402

MARKER = "@SHIYUMESYNC "


def emit(payload):
    print(MARKER + json.dumps(payload, ensure_ascii=False))


def fail(message):
    emit({'ok': False, 'error': message})
    sys.exit(0)


def take(carrier, names, material_names):
    """把中转文件里的网格数据块 append 进来, 按请求顺序返回。

    用 `dst.meshes` 而不是去 diff bpy.data.meshes: 出了 with 块它就是真正的数据块
    列表, 顺序与请求一致 —— append 会给重名的加 `.001` 后缀, 按名字回查会对错人。

    material_names 是挂在物体上 ('OBJECT' 那一路) 的材质 —— 它们不是网格的依赖, 不点名
    就带不进来。网格自己的材质 / 贴图 / 节点组是依赖, 跟着网格自动进来。
    """
    before_libs = {lib.name_full for lib in bpy.data.libraries}
    with bpy.data.libraries.load(carrier, link=False) as (src, dst):
        missing = [n for n in names if n not in src.meshes]
        if missing:
            fail("中转文件里没有网格 %s; 现有 %s" % (missing, sorted(src.meshes)[:20]))
        missing_materials = [n for n in material_names if n not in src.materials]
        if missing_materials:
            fail("中转文件里没有材质 %s; 现有 %s"
                 % (missing_materials, sorted(src.materials)[:20]))
        dst.meshes = list(names)
        dst.materials = list(material_names)
    loaded = list(dst.meshes)
    # 中转文件事后会被删掉, 绝不能把指向它的库记录留在共用文件里
    for lib in list(bpy.data.libraries):
        if lib.name_full not in before_libs and not lib.users_id:
            bpy.data.libraries.remove(lib)
    return loaded


def main():
    try:
        with open(sys.argv[sys.argv.index('--') + 1], encoding='utf-8') as handle:
            payload = json.load(handle)
    except (ValueError, IndexError, OSError) as exc:
        fail("payload 读取失败: %s" % exc)

    notes = []
    lines = []

    meshes = payload.get('meshes', [])
    rigs = payload.get('rigs', [])
    wanted = [row['carrier_mesh'] for row in meshes]
    if wanted:
        known = mesh_data.known_names()      # append 之前的名录, 用来认出带进来的那几份
        loaded = take(payload['carrier'], wanted, payload.get('object_materials', []))
        if len(loaded) != len(meshes):
            fail("中转文件里取回 %d 个网格, 请求的是 %d 个" % (len(loaded), len(meshes)))
        # 材质 / 贴图 / 节点组都是新造的一份, 先让它们接管共用文件里同名的那份: 共用文件里
        # 原来用着这份材质的东西 (没在这次推送里的网格也算) 跟着一起更新, 名字也不会漂
        adopted, adopt_notes = mesh_data.adopt_appended(known)
        notes.extend(adopt_notes)
        if adopted:
            lines.append("按名覆盖 %d 份材质/贴图/节点组: %s"
                         % (len(adopted), ', '.join(adopted)))
        # 贴图路径必须按工作文件那边的原样写回: append 会拿中转文件 (在临时目录里) 当基准
        # 把相对路径重算一遍, 算出来指向临时目录, 共用文件里就是一片紫
        changed, path_notes = mesh_data.apply_image_paths(payload.get('images', {}))
        notes.extend(path_notes)
        if changed:
            lines.append("贴图路径按工作文件写回 %d 张" % changed)
        for row, incoming in zip(meshes, loaded):
            target = bpy.data.objects.get(row['target_obj'])
            if target is None or target.type != 'MESH':
                fail("共用文件里没有网格物体 %r" % row['target_obj'])
            summary, extra = mesh_data.swap_mesh(target, incoming, row['vertex_groups'],
                                                 row.get('weighted'), row.get('slots'))
            lines.append(summary)
            notes.extend("%s: %s" % (row['target_obj'], n) for n in extra)

    for row in rigs:
        target = bpy.data.objects.get(row['target_obj'])
        if target is None or target.type != 'ARMATURE':
            fail("共用文件里没有骨架物体 %r" % row['target_obj'])
        lines.append("%s: %s" % (row['target_obj'], rig_data.apply(target, row['snapshot'])))

    if not lines:
        fail("没有任何要推送的内容")

    bpy.ops.wm.save_mainfile()
    emit({
        'ok': True,
        'notes': notes,
        'summary': "已写入 %s: %s" % (os.path.basename(bpy.data.filepath), "; ".join(lines)),
    })


main()
