import bpy
import cmath
import math


def _apply_deformation(c):
    real = c.real
    imag = c.imag
    imag += 0.15 - 0.3 * math.sin(0.43 * 0.1) + 0.2 * math.cos(real)
    if real > 0.0:
        real += 0.1 * real * math.cos(2.0 * 0.1 + math.sin(0.8 * real))
    return complex(real, imag)


def _mandelbrot_fish_stylized(c, max_iter):
    p = c
    if p.real < 3.968:
        if p == 0:
            return 0
        p = 1 / p
    else:
        p_real_shifted = c.real - 3.687
        tail_shape_check = 0.359 - 0.2 * cmath.cos(5.0 * c.imag).real
        distance_sq = p_real_shifted**2 + c.imag**2
        if tail_shape_check < distance_sq:
            return 0
        p = complex(p_real_shifted, c.imag)

    z = 0
    n = 0
    while abs(z) <= 22 and n < max_iter:
        z = z*z + p
        n += 1
    return n


class SHIYUME_OT_FractalFish(bpy.types.Operator):
    """基于曼德博集合(Mandelbrot)生成风格化的'逆鱼'生物网格。
    这是一个程序化生成工具，用于创建奇异的有机形态。"""
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

    def execute(self, context):
        width = self.width
        height = self.height
        max_iterations = self.max_iterations
        x_min = self.x_min
        x_max = self.x_max
        x_range = x_max - x_min
        y_range = x_range * (height / width)
        y_center = self.y_center
        y_min = y_center - (y_range / 2)
        y_max = y_center + (y_range / 2)
        mesh_size = self.mesh_size

        if "Fish_Fractal_Plane" in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects["Fish_Fractal_Plane"], do_unlink=True)
        if "Fish_Fractal_Plane_Mesh" in bpy.data.meshes:
            bpy.data.meshes.remove(bpy.data.meshes["Fish_Fractal_Plane_Mesh"])

        verts = []
        faces = []
        x_step = (x_max - x_min) / width
        y_step = (y_max - y_min) / height
        mesh_width = mesh_size
        mesh_height = mesh_size * (height / width)
        quad_width = mesh_width / width
        quad_height = mesh_height / height
        vert_index = 0

        for i in range(width):
            for j in range(height):
                c_original = complex(x_min + i * x_step, y_min + j * y_step)
                c_deformed = _apply_deformation(c_original)
                n = _mandelbrot_fish_stylized(c_deformed, max_iterations)

                if n > 0 and n < max_iterations:
                    x = (i / width - 0.5) * mesh_width
                    y = (j / height - 0.5) * mesh_height

                    v1 = (x, y, 0)
                    v2 = (x + quad_width, y, 0)
                    v3 = (x + quad_width, y + quad_height, 0)
                    v4 = (x, y + quad_height, 0)

                    verts.extend([v1, v2, v3, v4])
                    faces.append((vert_index, vert_index + 1, vert_index + 2, vert_index + 3))
                    vert_index += 4

        mesh_data = bpy.data.meshes.new("Fish_Fractal_Plane_Mesh")
        mesh_data.from_pydata(verts, [], faces)
        obj = bpy.data.objects.new("Fish_Fractal_Plane", mesh_data)
        context.collection.objects.link(obj)
        mesh_data.update()

        return {'FINISHED'}
