"""UV 重定向的唯一设置真源：挂在 Scene 上的属性组，算子与面板都只读它。"""

import bpy

from . import providers

_COLOR_SOURCE_ITEMS = providers.enum_items()


class SHIYUME_PG_UVTransfer(bpy.types.PropertyGroup):
    color_source: bpy.props.EnumProperty(
        name="颜色来源",
        items=_COLOR_SOURCE_ITEMS,
        default=_COLOR_SOURCE_ITEMS[0][0],
    )
    source_uv: bpy.props.StringProperty(
        name="源 UV",
        description="贴图当前所在的 UV 层（重定向的采样来源）",
    )
    target_uv: bpy.props.StringProperty(
        name="目标 UV",
        description="新的 UV 布局层（重定向的输出排布）",
    )
    resolution: bpy.props.EnumProperty(
        name="分辨率",
        items=[
            ('SOURCE', "跟随源图", "沿用每张源贴图自身的分辨率"),
            ('512', "512", ""),
            ('1024', "1024", ""),
            ('2048', "2048", ""),
            ('4096', "4096", ""),
            ('8192', "8192", ""),
        ],
        default='SOURCE',
    )
    supersample: bpy.props.EnumProperty(
        name="超采样",
        items=[
            ('1', "1x", "逐像素单点采样，边缘为硬边"),
            ('2', "2x", "每像素 4 个采样点"),
            ('4', "4x", "每像素 16 个采样点"),
        ],
        default='2',
        description="边缘抗锯齿倍率。RGB 只按几何覆盖加权平均，不会掺入背景色",
    )
    margin: bpy.props.IntProperty(
        name="外扩",
        default=16, min=0, max=256,
        description="把边缘颜色向 UV 岛外扩散的像素数，供 mipmap 与双线性过滤使用",
    )
    bake_type: bpy.props.EnumProperty(
        name="烘焙通道",
        items=[
            ('EMIT', "Emit (自发光)", "取着色器输出的颜色本身，不含光照"),
            ('DIFFUSE', "Diffuse (漫反射)", "只取漫反射颜色，不含直接/间接光"),
            ('COMBINED', "Combined (综合)", "取完整渲染结果，含光照"),
        ],
        default='EMIT',
    )
    bake_samples: bpy.props.IntProperty(
        name="烘焙采样",
        default=32, min=1, max=4096,
    )
    extension: bpy.props.EnumProperty(
        name="越界",
        items=[
            ('REPEAT', "重复", "源 UV 超出 0~1 时循环取样"),
            ('EXTEND', "延展", "源 UV 超出 0~1 时钳到边缘"),
        ],
        default='REPEAT',
    )
    apply_to_object: bpy.props.BoolProperty(
        name="应用到物体",
        default=True,
        description=(
            "完成后把新贴图接回材质，删除源 UV 层并把目标层改名为源层名"
            "（名字不变，所有按名绑定的节点自动继续生效）"
        ),
    )
    save_to_disk: bpy.props.BoolProperty(
        name="保存到磁盘",
        default=True,
    )
    output_dir: bpy.props.StringProperty(
        name="输出目录",
        subtype='DIR_PATH',
        default="//Textures/",
    )


def register():
    bpy.utils.register_class(SHIYUME_PG_UVTransfer)
    bpy.types.Scene.shiyume_uv_transfer = bpy.props.PointerProperty(
        type=SHIYUME_PG_UVTransfer
    )


def unregister():
    del bpy.types.Scene.shiyume_uv_transfer
    bpy.utils.unregister_class(SHIYUME_PG_UVTransfer)
