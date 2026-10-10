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
    target_space: bpy.props.EnumProperty(
        name="目标排布",
        items=[
            ('MESH_XY', "展平网格（世界投影）",
             "取展平网格求值后的世界 XY —— 等价于 ortho_scale=1、对准 (0.5, 0.5) 的"
             "正交顶视相机。改网格就是改排布，修改器与形态键都算数"),
            ('UV_LAYER', "目标 UV 层", "直接用另一个 UV 层作为新排布"),
        ],
        default='UV_LAYER',
    )
    source_uv: bpy.props.StringProperty(
        name="源 UV",
        description="贴图当前所在的 UV 层（重定向的采样来源）",
    )
    target_uv: bpy.props.StringProperty(
        name="目标 UV",
        description="新排布所在的 UV 层；世界投影模式下用来接住投影结果",
    )
    resolution: bpy.props.EnumProperty(
        name="分辨率",
        items=[
            ('SOURCE', "跟随源图", "沿用源贴图的分辨率；合并时取参与合成的最大一张。写入现有贴图时恒为目标图尺寸"),
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
            ('1', "1x", "每像素在中心取一次双线性：孤岛只平移时逐位不变，缩放旋转时最锐"),
            ('2', "2x", "每像素 4 个采样点平均：孤岛缩小较多时抗锯齿"),
            ('4', "4x", "每像素 16 个采样点平均：孤岛缩小很多时抗锯齿"),
        ],
        default='1',
        description="每像素采样数。多点是盒式平均，会让没缩小的孤岛也略微变糊；四个通道都只按几何覆盖平均，不会掺入背景",
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
    merge_material: bpy.props.PointerProperty(
        name="合并到材质",
        type=bpy.types.Material,
        description=(
            "留空：各面材质不变，每张源图各出一张。指定：选中网格的全部面改用这张材质，"
            "它每个经源 UV 采样的贴图节点按节点标签，从各面原材质里同标签的节点取色合成一张"
        ),
    )
    write_mode: bpy.props.EnumProperty(
        name="写入",
        items=[
            ('NEW', "新建贴图", "输出到新的图像数据块（自动编号，不覆盖已有数据块与文件）"),
            ('EXISTING', "写入现有贴图",
             "直接画进目标贴图并存回原文件：只写本次网格新排布覆盖的像素与就近外扩，"
             "文件里其他网格经 UV 用到的像素原样保留"),
        ],
        default='NEW',
    )
    normal_labels: bpy.props.StringProperty(
        name="切线法线",
        description=(
            "哪些贴图节点是切线空间法线贴图（按节点标签，逗号分隔）：孤岛旋转/镜像时法线 XY 跟着转。"
            "直接接「法线贴图」节点（切线空间）的自动识别"
        ),
    )
    normal_convention: bpy.props.EnumProperty(
        name="法线约定",
        items=[
            ('OPENGL', "OpenGL（Y+）", "绿通道朝 +V（Blender、Unity）"),
            ('DIRECTX', "DirectX（Y-）", "绿通道朝 -V"),
        ],
        default='OPENGL',
        description="按标签指定的切线法线贴图的绿通道朝向",
    )
    apply_to_object: bpy.props.BoolProperty(
        name="应用到物体",
        default=True,
        description=(
            "完成后把新贴图接回材质（合并时全部面改用目标材质），并对调两个 UV 层的数据："
            "源层拿到新布局、目标层接住旧布局。两层都保留，再执行一次即可换回"
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
