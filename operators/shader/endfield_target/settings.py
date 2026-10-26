"""头发分离法线贴图落点的共用设置：头发程序化生成与高光椭球烘焙写同一张贴图，目录、分辨率、变体、外扩只声明在这里。"""

import bpy

RESOLUTIONS = [
    ('1024', "1024", ""),
    ('2048', "2048", ""),
    ('4096', "4096", ""),
]


class SHIYUME_PG_EndfieldTarget(bpy.types.PropertyGroup):
    margin: bpy.props.IntProperty(
        name="外扩", default=8, min=0, max=64,
        description="把发片边缘的值向 UV 岛外扩散的像素数，供 mipmap 与双线性过滤使用；不会写到别的面占着的像素")
    output_dir: bpy.props.StringProperty(
        name="输出目录", subtype='DIR_PATH', default="//Textures/", options={'PATH_SUPPORTS_BLEND_RELATIVE'},
        description="生成的贴图存放的目录，相对 .blend")
    resolution: bpy.props.EnumProperty(
        name="新图分辨率", items=RESOLUTIONS, default='2048',
        description="没有模板图可拷、贴图又还不存在时新建的分辨率；已存在或有模板就沿用它们自己的")
    variant: bpy.props.StringProperty(
        name="变体名", default="",
        description="加在新材质与贴图名字里，一张头发材质可以并存好几套结果；留空是同一套反复覆盖")


def register():
    bpy.utils.register_class(SHIYUME_PG_EndfieldTarget)
    bpy.types.Scene.shiyume_endfield_target = bpy.props.PointerProperty(type=SHIYUME_PG_EndfieldTarget)


def unregister():
    del bpy.types.Scene.shiyume_endfield_target
    bpy.utils.unregister_class(SHIYUME_PG_EndfieldTarget)
