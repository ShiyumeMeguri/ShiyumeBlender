"""把展平网格的世界 XY 投影写回原物体的 UV 层。

「网格转UV」把 UV 变成可以用网格工具与修改器编辑的几何；这个算子是它的回程：
读取展平物体**求值后**的世界坐标（修改器已生效，比如用收缩包裹吸附到别处），
按正交顶视投影把 XY 当作 UV 写进原物体的目标 UV 层。

只要 UV，不要贴图时用它；要连贴图一起，直接用「生成重定向贴图」并勾上「应用到物体」。
"""

import bpy

from .uv_transfer import layout
from .uv_transfer.layout import SOURCE_OBJECT_PROP


class SHIYUME_OT_UVFromMesh(bpy.types.Operator):
    """把展平网格求值后的世界 XY 按正交顶视投影写回原物体的目标 UV 层"""

    bl_idname = "shiyume.uv_from_mesh"
    bl_label = "网格坐标写回UV"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        settings = context.scene.shiyume_uv_transfer
        layer_name = settings.target_uv
        if not layer_name:
            self.report({'ERROR'}, "请先在「UV 重定向」里填写目标 UV 的名字")
            return {'CANCELLED'}

        flattened = [obj for obj in context.selected_objects
                     if obj.type == 'MESH' and SOURCE_OBJECT_PROP in obj]
        if not flattened:
            self.report({'ERROR'}, "请选中「网格转UV」生成的展平物体")
            return {'CANCELLED'}

        written = 0
        for obj in flattened:
            if self._write_back(context, obj, layer_name):
                written += 1

        if written == 0:
            return {'CANCELLED'}

        self.report({'INFO'}, f"已写回 {written} 个物体的 '{layer_name}' UV 层")
        return {'FINISHED'}

    def _write_back(self, context, obj, layer_name):
        origin_name = obj[SOURCE_OBJECT_PROP]
        origin = bpy.data.objects.get(origin_name)
        if origin is None or origin.type != 'MESH':
            self.report({'ERROR'}, f"'{obj.name}' 的来源物体 '{origin_name}' 已不存在")
            return False

        settings = context.scene.shiyume_uv_transfer
        resolved = layout.resolve(context, obj, _WorldProjection(settings.source_uv))
        if resolved is None or resolved.base_loop_uv is None:
            self.report({'ERROR'},
                        f"'{obj.name}' 的修改器改变了拓扑，无法逐 loop 对应")
            return False

        if not layout.write_uv_layer(origin.data, layer_name, resolved.base_loop_uv):
            self.report(
                {'ERROR'},
                f"'{obj.name}' 有 {resolved.base_loop_uv.shape[0]} 个循环，"
                f"来源 '{origin_name}' 有 {len(origin.data.loops)} 个，对不上")
            return False
        return True


class _WorldProjection:
    """本算子恒定走世界投影，用最小的形状喂给 layout。"""

    target_space = 'MESH_XY'

    def __init__(self, source_uv):
        self.source_uv = source_uv
