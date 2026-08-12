"""把展平网格的顶点坐标写回原物体的 UV 层。

「网格转UV」把 UV 变成可以用网格工具与修改器编辑的几何；这个算子是它的回程：
读取展平物体的**求值后**坐标（修改器已生效，比如用收缩包裹吸附到另一张 UV 上），
把 XY 当作 UV 写进原物体的目标 UV 层。之后即可用「生成重定向贴图」出图。
"""

import bpy
import numpy as np

from .mesh_to_uv import SOURCE_OBJECT_PROP


class SHIYUME_OT_UVFromMesh(bpy.types.Operator):
    """把展平网格求值后的 XY 坐标写回原物体的目标 UV 层"""

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

        depsgraph = context.evaluated_depsgraph_get()
        written = 0
        for obj in flattened:
            if self._write_back(context, depsgraph, obj, layer_name):
                written += 1

        if written == 0:
            return {'CANCELLED'}

        self.report({'INFO'}, f"已写回 {written} 个物体的 '{layer_name}' UV 层")
        return {'FINISHED'}

    def _write_back(self, context, depsgraph, obj, layer_name):
        source_name = obj[SOURCE_OBJECT_PROP]
        source_obj = bpy.data.objects.get(source_name)
        if source_obj is None or source_obj.type != 'MESH':
            self.report({'ERROR'}, f"'{obj.name}' 的来源物体 '{source_name}' 已不存在")
            return False

        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            source_mesh = source_obj.data
            if len(mesh.loops) != len(source_mesh.loops):
                self.report(
                    {'ERROR'},
                    f"'{obj.name}' 求值后有 {len(mesh.loops)} 个循环，"
                    f"来源 '{source_name}' 有 {len(source_mesh.loops)} 个——"
                    f"修改器改变了拓扑，无法逐循环对应")
                return False

            positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", positions)
            positions = positions.reshape(-1, 3)

            loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
            mesh.loops.foreach_get("vertex_index", loop_vertices)
            uv = positions[loop_vertices, 0:2]
        finally:
            evaluated.to_mesh_clear()

        layer = source_mesh.uv_layers.get(layer_name)
        if layer is None:
            layer = source_mesh.uv_layers.new(name=layer_name, do_init=False)
        source_mesh.attributes[layer.name].data.foreach_set(
            "vector", np.ascontiguousarray(uv, dtype=np.float32).reshape(-1))
        source_mesh.update()
        return True
