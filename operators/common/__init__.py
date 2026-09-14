"""共用角色数据: 不用库链接, 靠指针 + 按需推拉。"""

import bpy

from . import ops
from . import panel
from . import warn

classes = ops.classes + panel.classes + warn.classes


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    warn.register_handlers()


def unregister():
    warn.unregister_handlers()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
