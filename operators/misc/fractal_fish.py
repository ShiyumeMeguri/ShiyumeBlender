import bpy

class SHIYUME_OT_FractalFish(bpy.types.Operator):
    """基于曼德博集合(Mandelbrot)生成风格化的'逆鱼'生物网格。
    这是一个程序化生成工具，用于创建奇异的有机形态。"""
    bl_idname = "shiyume.fractal_fish"
    bl_label = "生成分形鱼"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Implementation from 分形生物/逆鱼.py
        return {'FINISHED'}
