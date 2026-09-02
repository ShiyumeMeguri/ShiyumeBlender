"""后台 Blender 执行体: 把网格数据写进共用文件并保存。

由 common_sync.SHIYUME_OT_CommonPush 以
    blender -b <共用文件> --python common_sync_worker.py -- <payload json>
启动。**不导入插件**, 只用 bpy —— 它跑在一个干净的后台进程里。

结果以一行 `@SHIYUMESYNC {json}` 回传, 调用方只解析这一行。
"""

import json
import os
import sys

import bpy

MARKER = "@SHIYUMESYNC "


def emit(payload):
    print(MARKER + json.dumps(payload, ensure_ascii=False))


def fail(message):
    emit({'ok': False, 'error': message})
    sys.exit(0)


def main():
    try:
        payload = json.loads(sys.argv[sys.argv.index('--') + 1])
    except (ValueError, IndexError) as exc:
        fail("payload 解析失败: %s" % exc)

    target_name = payload['target_mesh']
    carrier = payload['carrier']
    carrier_mesh = payload['carrier_mesh']
    wanted_groups = payload['vertex_groups']
    notes = []

    old = bpy.data.meshes.get(target_name)
    if old is None:
        fail("共用文件里没有网格数据块 %r; 现有: %s"
             % (target_name, sorted(m.name for m in bpy.data.meshes)[:20]))

    users = [o for o in bpy.data.objects if o.type == 'MESH' and o.data is old]
    if not users:
        fail("共用文件里没有物体在用 %r, 拒绝写入 (先确认要更新的是哪一个)" % target_name)

    # 目的地的形态键"值"是这个文件自己的体型设定, 推送不该动它
    keep_values = ({k.name: (k.value, k.mute) for k in old.shape_keys.key_blocks}
                   if old.shape_keys else {})

    before_libs = {lib.name_full for lib in bpy.data.libraries}
    with bpy.data.libraries.load(carrier, link=False) as (src, dst):
        if carrier_mesh not in src.meshes:
            fail("中转文件里没有 %r; 现有 %s" % (carrier_mesh, sorted(src.meshes)))
        dst.meshes = [carrier_mesh]
    incoming = dst.meshes[0]
    # 中转文件事后会被删掉, 绝不能把指向它的库记录留在共用文件里
    for lib in list(bpy.data.libraries):
        if lib.name_full not in before_libs and not lib.users_id:
            bpy.data.libraries.remove(lib)

    before_verts = len(old.vertices)
    for obj in users:
        obj.data = incoming
        # 权重存的是组下标, 名表必须跟着一起过来, 否则静默错位
        current = [g.name for g in obj.vertex_groups]
        if current != wanted_groups:
            for group in list(obj.vertex_groups):
                obj.vertex_groups.remove(group)
            for name in wanted_groups:
                obj.vertex_groups.new(name=name)
            notes.append("%s 的顶点组名表已按来源重建 (%d -> %d)"
                         % (obj.name, len(current), len(wanted_groups)))

    if incoming.shape_keys:
        restored = 0
        for block in incoming.shape_keys.key_blocks:
            if block.name in keep_values:
                block.value, block.mute = keep_values[block.name]
                restored += 1
            else:
                notes.append("新形态键 %s (共用文件里原本没有, 用推送方的值)" % block.name)
        for name in keep_values:
            if name not in incoming.shape_keys.key_blocks:
                notes.append("形态键 %s 在推送方已不存在, 共用文件里也随之消失" % name)
    else:
        restored = 0
        if keep_values:
            notes.append("推送方没有形态键, 共用文件原有的 %d 个随之消失" % len(keep_values))

    name = old.name
    old.use_fake_user = False
    if old.users == 0:
        bpy.data.meshes.remove(old)
    incoming.name = name

    bpy.ops.wm.save_mainfile()
    emit({
        'ok': True,
        'notes': notes,
        'summary': "已写入 %s：%s 顶点 %d -> %d，更新了 %d 个物体，保留 %d 个形态键值"
                   % (os.path.basename(bpy.data.filepath), name, before_verts,
                      len(incoming.vertices), len(users), restored),
    })


main()
