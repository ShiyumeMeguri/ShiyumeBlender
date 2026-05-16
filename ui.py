import bpy


# ---------------------------------------------------------------------------
# Right-click context menu (mode-aware)
# ---------------------------------------------------------------------------

class SHIYUME_MT_Main(bpy.types.Menu):
    bl_label = "Shiyume Tools"
    bl_idname = "SHIYUME_MT_Main"

    def draw(self, context):
        layout = self.layout
        mode = context.mode

        if mode == "POSE":
            layout.label(text="动画工具")
            layout.operator("shiyume.fix_all_anim_issues", icon="AUTO")
            layout.operator("shiyume.animation_offset", icon="ACTION")
            layout.separator()
            layout.operator("shiyume.cleanup_bake_frames", icon="X")
            layout.operator("shiyume.cleanup_bone_loc_scale", icon="GROUP_BONE")
            layout.operator("shiyume.fix_invalid_anim_paths", icon="LIBRARY_DATA_BROKEN")
            layout.operator("shiyume.clean_bone_collections", icon="OUTLINER_OB_ARMATURE")

        elif mode == "OBJECT":
            layout.label(text="选择与布局")
            layout.operator("shiyume.aabb_select", icon="RESTRICT_SELECT_OFF")
            layout.operator("shiyume.select_avg_size_half", icon="ZOOM_OUT")
            layout.operator("shiyume.grid_sort", icon="GRID")
            layout.operator("shiyume.topology_cut", icon="MESH_GRID")
            layout.operator("shiyume.mesh_to_uv", icon="MESH_UVSPHERE")
            layout.operator("shiyume.prepare_uv_copy", icon="COPYDOWN")
            layout.operator("shiyume.smart_uv_redirect", icon="UV_ISLANDSEL")
            layout.operator("shiyume.batch_rename", icon="SORTALPHA")
            layout.operator("shiyume.sort_roots_x", icon="SORTSIZE")
            layout.operator("shiyume.clear_empty", icon="X")
            layout.operator("shiyume.clear_zero_vgs", icon="GROUP_VERTEX")

            layout.separator()
            layout.label(text="渲染与杂项")
            layout.operator("shiyume.render_viewport_texture", icon="TEXTURE")
            layout.operator("shiyume.viewport_simple_render", icon="RESTRICT_VIEW_OFF")
            layout.operator("shiyume.uv_render_rt", icon="UV")
            layout.operator("shiyume.batch_bake_textures", icon="RENDER_STILL")
            layout.operator("shiyume.modular_export", icon="EXPORT")
            layout.operator("shiyume.outline", icon="MOD_SOLIDIFY")

        elif mode in {"EDIT_MESH", "EDIT"}:
            layout.label(text="网格工具")
            layout.operator("shiyume.grid_cut", icon="MOD_ARRAY")
            layout.operator("shiyume.mesh_to_uv", icon="MESH_UVSPHERE")
            layout.operator("shiyume.prepare_uv_copy", icon="COPYDOWN")
            layout.operator("shiyume.smart_uv_redirect", icon="UV_ISLANDSEL")
            layout.operator("shiyume.cleanup_vgs", icon="GROUP_VERTEX")
            layout.operator("shiyume.clear_zero_vgs", icon="X")
            layout.operator("shiyume.weight_prune", icon="WPAINT_HLT")
            layout.operator("shiyume.match_weights_active", icon="VERTEXSEL")
            layout.operator("shiyume.vg_smooth_merge", icon="AUTOMERGE_ON")
            layout.operator("shiyume.normal_expansion", icon="MOD_NORMALEDIT")
            layout.operator("shiyume.outline", icon="MOD_SOLIDIFY")
            layout.operator("shiyume.vertex_color_rgba", icon="VPAINT_HLT")

        elif mode == "EDIT_CURVE":
            layout.label(text="曲线工具")
            layout.operator("shiyume.curve_smooth_fix", icon="CURVE_DATA")
            layout.operator("shiyume.curve_to_mesh", icon="MESH_DATA")
            layout.operator("shiyume.mesh_to_curve", icon="CURVE_PATH")

        else:
            layout.label(text="通用工具")
            layout.operator("shiyume.batch_rename", icon="SORTALPHA")
            layout.operator("shiyume.outline", icon="MOD_SOLIDIFY")
            layout.operator("shiyume.render_viewport_texture", icon="TEXTURE")


