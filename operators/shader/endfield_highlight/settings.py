"""高光椭球的唯一设置真源：挂在 Scene 上的属性组，算子、会话与侧栏标签都只读它。"""

import bpy


def _is_mesh(self, obj):
    return obj.type == 'MESH'


class SHIYUME_PG_HighlightHair(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object)


class SHIYUME_PG_EndfieldHighlight(bpy.types.PropertyGroup):
    ellipsoid: bpy.props.PointerProperty(
        name="椭球", type=bpy.types.Object, poll=_is_mesh,
        description="高光法线的高模：头发每个点的高光法线取椭球上离它最近的点的法线")
    hair: bpy.props.CollectionProperty(type=SHIYUME_PG_HighlightHair)
    previewing: bpy.props.BoolProperty(
        name="实时预览", default=False,
        description="开着时，头发材质的高光法线实时取椭球的法线；烘焙、停止预览或椭球被删都会还原成贴图里的高光法线")
    switch_viewport: bpy.props.BoolProperty(
        name="切到材质预览", default=True,
        description="开始预览时把当前 3D 视口切到材质预览，实体视图看不到高光")


def register():
    bpy.utils.register_class(SHIYUME_PG_HighlightHair)
    bpy.utils.register_class(SHIYUME_PG_EndfieldHighlight)
    bpy.types.Scene.shiyume_endfield_highlight = bpy.props.PointerProperty(type=SHIYUME_PG_EndfieldHighlight)


def unregister():
    del bpy.types.Scene.shiyume_endfield_highlight
    bpy.utils.unregister_class(SHIYUME_PG_EndfieldHighlight)
    bpy.utils.unregister_class(SHIYUME_PG_HighlightHair)
