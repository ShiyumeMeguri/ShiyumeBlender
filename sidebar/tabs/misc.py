from ..tab import Tab


def draw(layout, context):
    column = layout.column(align=True)
    column.operator("shiyume.clear_empty", icon="X")
    column.operator("shiyume.sort_roots_x", icon="SORTSIZE")


TAB = Tab("misc", "杂项", "清理空物体、按 X 排序根物体", draw)
