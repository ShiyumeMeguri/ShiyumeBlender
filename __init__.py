bl_info = {
    "name": "Shiyume Toolkit",
    "author": "ShiyumeMeguri",
    "version": (2, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (Shiyume) | 右键菜单 | UV 编辑器 | Shift+A > Mesh",
    "description": "通用建模 / 动画 / UV / 法线 / 烘焙工具库(Blender 4.x + 5.x,NumPy 批量加速)",
    "category": "Object",
}

from . import operators, ui


def register():
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()


if __name__ == "__main__":
    register()
