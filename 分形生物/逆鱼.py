import bpy
import cmath
import math

# --- 参数设置 (不变) ---
width = 768
height = 768
max_iterations = 100
x_min, x_max = -5.0, 5.0
x_range = x_max - x_min
y_range = x_range * (height / width)
y_center = 0.0
y_min = y_center - (y_range / 2)
y_max = y_center + (y_range / 2)
mesh_size = 10.0

# --- 变形函数 (不变) ---
def apply_deformation(c):
    real = c.real
    imag = c.imag
    imag += 0.15 - 0.3 * math.sin(0.43 * 0.1) + 0.2 * math.cos(real)
    if real > 0.0:
        real += 0.1 * real * math.cos(2.0 * 0.1 + math.sin(0.8 * real))
    return complex(real, imag)

# --- 风格化的鱼形分形函数 (不变，它已经是正确的) ---
def mandelbrot_fish_stylized(c, max_iter):
    p = c 
    if p.real < 3.968:
        if p == 0: return 0
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

# --- 创建网格的函数 ---
def create_fish_fractal_plane():
    # 清理旧对象 (不变)
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
            c_deformed = apply_deformation(c_original)
            n = mandelbrot_fish_stylized(c_deformed, max_iterations)
            
            # --- 核心最终修正：使用统一的、正确的判断逻辑 ---
            # 我们只为那些“真正”进行了迭代(n>0)并且在结束前“逃逸”(n<max_iter)的点创建面。
            # 这条判断同时正确地处理了鱼身和带分形边缘的鱼尾。
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

    # 创建网格和对象 (不变)
    mesh_data = bpy.data.meshes.new("Fish_Fractal_Plane_Mesh")
    mesh_data.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new("Fish_Fractal_Plane", mesh_data)
    bpy.context.collection.objects.link(obj)
    mesh_data.update()

# --- 运行脚本 ---
create_fish_fractal_plane()

print("已统一判断逻辑，鱼尾现在应带有正确的分形边缘！")