from collections import namedtuple

import bpy

from ...operators.shader.hair_procedural import layers
from ..tab import Tab

SECTION = "shiyume_endfield_section"
Section = namedtuple("Section", ("key", "label", "description", "draw", "writes_textures"))


def _draw_hair(layout, context):
    options = context.scene.shiyume_hair_preview
    obj = context.active_object
    editable = obj is not None and obj.type == 'MESH'
    if not layers.all_layers():
        layout.operator("shiyume.hair_preview_start", icon="NORMALS_FACE")
        layout.label(text="选中头发物体后开始预览，参数调好再烘焙", icon="INFO")
    else:
        row = layout.row(align=True)
        row.operator("shiyume.hair_preview_local", icon="FACESEL")
        row.operator("shiyume.hair_preview_drop_local", text="", icon="X")
        if editable and any(layers.is_layer(slot.material) for slot in obj.material_slots):
            layout.template_list("MATERIAL_UL_matslots", "", obj, "material_slots", obj, "active_material_index", rows=3)
        active = layers.active_layer(context)
        if active is None:
            layout.label(text="在材质槽里选一个预览层来调参数", icon="INFO")
        elif layers.generator_of(active) is None:
            layout.label(text="这一层是别的版本做的，取消预览后重新开始", icon="ERROR")
        else:
            users = layers.preview_group(active).users
            if not layers.is_local(active) and users > 1:
                layout.label(text="%d 张材质的基础层共用这一套参数" % users, icon="LINKED")
            row = layout.row(align=True)
            row.operator("shiyume.hair_preview_random_seed", icon="FILE_REFRESH")
            row.prop(options, "random_color", toggle=True, icon="COLOR")
            layout.template_node_inputs(layers.generator_of(active))
        layout.prop(options, "show_normal", toggle=True)
        layout.operator("shiyume.hair_preview_refresh", icon="FILE_REFRESH")
        layout.operator("shiyume.hair_preview_bake", icon="RENDER_STILL")
        layout.operator("shiyume.hair_preview_cancel", icon="CANCEL")
    if editable:
        layout.prop_search(options, "uv_layer", obj.data, "uv_layers")
    layout.prop(options, "generate_color")
    layout.prop(options, "switch_viewport")


def _draw_highlight(layout, context):
    options = context.scene.shiyume_endfield_highlight

    layout.operator("shiyume.endfield_highlight_create", text="重置椭球到估算位置" if options.ellipsoid is not None else "创建高光椭球并预览",
                    icon="MESH_UVSPHERE")
    layout.prop(options, "ellipsoid")
    if options.ellipsoid is None:
        layout.label(text="选中带导入器头发材质的物体后创建", icon="INFO")
        return
    if options.previewing:
        layout.operator("shiyume.endfield_highlight_stop", icon="PAUSE")
    else:
        layout.operator("shiyume.endfield_highlight_preview", icon="PLAY")
    layout.prop(options, "switch_viewport")
    layout.label(text="预览的头发：%d 个物体" % sum(1 for entry in options.hair if entry.obj is not None), icon="STRANDS")
    layout.operator("shiyume.endfield_highlight_bake", icon="RENDER_STILL")


def _draw_outline(layout, context):
    options = context.scene.shiyume_endfield_outline
    layout.label(text="选中要描边的网格物体后烘焙", icon="INFO")
    layout.prop(options, "source")
    if options.source == 'ATTRIBUTE':
        layout.prop(options, "attribute")
    elif options.source == 'PROXY':
        layout.prop(options, "proxy")
    else:
        layout.prop(options, "weld_distance")
    layout.prop(options, "layer")
    layout.operator("shiyume.endfield_outline_bake", icon="NORMALS_VERTEX")
    row = layout.row(align=True)
    row.operator("shiyume.endfield_outline_verify", icon="CHECKMARK")
    row.operator("shiyume.endfield_outline_clear", icon="TRASH")
    for entry in options.report:
        layout.label(text=entry.text)


SECTIONS = (
    Section("HAIR", "头发生成", "按发片 UV 程序化生成头发的法线与颜色：实时预览调参数，编辑模式选面做局部层，最后烘焙", _draw_hair, True),
    Section("HIGHLIGHT", "高光椭球", "椭球当高模烘焙头发的高光法线，实时预览；只写分离法线贴图的 B、A 通道", _draw_highlight, True),
    Section("OUTLINE", "描边法线", "把平滑法线按每个角的切线框烘焙进 UV2，游戏的反壳描边按它外扩；不写贴图", _draw_outline, False),
)
SECTIONS_BY_KEY = {section.key: section for section in SECTIONS}


def _draw_target(layout, context):
    options = context.scene.shiyume_endfield_target
    layout.label(text="输出（贴图落点）")
    layout.prop(options, "margin")
    layout.prop(options, "output_dir")
    layout.prop(options, "resolution")
    layout.prop(options, "variant")


def draw(layout, context):
    layout.prop(context.window_manager, SECTION, text="")
    section = SECTIONS_BY_KEY[getattr(context.window_manager, SECTION)]
    section.draw(layout, context)
    if section.writes_textures:
        _draw_target(layout.box(), context)


PROPERTIES = (
    (SECTION, bpy.props.EnumProperty(
        name="EndField 功能", items=[(section.key, section.label, section.description) for section in SECTIONS], default=SECTIONS[0].key)),
)

TAB = Tab("endfield", "EndField", "头发的程序化法线与颜色、高光椭球烘焙高光法线，两者写同一张分离法线贴图；描边法线烘焙进网格的 UV2", draw, PROPERTIES)
