import bpy
import numpy

from . import _normal_map_bake as bake_common


class SHIYUME_OT_NormalMapToMesh(bpy.types.Operator):
    """法线贴图烘焙到网格（纯净覆写自定义法线）。

    先剥离现有自定义法线、强制全平滑得到纯净几何基准面，再按切线空间把材质里的
    法线贴图解算成物体空间法线，整体覆盖写入网格的自定义法线——结果 100% 由法线
    贴图接管。与“网格法线烘焙到贴图”互为逆操作。"""
    bl_idname = "shiyume.normal_map_to_mesh"
    bl_label = "法线贴图烘焙到网格"
    bl_options = {'REGISTER', 'UNDO'}

    flip_green: bpy.props.BoolProperty(
        name="翻转绿色通道",
        default=False,
        description="按 DirectX 约定翻转 Y 分量；关闭则用 OpenGL 约定（须与贴图一致）",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object

        material = obj.active_material
        if not material or not material.use_nodes:
            self.report({'ERROR'}, "没有激活的材质或未启用节点")
            return {'CANCELLED'}

        node = bake_common.find_normal_image_node(material)
        if not node or not node.image:
            self.report({'ERROR'}, "未在材质中找到法线贴图")
            return {'CANCELLED'}

        mesh = obj.data
        if mesh.uv_layers.active is None:
            self.report({'ERROR'}, "网格缺少 UV，无法解算切线空间")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        image = node.image
        width, height = image.size
        pixel_matrix = bake_common.read_image_pixels(image)

        # 剥离旧自定义法线并强制平滑，得到与“反向烘焙”完全一致的纯净基准面。
        bake_common.clear_custom_split_normals(context, obj)
        bake_common.force_all_smooth(mesh)

        normals, tangents, bitangents = bake_common.read_loop_tangent_basis(mesh)
        uvs = bake_common.read_loop_uvs(mesh)

        # 采样：UV → 像素行列（与反向烘焙共用同一取整约定）。
        column = numpy.clip((numpy.mod(uvs[:, 0], 1.0) * width).astype(numpy.int32), 0, width - 1)
        row = numpy.clip((numpy.mod(uvs[:, 1], 1.0) * height).astype(numpy.int32), 0, height - 1)
        sampled = pixel_matrix[row, column]

        # 解码切线空间法线（OpenGL；可选翻转绿色通道）。
        tangent_space = sampled[:, :3] * 2.0 - 1.0
        if self.flip_green:
            tangent_space[:, 1] = -tangent_space[:, 1]
        tangent_space = bake_common.normalize_rows(tangent_space)

        # 切线空间 → 物体空间：os = tx·T + ty·B + tz·N。
        object_space = (
            tangent_space[:, 0:1] * tangents
            + tangent_space[:, 1:2] * bitangents
            + tangent_space[:, 2:3] * normals
        )
        object_space = bake_common.normalize_rows(object_space)

        # 完全覆盖写入全新的自定义法线。
        mesh.normals_split_custom_set(object_space.tolist())
        mesh.update()

        self.report({'INFO'}, f"已从 {image.name} 覆写 {len(mesh.loops)} 条自定义法线")
        return {'FINISHED'}
