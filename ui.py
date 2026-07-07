"""界面:全部由分类表驱动。

一个分类 = 右键菜单里的一个子菜单 + 侧栏里的一个子面板,共用同一份条目表;
新增分类(如新的 shader 专属家族)只需在 _CATEGORIES 加一行。
shader 专属功能按引擎/着色器立独立分类(如 EndField),通用功能进通用分类。
"""

import bpy


# ---------------------------------------------------------------------------
# 分类表
# ---------------------------------------------------------------------------

class _ToolCategory:
    """key 生成菜单/面板 idname;modes 控制右键菜单在哪些模式下出现;
    items 为 (bl_idname, 图标) 序列,None 表示分隔线。"""

    __slots__ = ("key", "label", "icon", "modes", "items")

    def __init__(self, key, label, icon, modes, items):
        self.key = key
        self.label = label
        self.icon = icon
        self.modes = modes
        self.items = items


_CATEGORIES = (
    _ToolCategory("animation", "动画", 'ARMATURE_DATA', {'POSE'}, (
        ("shiyume.clean_animation", 'BRUSH_DATA'),
        ("shiyume.offset_keyframes", 'ACTION'),
    )),
    _ToolCategory("object", "物体", 'OBJECT_DATA', {'OBJECT'}, (
        ("shiyume.select_by_size", 'RESTRICT_SELECT_OFF'),
        ("shiyume.arrange_objects", 'GRID'),
        None,
        ("shiyume.batch_rename", 'SORTALPHA'),
        ("shiyume.clear_empty", 'X'),
    )),
    _ToolCategory("mesh", "网格", 'EDITMODE_HLT', {'OBJECT', 'EDIT_MESH'}, (
        ("shiyume.grid_cut", 'MOD_ARRAY'),
        ("shiyume.topology_cut", 'MESH_GRID'),
        ("shiyume.weld_by_vertex_group", 'AUTOMERGE_ON'),
        None,
        ("shiyume.vertex_color_fill", 'VPAINT_HLT'),
    )),
    _ToolCategory("weights", "权重", 'WPAINT_HLT', {'OBJECT', 'EDIT_MESH'}, (
        ("shiyume.clean_vertex_groups", 'GROUP_VERTEX'),
        ("shiyume.limit_weights", 'WPAINT_HLT'),
        ("shiyume.match_weights_active", 'VERTEXSEL'),
    )),
    _ToolCategory("normals", "法线", 'NORMALS_VERTEX', {'OBJECT'}, (
        ("shiyume.smooth_normals", 'MOD_NORMALEDIT'),
        ("shiyume.uv_normal_compress", 'UV_DATA'),
        None,
        ("shiyume.normal_map_to_mesh", 'IMPORT'),
        ("shiyume.mesh_to_normal_map", 'EXPORT'),
        None,
        ("shiyume.outline", 'MOD_SOLIDIFY'),
    )),
    _ToolCategory("endfield", "EndField", 'MATERIAL', {'OBJECT'}, (
        ("shiyume.endfield_hair_dual_normal", 'CURVES'),
    )),
    _ToolCategory("uv", "UV", 'UV', {'OBJECT', 'EDIT_MESH'}, (
        ("shiyume.mesh_uv_morph", 'UV_SYNC_SELECT'),
        ("shiyume.mesh_uv_morph_stop", 'X'),
        None,
        ("shiyume.arrange_uv_islands", 'ALIGN_CENTER'),
        ("shiyume.uv_pack_lock_group", 'PACKAGE'),
        None,
        ("shiyume.prepare_uv_copy", 'COPYDOWN'),
        ("shiyume.smart_uv_redirect", 'UV_ISLANDSEL'),
    )),
    _ToolCategory("curve", "曲线", 'CURVE_DATA', {'OBJECT', 'EDIT_CURVE'}, (
        ("shiyume.curve_smooth_fix", 'CURVE_DATA'),
        ("shiyume.curve_to_mesh", 'MESH_DATA'),
        ("shiyume.mesh_to_curve", 'CURVE_PATH'),
    )),
    _ToolCategory("render", "渲染 / 导出", 'RENDER_STILL', {'OBJECT'}, (
        ("shiyume.render_uv_texture", 'TEXTURE'),
        ("shiyume.viewport_screenshot", 'RESTRICT_VIEW_OFF'),
        ("shiyume.batch_bake_textures", 'RENDER_STILL'),
        None,
        ("shiyume.modular_export", 'EXPORT'),
    )),
    _ToolCategory("generate", "生成", 'MESH_DATA', {'OBJECT'}, (
        ("shiyume.fractal_fish", 'MESH_DATA'),
    )),
)


def _draw_items(layout, items):
    for item in items:
        if item is None:
            layout.separator()
        else:
            layout.operator(item[0], icon=item[1])


def _build_menu(category):
    def draw(self, context):
        _draw_items(self.layout, category.items)

    return type(f"SHIYUME_MT_category_{category.key}", (bpy.types.Menu,), {
        "bl_idname": f"SHIYUME_MT_category_{category.key}",
        "bl_label": category.label,
        "draw": draw,
    })


