"""描边平滑法线烘焙的唯一设置真源：挂在 Scene 上的属性组，算子与侧栏标签都只读它。"""

import bpy

SOURCES = (
    ('FACES', "面法线（游戏算法）", "同一位置各面的几何法线按所在角的夹角加权求和，与游戏烘焙进 UV2 的平滑法线一致；忽略自定义法线和平滑标记"),
    ('ATTRIBUTE', "已有属性", "取网格上现成的向量属性（物体空间的单位向量）当平滑法线，例如手工做好的 smoothnormalWS"),
    ('PROXY', "代理物体", "取代理网格上离每个角最近的点的平滑法线：复制一份网格，随便雕它或改它的法线，当高模来烘焙"),
)


def _is_mesh(self, obj):
    return obj.type == 'MESH'


class SHIYUME_PG_OutlineReport(bpy.types.PropertyGroup):
    text: bpy.props.StringProperty()


class SHIYUME_PG_EndfieldOutline(bpy.types.PropertyGroup):
    source: bpy.props.EnumProperty(name="平滑法线来源", items=SOURCES, default='FACES')
    attribute: bpy.props.StringProperty(name="属性名", default="smoothnormalWS",
                                        description="来源是已有属性时读它：角域或点域的向量，物体空间")
    proxy: bpy.props.PointerProperty(name="代理物体", type=bpy.types.Object, poll=_is_mesh,
                                     description="来源是代理物体时，每个角取它表面上离自己最近的点的平滑法线")
    weld_distance: bpy.props.FloatProperty(name="焊接距离", default=1e-5, min=0.0, soft_max=1e-3, precision=6, unit='LENGTH',
                                           description="面法线求和时，距离不超过它的顶点算同一个位置；0 = 只按顶点下标")
    layer: bpy.props.StringProperty(name="写入的 UV 层", default="UV2",
                                    description="平滑法线的切线空间 XY 写进这一层（没有就新建）；游戏的描边读的是 UV2")
    report: bpy.props.CollectionProperty(type=SHIYUME_PG_OutlineReport)


def register():
    bpy.utils.register_class(SHIYUME_PG_OutlineReport)
    bpy.utils.register_class(SHIYUME_PG_EndfieldOutline)
    bpy.types.Scene.shiyume_endfield_outline = bpy.props.PointerProperty(type=SHIYUME_PG_EndfieldOutline)


def unregister():
    del bpy.types.Scene.shiyume_endfield_outline
    bpy.utils.unregister_class(SHIYUME_PG_EndfieldOutline)
    bpy.utils.unregister_class(SHIYUME_PG_OutlineReport)
