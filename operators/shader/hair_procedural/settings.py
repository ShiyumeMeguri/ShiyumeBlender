"""头发预览与烘焙的界面设置：挂在 Scene 上的属性组。生成参数不在这里，在每个预览层的程序节点组实例上。"""

import bpy

from . import layers
from . import procedural

SHOW_NORMAL = "showNormal"


def _apply_show_normal(self, context):
    for material in layers.all_layers():
        generator = layers.generator_of(material)
        if generator is not None:
            procedural.set_parameter(generator, SHOW_NORMAL, self.show_normal)


class SHIYUME_PG_HairPreview(bpy.types.PropertyGroup):
    uv_layer: bpy.props.StringProperty(
        name="UV 层", default="",
        description="按哪层 UV 量发片、写贴图；留空用渲染激活的 UV 层")
    generate_color: bpy.props.BoolProperty(
        name="配套颜色", default=True,
        description="烘焙时同时写配套的 BaseMap 颜色，和法线一起挂到材质上；关掉只写法线")
    switch_viewport: bpy.props.BoolProperty(
        name="切换视口", default=True,
        description="开始预览时把当前 3D 视口切到材质预览（实体视图看不到预览材质），烘焙后切到实体 + Flat 光照 + 贴图颜色")
    random_color: bpy.props.BoolProperty(
        name="随机配色", default=True,
        description="点「随机种子」时发色也一起随机换一套（开了渐变发梢色就连发梢色），颜色取自参考头发的配色；关掉只换种子，颜色不动")
    show_normal: bpy.props.BoolProperty(
        name="预览法线", default=False, update=_apply_show_normal,
        description="全部预览层一起看漫反射法线的编码色（平坦处是淡蓝）；关掉看 BaseMap 颜色")


def register():
    bpy.utils.register_class(SHIYUME_PG_HairPreview)
    bpy.types.Scene.shiyume_hair_preview = bpy.props.PointerProperty(type=SHIYUME_PG_HairPreview)


def unregister():
    del bpy.types.Scene.shiyume_hair_preview
    bpy.utils.unregister_class(SHIYUME_PG_HairPreview)
