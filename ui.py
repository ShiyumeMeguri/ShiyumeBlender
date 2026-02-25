import bpy

def draw_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu("SHIYUME_MT_Main", text="Shiyume Tools", icon='MODIFIER')

class SHIYUME_MT_Main(bpy.types.Menu):
    bl_label = "Shiyume Tools"
    bl_idname = "SHIYUME_MT_Main"

    def draw(self, context):
        layout = self.layout
        mode = context.mode
        
        if mode == 'POSE':
            layout.label(text="动画工具")
            layout.operator("shiyume.fix_all_anim_issues", icon='AUTO')
            layout.operator("shiyume.animation_offset", icon='ACTION')
        
        elif mode == 'OBJECT':
            layout.label(text="选择与布局")
            layout.operator("shiyume.aabb_select", icon='RESTRICT_SELECT_OFF')
            layout.operator("shiyume.grid_sort", icon='GRID')
            layout.operator("shiyume.mat_link_object", icon='LINKED')
            layout.operator("shiyume.mesh_to_uv", icon='MESH_UVSPHERE')
            layout.operator("shiyume.prepare_uv_copy", icon='COPYDOWN')
            layout.operator("shiyume.smart_uv_redirect", icon='UV_ISLANDSEL')
            layout.operator("shiyume.batch_rename", icon='SORTALPHA')
            layout.operator("shiyume.sort_roots_x", icon='SORTSIZE')
            layout.operator("shiyume.clear_empty", icon='X')
            
            layout.separator()
            layout.label(text="渲染与杂项")
            layout.operator("shiyume.render_viewport_texture", icon='TEXTURE')
            layout.operator("shiyume.batch_bake_textures", icon='RENDER_STILL')
            layout.operator("shiyume.preview_360", icon='SCENE_DATA')
            layout.operator("shiyume.modular_export", icon='EXPORT')
            layout.operator("shiyume.fractal_fish", icon='MESH_DATA')

        elif mode in {'EDIT_MESH', 'EDIT'}:
            layout.label(text="网格工具")
            layout.operator("shiyume.grid_cut", icon='MOD_ARRAY')
            layout.operator("shiyume.mesh_to_uv", icon='MESH_UVSPHERE')
            layout.operator("shiyume.prepare_uv_copy", icon='COPYDOWN')
            layout.operator("shiyume.smart_uv_redirect", icon='UV_ISLANDSEL')
            layout.operator("shiyume.cleanup_vgs", icon='GROUP_VERTEX')
            layout.operator("shiyume.weight_prune", icon='WPAINT_HLT')
            layout.operator("shiyume.normal_expansion", icon='MOD_NORMALEDIT')
            layout.operator("shiyume.outline", icon='MOD_SOLIDIFY')
            layout.operator("shiyume.vertex_color_rgba", icon='VPAINT_HLT')
        
        elif mode == 'EDIT_CURVE':
            layout.label(text="曲线工具")
            layout.operator("shiyume.curve_smooth_fix", icon='CURVE_DATA')
            layout.operator("shiyume.curve_to_mesh", icon='MESH_DATA')
            layout.operator("shiyume.mesh_to_curve", icon='CURVE_PATH')
        
        else:
            # Fallback for other modes
            layout.label(text="通用工具")
            layout.operator("shiyume.batch_rename", icon='SORTALPHA')
            layout.operator("shiyume.outline", icon='MOD_SOLIDIFY')
            layout.operator("shiyume.render_viewport_texture", icon='TEXTURE')
        
        # UV Editor menu is handled separately in IMAGE_MT_uv_context_menu

class SHIYUME_MT_UV(bpy.types.Menu):
    bl_label = "Shiyume UV Tools"
    bl_idname = "SHIYUME_MT_UV"

    def draw(self, context):
        layout = self.layout
        layout.operator("shiyume.uv_pack_lock_group", icon='PACKAGE')
        layout.operator("shiyume.mesh_uv_sync", icon='UV_DATA')
        layout.operator("shiyume.mesh_to_uv", icon='MESH_UVSPHERE', text="Mesh to UV (网格转UV)")
        layout.operator("shiyume.prepare_uv_copy", icon='COPYDOWN')
        layout.operator("shiyume.smart_uv_redirect", icon='UV_ISLANDSEL')
        layout.separator()
        layout.operator("shiyume.uv_island_equidistant", icon='ALIGN_CENTER')
        layout.operator("shiyume.uv_island_sort_height", icon='SORTSIZE')

def menu_func(self, context):
    self.layout.menu("SHIYUME_MT_Main")

def menu_func_uv(self, context):
    self.layout.separator()
    self.layout.menu("SHIYUME_MT_UV", icon='MODIFIER')

# REMOVED SHIYUME_PT_Sidebar
# REMOVED draw_header

def register():
    bpy.utils.register_class(SHIYUME_MT_Main)
    bpy.utils.register_class(SHIYUME_MT_UV)
    
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
            try: getattr(bpy.types, t).remove(menu_func)
            except: pass

    uv_targets = [
        "IMAGE_MT_uv_context_menu",
        "IMAGE_MT_uvs_context_menu",
        "IMAGE_MT_uv_specials",
    ]
    for t in uv_targets:
        if hasattr(bpy.types, t):
            try: getattr(bpy.types, t).remove(menu_func_uv)
            except: pass

    bpy.utils.unregister_class(SHIYUME_MT_Main)
    bpy.utils.unregister_class(SHIYUME_MT_UV)
