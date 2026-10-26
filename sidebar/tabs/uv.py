from ..tab import Tab


def draw(layout, context):
    column = layout.column(align=True)
    column.operator("shiyume.uv_pack_lock_group", icon="PACKAGE")
    column.operator("shiyume.mesh_uv_sync", icon="UV_DATA")
    column.operator("shiyume.mesh_uv_sync_live", icon="UV_SYNC_SELECT")
    column.operator("shiyume.mesh_uv_sync_live_disable", icon="X")
    column.operator("shiyume.mesh_to_uv", icon="MESH_UVSPHERE")
    column.operator("shiyume.uv_from_mesh", icon="UV_SYNC_SELECT")
    column.operator("shiyume.uv_island_equidistant", icon="ALIGN_CENTER")
    column.operator("shiyume.uv_island_sort_height", icon="SORTSIZE")
    column.operator("shiyume.hair_uv_unwrap", icon="UV_DATA")
    column.operator("shiyume.uv_relax_locked", icon="MOD_SMOOTH")
    column.operator("shiyume.uv_cut", icon="MOD_ARRAY")


TAB = Tab("uv", "UV", "UV 打包、同步、孤岛排布与切割", draw)
