from ..tab import Tab


def draw(layout, context):
    if context.mode != 'OBJECT':
        layout.label(text="UV 重定向只在物体模式下可用", icon='INFO')
        return
    active = context.active_object
    if active is None or active.type != 'MESH':
        layout.label(text="请激活一个网格物体", icon='INFO')
        return
    settings = context.scene.shiyume_uv_transfer
    resample = settings.color_source == 'IMAGE'
    writes_existing = resample and settings.write_mode == 'EXISTING'

    flatten = layout.column(align=True)
    flatten.label(text="在网格上编辑 UV 布局")
    flatten.operator("shiyume.mesh_to_uv", icon="MESH_UVSPHERE", text="展平为网格")
    flatten.operator("shiyume.uv_from_mesh", icon="UV_SYNC_SELECT", text="网格坐标写回UV")

    arrangement = layout.box()
    arrangement.prop(settings, "target_space", text="")
    layers = arrangement.column(align=True)
    layers.prop_search(settings, "source_uv", active.data, "uv_layers", text="源 UV", icon='UV_DATA')
    target = layers.row(align=True)
    target.enabled = settings.target_space == 'UV_LAYER' or settings.apply_to_object
    target.prop_search(settings, "target_uv", active.data, "uv_layers",
                       text="目标 UV" if settings.target_space == 'UV_LAYER' else "投影写入", icon='UV_ISLANDSEL')
    arrangement.prop(settings, "color_source", expand=True)
    arrangement.prop(settings, "merge_material")
    if resample:
        arrangement.row().prop(settings, "write_mode", expand=True)

    quality = layout.box()
    column = quality.column(align=True)
    resolution = column.row(align=True)
    resolution.enabled = not writes_existing
    resolution.prop(settings, "resolution")
    column.prop(settings, "margin")
    if resample:
        column.prop(settings, "supersample")
        normals = quality.column(align=True)
        normals.prop(settings, "normal_labels")
        normals.prop(settings, "normal_convention", text="")
    else:
        column.prop(settings, "bake_type")
        column.prop(settings, "bake_samples")

    output = layout.box()
    output.prop(settings, "apply_to_object")
    saving = output.column(align=True)
    saving.prop(settings, "save_to_disk")
    directory = saving.column(align=True)
    directory.enabled = settings.save_to_disk and not writes_existing
    directory.prop(settings, "output_dir", text="")

    layout.operator("shiyume.uv_transfer", icon='TEXTURE')


TAB = Tab("uv_transfer", "重定向", "UV 重定向：源 UV 上的贴图 → 目标 UV 的排布", draw)