class SHIYUME_MT_UV(bpy.types.Menu):
    bl_label = "Shiyume UV Tools"
    bl_idname = "SHIYUME_MT_UV"

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.uv_pack_lock_group", icon="PACKAGE")
        layout.operator("shiyume.mesh_uv_sync", icon="UV_DATA")
        layout.operator("shiyume.mesh_uv_sync_live", icon="UV_SYNC_SELECT")
        layout.operator("shiyume.mesh_uv_sync_live_disable", icon="X")
        layout.operator(
            "shiyume.mesh_to_uv", icon="MESH_UVSPHERE", text="Mesh to UV (网格转UV)"
        )
        layout.operator("shiyume.prepare_uv_copy", icon="COPYDOWN")
        layout.operator("shiyume.smart_uv_redirect", icon="UV_ISLANDSEL")
        layout.operator("shiyume.uv_render_rt", icon="RENDERLAYERS")
        layout.separator()
        layout.operator("shiyume.uv_island_equidistant", icon="ALIGN_CENTER")
        layout.operator("shiyume.uv_island_sort_height", icon="SORTSIZE")


def menu_func(self, context):
    self.layout.menu("SHIYUME_MT_Main")


def menu_func_uv(self, context):
    self.layout.separator()
    self.layout.menu("SHIYUME_MT_UV", icon="MODIFIER")


def menu_func_mesh_add(self, context):
    """Add 'Fractal Fish' under Shift+A > Mesh."""
    self.layout.separator()
    self.layout.operator("shiyume.fractal_fish", icon="MESH_DATA", text="Fractal Fish (分形鱼)")


# ---------------------------------------------------------------------------
# Sidebar panel (View3D > N > Shiyume)
# ---------------------------------------------------------------------------

class SHIYUME_PT_Sidebar(bpy.types.Panel):
    """Main Shiyume sidebar panel exposing every operator categorised."""
    bl_label = "Shiyume Tools"
    bl_idname = "SHIYUME_PT_Sidebar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"Mode: {context.mode}", icon='OPTIONS')


class SHIYUME_PT_Animation(bpy.types.Panel):
    bl_label = "动画"
    bl_idname = "SHIYUME_PT_Animation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'
    bl_parent_id = "SHIYUME_PT_Sidebar"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.fix_all_anim_issues", icon="AUTO")
        layout.operator("shiyume.animation_offset", icon="ACTION")
        layout.separator()
        layout.operator("shiyume.cleanup_bake_frames", icon="X")
        layout.operator("shiyume.cleanup_bone_loc_scale", icon="GROUP_BONE")
        layout.operator("shiyume.fix_invalid_anim_paths", icon="LIBRARY_DATA_BROKEN")
        layout.operator("shiyume.clean_bone_collections", icon="OUTLINER_OB_ARMATURE")


class SHIYUME_PT_Mesh(bpy.types.Panel):
    bl_label = "网格"
    bl_idname = "SHIYUME_PT_Mesh"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'
    bl_parent_id = "SHIYUME_PT_Sidebar"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.label(text="选择/布局")
        col.operator("shiyume.aabb_select", icon="RESTRICT_SELECT_OFF")
        col.operator("shiyume.select_avg_size_half", icon="ZOOM_OUT")
        col.operator("shiyume.grid_sort", icon="GRID")

        col = layout.column(align=True)
        col.label(text="拓扑/剪切")
        col.operator("shiyume.grid_cut", icon="MOD_ARRAY")
        col.operator("shiyume.topology_cut", icon="MESH_GRID")

        col = layout.column(align=True)
        col.label(text="顶点组/权重")
        col.operator("shiyume.cleanup_vgs", icon="GROUP_VERTEX")
        col.operator("shiyume.clear_zero_vgs", icon="X")
        col.operator("shiyume.weight_prune", icon="WPAINT_HLT")
        col.operator("shiyume.match_weights_active", icon="VERTEXSEL")
        col.operator("shiyume.vg_smooth_merge", icon="AUTOMERGE_ON")

        col = layout.column(align=True)
        col.label(text="重命名")
        col.operator("shiyume.batch_rename", icon="SORTALPHA")


class SHIYUME_PT_Shader(bpy.types.Panel):
    bl_label = "着色 / 烘焙"
    bl_idname = "SHIYUME_PT_Shader"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'
    bl_parent_id = "SHIYUME_PT_Sidebar"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.normal_expansion", icon="MOD_NORMALEDIT")
        layout.operator("shiyume.vertex_color_rgba", icon="VPAINT_HLT")
        layout.operator("shiyume.batch_bake_textures", icon="RENDER_STILL")


class SHIYUME_PT_UV(bpy.types.Panel):
    bl_label = "UV"
    bl_idname = "SHIYUME_PT_UV"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'
    bl_parent_id = "SHIYUME_PT_Sidebar"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.uv_pack_lock_group", icon="PACKAGE")
        layout.operator("shiyume.mesh_uv_sync", icon="UV_DATA")
        layout.operator("shiyume.mesh_uv_sync_live", icon="UV_SYNC_SELECT")
        layout.operator("shiyume.mesh_uv_sync_live_disable", icon="X")
        layout.operator("shiyume.mesh_to_uv", icon="MESH_UVSPHERE")
        layout.operator("shiyume.prepare_uv_copy", icon="COPYDOWN")
        layout.operator("shiyume.smart_uv_redirect", icon="UV_ISLANDSEL")
        layout.operator("shiyume.uv_island_equidistant", icon="ALIGN_CENTER")
        layout.operator("shiyume.uv_island_sort_height", icon="SORTSIZE")


