"""侧栏的界面状态：当前停在哪个标签（挂在 WindowManager 上的枚举，选项就是标签注册表本身），以及各标签自带的界面状态属性。"""

import bpy

from .tabs import TABS

PROPERTY = "shiyume_sidebar_tab"


def register():
    setattr(bpy.types.WindowManager, PROPERTY, bpy.props.EnumProperty(
        name="Shiyume 标签",
        items=[(tab.key, tab.label, tab.description) for tab in TABS],
        default=TABS[0].key,
    ))
    for tab in TABS:
        for name, definition in tab.properties:
            setattr(bpy.types.WindowManager, name, definition)


def unregister():
    for tab in TABS:
        for name, _definition in tab.properties:
            delattr(bpy.types.WindowManager, name)
    delattr(bpy.types.WindowManager, PROPERTY)
