from ..tab import Tab


def draw(layout, context):
    column = layout.column(align=True)
    column.operator("shiyume.curve_smooth_fix", icon="CURVE_DATA")
    column.operator("shiyume.hair_to_path", icon="OUTLINER_OB_CURVES")
    column.operator("shiyume.hair_curve_bind", icon="CONSTRAINT")
    column.operator("shiyume.hair_curve_retarget", icon="CURVE_DATA")


TAB = Tab("curve", "曲线", "曲线平滑修复与头发曲线绑定", draw)