class SHIYUME_PT_Curve(bpy.types.Panel):
    bl_label = "曲线"
    bl_idname = "SHIYUME_PT_Curve"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'
    bl_parent_id = "SHIYUME_PT_Sidebar"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.curve_smooth_fix", icon="CURVE_DATA")
        layout.operator("shiyume.curve_to_mesh", icon="MESH_DATA")
        layout.operator("shiyume.mesh_to_curve", icon="CURVE_PATH")


class SHIYUME_PT_Render(bpy.types.Panel):
    bl_label = "渲染 / 导出"
    bl_idname = "SHIYUME_PT_Render"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'
    bl_parent_id = "SHIYUME_PT_Sidebar"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.render_viewport_texture", icon="TEXTURE")
        layout.operator("shiyume.viewport_simple_render", icon="RESTRICT_VIEW_OFF")
        layout.operator("shiyume.uv_render_rt", icon="RENDERLAYERS")
        layout.operator("shiyume.modular_export", icon="EXPORT")


class SHIYUME_PT_Misc(bpy.types.Panel):
    bl_label = "杂项"
    bl_idname = "SHIYUME_PT_Misc"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'
    bl_parent_id = "SHIYUME_PT_Sidebar"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.outline", icon="MOD_SOLIDIFY")
        layout.operator("shiyume.clear_empty", icon="X")
        layout.operator("shiyume.sort_roots_x", icon="SORTSIZE")


_PANEL_CLASSES = (
    SHIYUME_PT_Sidebar,
    SHIYUME_PT_Animation,
    SHIYUME_PT_Mesh,
    SHIYUME_PT_Shader,
    SHIYUME_PT_UV,
    SHIYUME_PT_Curve,
    SHIYUME_PT_Render,
    SHIYUME_PT_Misc,
)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def register():
    bpy.utils.register_class(SHIYUME_MT_Main)
    bpy.utils.register_class(SHIYUME_MT_UV)

    for cls in _PANEL_CLASSES:
        bpy.utils.register_class(cls)

    # Target all possible specials/context menus with prepend like LoopTools
    targets = [
        "VIEW3D_MT_object_context_menu",
        "VIEW3D_MT_edit_mesh_context_menu",
        "VIEW3D_MT_edit_mesh_specials",
        "VIEW3D_MT_pose_context_menu",
        "VIEW3D_MT_pose_specials",
        "VIEW3D_MT_edit_curve_context_menu",
        "VIEW3D_MT_edit_curve_specials",
        "VIEW3D_MT_armature_context_menu",
        "VIEW3D_MT_armature_specials",
    ]

    for t in targets:
        if hasattr(bpy.types, t):
            getattr(bpy.types, t).prepend(menu_func)

    # UV Editor menus
    uv_targets = [
        "IMAGE_MT_uv_context_menu",
        "IMAGE_MT_uvs_context_menu",
        "IMAGE_MT_uv_specials",
    ]

    for t in uv_targets:
        if hasattr(bpy.types, t):
            getattr(bpy.types, t).prepend(menu_func_uv)

    # Shift+A > Mesh menu (where built-in Cube/Plane/etc live) -> add Fractal Fish
    if hasattr(bpy.types, "VIEW3D_MT_mesh_add"):
        bpy.types.VIEW3D_MT_mesh_add.append(menu_func_mesh_add)


def unregister():
    targets = [
        "VIEW3D_MT_object_context_menu",
        "VIEW3D_MT_edit_mesh_context_menu",
        "VIEW3D_MT_edit_mesh_specials",
        "VIEW3D_MT_pose_context_menu",
        "VIEW3D_MT_pose_specials",
        "VIEW3D_MT_edit_curve_context_menu",
        "VIEW3D_MT_edit_curve_specials",
        "VIEW3D_MT_armature_context_menu",
        "VIEW3D_MT_armature_specials",
    ]
    for t in targets:
        if hasattr(bpy.types, t):
            try:
                getattr(bpy.types, t).remove(menu_func)
            except Exception:
                pass

    uv_targets = [
        "IMAGE_MT_uv_context_menu",
        "IMAGE_MT_uvs_context_menu",
        "IMAGE_MT_uv_specials",
    ]
    for t in uv_targets:
        if hasattr(bpy.types, t):
            try:
                getattr(bpy.types, t).remove(menu_func_uv)
            except Exception:
                pass

    if hasattr(bpy.types, "VIEW3D_MT_mesh_add"):
        try:
            bpy.types.VIEW3D_MT_mesh_add.remove(menu_func_mesh_add)
        except Exception:
            pass

    for cls in reversed(_PANEL_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    bpy.utils.unregister_class(SHIYUME_MT_Main)
    bpy.utils.unregister_class(SHIYUME_MT_UV)
