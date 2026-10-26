"""侧栏的一个标签：key 是枚举项标识，draw(layout, context) 画它的正文，properties 是这个标签要挂在 WindowManager 上的界面状态属性。"""

from collections import namedtuple

Tab = namedtuple("Tab", ("key", "label", "description", "draw", "properties"), defaults=((),))
