"""EndField 着色器专属工具。

只放与 EndField 材质约定强绑定的功能;通用机制(如 UV 法线压缩)一律进对应通用分类。
新增 EndField 专属算子:写在本文件 + 登记 classes,再到 ui.py 的 endfield 分类表加一行。
"""

import bpy

from ..core import smooth_normals


class SHIYUME_OT_EndFieldHairDualNormal(bpy.types.Operator):
    """EndField 头发双法线(头发专用):在几何法线之外烘焙第二套法线 ——
    按空间位置聚合的平滑法线,切线空间八面体编码写入 UV2,
    供 EndField 头发 shader 采样,高光与描边不随发片硬边/接缝断裂"""
    bl_idname = "shiyume.endfield_hair_dual_normal"
    bl_label = "EndField 头发双法线"
    bl_options = {'REGISTER', 'UNDO'}

    uv_layer_name: bpy.props.StringProperty(
        name="UV 层名", default="UV2",
        description="双法线写入的 UV 层(EndField 头发 shader 约定 UV2),不存在则新建",
    )
    weight_mode: bpy.props.EnumProperty(
        name="加权方式",
        items=[
            ('ANGLE', "角度加权", "按每个角的张角加权平均(几何正确,推荐)"),
            ('UNIFORM', "算术平均", "所有角等权平均"),
        ],
        default='ANGLE',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "uv_layer_name")
        layout.prop(self, "weight_mode")

    def execute(self, context):
        processed = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH' or len(obj.data.loops) == 0:
                continue
            mesh = obj.data

            smoothed = smooth_normals.smoothed_corner_normals(mesh, self.weight_mode)
            error = smooth_normals.pack_octahedral_into_uv(mesh, smoothed, self.uv_layer_name)
            if error is not None:
                self.report({'WARNING'}, f"'{obj.name}' {error},跳过")
                continue
            processed += 1

        if processed == 0:
            return {'CANCELLED'}
        self.report({'INFO'}, f"已烘焙 {processed} 个网格的头发双法线到 UV '{self.uv_layer_name}'")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_EndFieldHairDualNormal,
)
