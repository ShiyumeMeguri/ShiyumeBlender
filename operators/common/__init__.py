"""共用数据: 数据块链接到唯一源, 物体永远是本地的。

网格/材质/骨架挂到源文件上 (库覆盖), 几何跟着源走, 打开文件就是最新的 —— 没有"拉取"。
形态键的值、变换、修改器、顶点组、材质槽都是每个文件自己的。

要改就按 Tab: 覆盖态进不去编辑模式, takeover 在那一刻把数据块摘下来。改完推送, 推送把它
写回源、备份源的上一版、再把链接接回去。集合不参与 —— 集合管的是物体。
"""

import bpy

from . import ops
from . import panel
from . import takeover

classes = ops.classes + takeover.classes + panel.classes


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    takeover.register_keymap()


def unregister():
    takeover.unregister_keymap()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