def _build_panel(category):
    def draw(self, context):
        _draw_items(self.layout.column(align=True), category.items)

    return type(f"SHIYUME_PT_category_{category.key}", (bpy.types.Panel,), {
        "bl_idname": f"SHIYUME_PT_category_{category.key}",
        "bl_label": category.label,
        "bl_space_type": 'VIEW_3D',
        "bl_region_type": 'UI',
        "bl_category": 'Shiyume',
        "bl_parent_id": "SHIYUME_PT_Sidebar",
        "bl_options": {'DEFAULT_CLOSED'},
        "draw": draw,
    })


_CATEGORY_MENUS = tuple(_build_menu(category) for category in _CATEGORIES)
_CATEGORY_PANELS = tuple(_build_panel(category) for category in _CATEGORIES)


# ---------------------------------------------------------------------------
# 根菜单 / 根面板
# ---------------------------------------------------------------------------

class SHIYUME_MT_Main(bpy.types.Menu):
    """右键根菜单:按当前模式列出相关分类的子菜单。"""
    bl_label = "Shiyume Tools"
    bl_idname = "SHIYUME_MT_Main"

    def draw(self, context):
        layout = self.layout
        mode = context.mode
        drawn = False
        for category in _CATEGORIES:
            if category.modes is None or mode in category.modes:
                layout.menu(f"SHIYUME_MT_category_{category.key}", icon=category.icon)
                drawn = True
        if not drawn:
            layout.operator("shiyume.batch_rename", icon='SORTALPHA')
            layout.operator("shiyume.outline", icon='MOD_SOLIDIFY')
            layout.operator("shiyume.viewport_screenshot", icon='RESTRICT_VIEW_OFF')


class SHIYUME_MT_UV(bpy.types.Menu):
    """UV 编辑器专用菜单(与 3D 视图分类表独立的精选列表)。"""
    bl_label = "Shiyume UV Tools"
    bl_idname = "SHIYUME_MT_UV"

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.arrange_uv_islands", icon='ALIGN_CENTER')
        layout.operator("shiyume.uv_pack_lock_group", icon='PACKAGE')
        layout.separator()
        layout.operator("shiyume.mesh_uv_morph", icon='UV_SYNC_SELECT')
        layout.operator("shiyume.mesh_uv_morph_stop", icon='X')
        layout.separator()
        layout.operator("shiyume.prepare_uv_copy", icon='COPYDOWN')
        layout.operator("shiyume.smart_uv_redirect", icon='UV_ISLANDSEL')
        layout.operator("shiyume.render_uv_texture", icon='RENDERLAYERS')


class SHIYUME_PT_Sidebar(bpy.types.Panel):
    """侧栏根面板:分类子面板的挂载点。"""
    bl_label = "Shiyume Toolkit"
    bl_idname = "SHIYUME_PT_Sidebar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'

    def draw(self, context):
        pass


def _menu_main(self, context):
    self.layout.menu("SHIYUME_MT_Main")


def _menu_uv(self, context):
    self.layout.separator()
    self.layout.menu("SHIYUME_MT_UV", icon='MODIFIER')


def _menu_mesh_add(self, context):
    self.layout.separator()
    self.layout.operator("shiyume.fractal_fish", icon='MESH_DATA', text="Fractal Fish (分形鱼)")


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

_CLASSES = (
    SHIYUME_MT_Main,
    SHIYUME_MT_UV,
    SHIYUME_PT_Sidebar,
) + _CATEGORY_MENUS + _CATEGORY_PANELS

_CONTEXT_MENUS = (
    "VIEW3D_MT_object_context_menu",
    "VIEW3D_MT_edit_mesh_context_menu",
    "VIEW3D_MT_edit_mesh_specials",
    "VIEW3D_MT_pose_context_menu",
    "VIEW3D_MT_pose_specials",
    "VIEW3D_MT_edit_curve_context_menu",
    "VIEW3D_MT_edit_curve_specials",
    "VIEW3D_MT_armature_context_menu",
    "VIEW3D_MT_armature_specials",
)

_UV_MENUS = (
    "IMAGE_MT_uv_context_menu",
    "IMAGE_MT_uvs_context_menu",
    "IMAGE_MT_uv_specials",
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    for menu_name in _CONTEXT_MENUS:
        if hasattr(bpy.types, menu_name):
            getattr(bpy.types, menu_name).prepend(_menu_main)

    for menu_name in _UV_MENUS:
        if hasattr(bpy.types, menu_name):
            getattr(bpy.types, menu_name).prepend(_menu_uv)

    if hasattr(bpy.types, "VIEW3D_MT_mesh_add"):
        bpy.types.VIEW3D_MT_mesh_add.append(_menu_mesh_add)


def unregister():
    for menu_name in _CONTEXT_MENUS:
        if hasattr(bpy.types, menu_name):
            try:
                getattr(bpy.types, menu_name).remove(_menu_main)
            except Exception:
                pass

    for menu_name in _UV_MENUS:
        if hasattr(bpy.types, menu_name):
            try:
                getattr(bpy.types, menu_name).remove(_menu_uv)
            except Exception:
                pass

    if hasattr(bpy.types, "VIEW3D_MT_mesh_add"):
        try:
            bpy.types.VIEW3D_MT_mesh_add.remove(_menu_mesh_add)
        except Exception:
            pass

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
