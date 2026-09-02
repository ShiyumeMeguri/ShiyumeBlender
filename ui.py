import os

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
            layout.operator("shiyume.sort_roots_x", icon="SORTSIZE")
            layout.operator("shiyume.clear_empty", icon="X")
            layout.operator("shiyume.cleanup_vgs", icon="GROUP_VERTEX")

            layout.separator()
            layout.label(text="头发")
            layout.operator("shiyume.hair_to_path", icon="OUTLINER_OB_CURVES")

            layout.separator()
            layout.label(text="法线贴图烘焙")
            layout.operator("shiyume.normal_map_to_mesh", icon="IMPORT")
            layout.operator("shiyume.mesh_to_normal_map", icon="EXPORT")

        elif mode in {"EDIT_MESH", "EDIT"}:
            layout.label(text="网格工具")
            layout.operator("shiyume.grid_cut", icon="MOD_ARRAY")
            layout.operator("shiyume.mesh_to_uv", icon="MESH_UVSPHERE")
            layout.operator("shiyume.cleanup_vgs", icon="GROUP_VERTEX")
            layout.operator("shiyume.weight_prune", icon="WPAINT_HLT")
            layout.operator("shiyume.match_weights_active", icon="VERTEXSEL")
            layout.operator("shiyume.swap_vertex_weights", icon="ARROW_LEFTRIGHT")
            layout.operator("shiyume.copy_vertex_weights", icon="PASTEDOWN")
            layout.operator("shiyume.vg_smooth_merge", icon="AUTOMERGE_ON")
            layout.operator("shiyume.normal_expansion", icon="MOD_NORMALEDIT")
            layout.operator("shiyume.vertex_color_rgba", icon="VPAINT_HLT")

        elif mode == "EDIT_ARMATURE":
            layout.label(text="骨架工具")
            layout.operator("shiyume.auto_bone_orientation", icon="CONSTRAINT_BONE")

        elif mode == "EDIT_CURVE":
            layout.label(text="曲线工具")
            layout.operator("shiyume.curve_smooth_fix", icon="CURVE_DATA")
            layout.operator("shiyume.curve_to_mesh", icon="MESH_DATA")
            layout.operator("shiyume.mesh_to_curve", icon="CURVE_PATH")


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
        layout.operator("shiyume.uv_from_mesh", icon="UV_SYNC_SELECT")
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
        layout.operator("shiyume.auto_bone_orientation", icon="CONSTRAINT_BONE")
        layout.separator()
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
        col.operator("shiyume.weight_prune", icon="WPAINT_HLT")
        col.operator("shiyume.match_weights_active", icon="VERTEXSEL")
        col.operator("shiyume.swap_vertex_weights", icon="ARROW_LEFTRIGHT")
        col.operator("shiyume.copy_vertex_weights", icon="PASTEDOWN")
        col.operator("shiyume.vg_smooth_merge", icon="AUTOMERGE_ON")


