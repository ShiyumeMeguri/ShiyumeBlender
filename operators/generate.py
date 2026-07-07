"""程序化生成:曼德博集合风格化"逆鱼"网格,迭代全程 NumPy 向量化。"""

import math

import bpy
import numpy as np


class SHIYUME_OT_FractalFish(bpy.types.Operator):
    """基于曼德博集合生成风格化的"逆鱼"生物网格。
    逃逸迭代整场向量化,768x768 网格亦即时完成"""
    bl_idname = "shiyume.fractal_fish"
    bl_label = "生成分形鱼"
    bl_options = {'REGISTER', 'UNDO'}

    width: bpy.props.IntProperty(name="网格宽度", default=768, min=32, max=4096)
    height: bpy.props.IntProperty(name="网格高度", default=768, min=32, max=4096)
    max_iterations: bpy.props.IntProperty(name="最大迭代次数", default=100, min=10, max=1000)
    x_min: bpy.props.FloatProperty(name="X 最小值", default=-5.0)
    x_max: bpy.props.FloatProperty(name="X 最大值", default=5.0)
    y_center: bpy.props.FloatProperty(name="Y 中心", default=0.0)
    mesh_size: bpy.props.FloatProperty(name="网格物理大小", default=10.0)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        column = layout.column(align=True)
        column.prop(self, "width")
        column.prop(self, "height")
        layout.prop(self, "max_iterations")
        column = layout.column(align=True)
        column.prop(self, "x_min")
        column.prop(self, "x_max")
        column.prop(self, "y_center")
        layout.prop(self, "mesh_size")

    def execute(self, context):
        width = self.width
        height = self.height
        max_iterations = self.max_iterations

        x_range = self.x_max - self.x_min
        y_range = x_range * (height / width)
        y_min = self.y_center - y_range / 2
        x_step = x_range / width
        y_step = y_range / height

        # ---- 采样格坐标 ----
        real = self.x_min + np.arange(width, dtype=np.float64)[:, None] * x_step      # (W, 1)
        imaginary = y_min + np.arange(height, dtype=np.float64)[None, :] * y_step     # (1, H)
        real, imaginary = np.broadcast_arrays(real, imaginary)
        real = real.copy()
        imaginary = imaginary.copy()

        # ---- 形变场 ----
        imaginary += 0.15 - 0.3 * math.sin(0.043) + 0.2 * np.cos(real)
        positive = real > 0.0
        real[positive] += 0.1 * real[positive] * np.cos(0.2 + np.sin(0.8 * real[positive]))

        # ---- 风格化分支:倒数区 / 尾部平移区 ----
        c = real + 1j * imaginary
        inverse_region = real < 3.968

        zero_cell = inverse_region & (c == 0)
        with np.errstate(divide='ignore', invalid='ignore'):
            inverse_c = np.where(c == 0, 0, 1.0 / c)

        shifted_real = real - 3.687
        tail_boundary = 0.359 - 0.2 * np.cos(5.0 * imaginary)
        tail_dead = (~inverse_region) & (tail_boundary < shifted_real ** 2 + imaginary ** 2)

        parameter = np.where(inverse_region, inverse_c, shifted_real + 1j * imaginary)

        # ---- 逃逸迭代(活跃掩码收缩) ----
        z = np.zeros_like(parameter)
        iterations = np.zeros((width, height), dtype=np.int32)
        active = ~(zero_cell | tail_dead)

        for _ in range(max_iterations):
            live = active & (np.abs(z) <= 22.0)
            if not live.any():
                break
            z = np.where(live, z * z + parameter, z)
            iterations += live
            active = live

        good = (iterations > 0) & (iterations < max_iterations)

        # ---- 命中格生成独立四边形 ----
        column_hits, row_hits = np.nonzero(good)
        quad_count = len(column_hits)
        if quad_count == 0:
            self.report({'WARNING'}, "参数下没有任何命中格")
            return {'CANCELLED'}

        mesh_width = self.mesh_size
        mesh_height = self.mesh_size * (height / width)
        quad_width = mesh_width / width
        quad_height = mesh_height / height

        x = (column_hits / width - 0.5) * mesh_width
        y = (row_hits / height - 0.5) * mesh_height

        vertices = np.zeros((quad_count, 4, 3), dtype=np.float64)
        vertices[:, 0, 0] = x
        vertices[:, 0, 1] = y
        vertices[:, 1, 0] = x + quad_width
        vertices[:, 1, 1] = y
        vertices[:, 2, 0] = x + quad_width
        vertices[:, 2, 1] = y + quad_height
        vertices[:, 3, 0] = x
        vertices[:, 3, 1] = y + quad_height
        faces = np.arange(quad_count * 4, dtype=np.int32).reshape(quad_count, 4)

        # ---- 替换旧结果并建网格 ----
        old_object = bpy.data.objects.get("Fish_Fractal_Plane")
        if old_object:
            bpy.data.objects.remove(old_object, do_unlink=True)
        old_mesh = bpy.data.meshes.get("Fish_Fractal_Plane_Mesh")
        if old_mesh:
            bpy.data.meshes.remove(old_mesh)

        mesh_data = bpy.data.meshes.new("Fish_Fractal_Plane_Mesh")
        mesh_data.from_pydata(vertices.reshape(-1, 3).tolist(), [], faces.tolist())
        mesh_data.update()

        obj = bpy.data.objects.new("Fish_Fractal_Plane", mesh_data)
        context.collection.objects.link(obj)

        self.report({'INFO'}, f"已生成 {quad_count} 个四边形")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_FractalFish,
)
