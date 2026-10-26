from ..tab import Tab


def draw(layout, context):
    selection = layout.box()
    selection.label(text="选择 / 布局")
    column = selection.column(align=True)
    column.operator("shiyume.aabb_select", icon="RESTRICT_SELECT_OFF")
    column.operator("shiyume.select_avg_size_half", icon="ZOOM_OUT")
    column.operator("shiyume.grid_sort", icon="GRID")

    topology = layout.box()
    topology.label(text="拓扑 / 剪切")
    column = topology.column(align=True)
    column.operator("shiyume.topology_cut", icon="MESH_GRID")
    column.operator("shiyume.lossless_mirror", icon="MOD_MIRROR")
    column.operator("shiyume.select_island_seam", icon="SELECT_SUBTRACT")

    weights = layout.box()
    weights.label(text="顶点组 / 权重")
    column = weights.column(align=True)
    column.operator("shiyume.cleanup_vgs", icon="GROUP_VERTEX")
    column.operator("shiyume.weight_prune", icon="WPAINT_HLT")
    column.operator("shiyume.smooth_weights_for_game", icon="MOD_SMOOTH")
    column.operator("shiyume.match_weights_active", icon="VERTEXSEL")
    column.operator("shiyume.swap_vertex_weights", icon="ARROW_LEFTRIGHT")
    column.operator("shiyume.copy_vertex_weights", icon="PASTEDOWN")
    column.operator("shiyume.vg_smooth_merge", icon="AUTOMERGE_ON")


TAB = Tab("mesh", "网格", "选择布局、拓扑剪切、顶点组与权重", draw)