class SHIYUME_PT_CommonMesh(bpy.types.Panel):
    """共用网格同步。放在 Item 页而不是 Shiyume 页: 它是"看当前选中的这个物体
    绑到哪儿、推一下拉一下"，属于物体属性的即时查看，和 Item 页里其它内容
    (变换、尺寸) 是同一类东西，用的时候不该再切标签页。"""
    bl_label = "共用网格 (按需同步)"
    bl_idname = "SHIYUME_PT_CommonMesh"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def draw(self, context):
        from .operators.mesh.common_sync import binding_of

        layout = self.layout
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            layout.label(text="先选中一个网格物体", icon='INFO')
            return

        binding = binding_of(obj)
        if binding is None:
            layout.label(text="%s 未绑定共用来源" % obj.name, icon='UNLINKED')
            layout.operator("shiyume.common_bind", icon='FILE_BLEND')
            return

        path, mesh_name = binding
        box = layout.box()
        box.label(text=obj.name, icon='OUTLINER_OB_MESH')
        box.label(text="→ %s" % os.path.basename(path), icon='FILE_BLEND')
        box.label(text="   数据块: %s" % mesh_name, icon='MESH_DATA')
        if not os.path.isfile(path):
            box.label(text="来源文件不存在！", icon='ERROR')

        col = layout.column(align=True)
        col.enabled = os.path.isfile(path)
        col.operator("shiyume.common_push", icon='EXPORT')
        col.operator("shiyume.common_pull", icon='IMPORT')
        row = layout.row(align=True)
        row.operator("shiyume.common_bind", text="改绑到别的文件", icon='FILE_BLEND')
        pick = row.operator("shiyume.common_bind_pick", text="换数据块", icon='MESH_DATA')
        pick.filepath = path
        layout.operator("shiyume.common_unbind", icon='X')
        layout.label(text="网格始终是本地的，随时可编辑", icon='CHECKMARK')


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

        col = layout.column(align=True)
        col.label(text="法线贴图烘焙")
        col.operator("shiyume.normal_map_to_mesh", icon="IMPORT")
        col.operator("shiyume.mesh_to_normal_map", icon="EXPORT")

        layout.operator("shiyume.vertex_color_rgba", icon="VPAINT_HLT")


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
        layout.operator("shiyume.uv_from_mesh", icon="UV_SYNC_SELECT")
        layout.operator("shiyume.uv_island_equidistant", icon="ALIGN_CENTER")
        layout.operator("shiyume.uv_island_sort_height", icon="SORTSIZE")


class SHIYUME_PT_UVTransfer(bpy.types.Panel):
    """UV 重定向：源 UV 上的贴图 → 目标 UV 的排布。"""
    bl_label = "UV 重定向"
    bl_idname = "SHIYUME_PT_UVTransfer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shiyume'
    bl_parent_id = "SHIYUME_PT_Sidebar"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.shiyume_uv_transfer
        obj = context.active_object

        if obj is None or obj.type != 'MESH':
            layout.label(text="请激活一个网格物体", icon='INFO')
            return

        col = layout.column(align=True)
        col.label(text="在网格上编辑 UV 布局")
        col.operator("shiyume.mesh_to_uv", icon="MESH_UVSPHERE", text="展平为网格")
        col.operator("shiyume.uv_from_mesh", icon="UV_SYNC_SELECT", text="网格坐标写回UV")

        layout.separator()

        layout.prop(settings, "target_space", text="")

        col = layout.column(align=True)
        col.prop_search(settings, "source_uv", obj.data, "uv_layers",
                        text="源 UV", icon='UV_DATA')
        target_text = ("目标 UV" if settings.target_space == 'UV_LAYER'
                       else "投影写入")
        row = col.row(align=True)
        row.enabled = (settings.target_space == 'UV_LAYER'
                       or settings.apply_to_object)
        row.prop_search(settings, "target_uv", obj.data, "uv_layers",
                        text=target_text, icon='UV_ISLANDSEL')

        layout.prop(settings, "color_source", expand=True)

        col = layout.column(align=True)
        col.prop(settings, "resolution")
        col.prop(settings, "margin")
        if settings.color_source == 'IMAGE':
            col.prop(settings, "supersample")
            col.prop(settings, "extension")
        else:
            col.prop(settings, "bake_type")
            col.prop(settings, "bake_samples")

        layout.prop(settings, "apply_to_object")

        col = layout.column(align=True)
        col.prop(settings, "save_to_disk")
        sub = col.column(align=True)
        sub.enabled = settings.save_to_disk
        sub.prop(settings, "output_dir", text="")

        layout.operator("shiyume.uv_transfer", icon='TEXTURE')


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
        layout.operator("shiyume.hair_to_path", icon="OUTLINER_OB_CURVES")


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
        layout.operator("shiyume.clear_empty", icon="X")
        layout.operator("shiyume.sort_roots_x", icon="SORTSIZE")


_PANEL_CLASSES = (
    SHIYUME_PT_Sidebar,
    SHIYUME_PT_Animation,
    SHIYUME_PT_Mesh,
    SHIYUME_PT_CommonMesh,
    SHIYUME_PT_Shader,
    SHIYUME_PT_UV,
    SHIYUME_PT_UVTransfer,
    SHIYUME_PT_Curve,
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
