"""把侧栏标签里的工具插进 RuriRipperImporter 生成的材质面板，放在它们写的那些参数旁边。

插入点是导入器材质布局数据里的槽位，注册表是它的 material panel slots 拓展点：这里只往里登记 draw(layout, context, slot)，
导入器不知道这里有什么，没装导入器就什么也不登记。登记推迟到启动脚本跑完之后，两个插件谁先加载都一样。
"""

import bpy

from ..operators.shader.endfield_target import importer
from .tabs import PLACEMENTS

_attached = []


def _attach():
    host = importer.panel()
    if host is None:
        return None
    for placement in PLACEMENTS:
        host.register_slot(placement.slot, placement.key, placement.draw, placement.title)
        _attached.append(placement)
    return None


def register():
    bpy.app.timers.register(_attach, first_interval=0.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_attach):
        bpy.app.timers.unregister(_attach)
    host = importer.panel()
    if host is not None:
        for placement in _attached:
            host.drop_slot(placement.slot, placement.key)
    _attached.clear()
