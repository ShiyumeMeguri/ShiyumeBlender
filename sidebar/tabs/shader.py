from ..tab import Tab


def draw(layout, context):
    layout.operator("shiyume.normal_expansion", icon="MOD_NORMALEDIT")
    bake = layout.box()
    bake.label(text="法线贴图烘焙")
    column = bake.column(align=True)
    column.operator("shiyume.normal_map_to_mesh", icon="IMPORT")
    column.operator("shiyume.mesh_to_normal_map", icon="EXPORT")
    layout.operator("shiyume.vertex_color_rgba", icon="VPAINT_HLT")


TAB = Tab("shader", "着色", "法线外扩、法线贴图烘焙、顶点色", draw)
