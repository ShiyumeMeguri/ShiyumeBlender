from ..tab import Tab


def draw(layout, context):
    skeleton = layout.column(align=True)
    skeleton.operator("shiyume.auto_bone_orientation", icon="CONSTRAINT_BONE")
    skeleton.operator("shiyume.armature_to_edge_mesh", icon="OUTLINER_OB_ARMATURE")
    layout.separator()
    repair = layout.column(align=True)
    repair.operator("shiyume.fix_all_anim_issues", icon="AUTO")
    repair.operator("shiyume.animation_offset", icon="ACTION")
    layout.separator()
    cleanup = layout.column(align=True)
    cleanup.operator("shiyume.cleanup_bake_frames", icon="X")
    cleanup.operator("shiyume.cleanup_bone_loc_scale", icon="GROUP_BONE")
    cleanup.operator("shiyume.fix_invalid_anim_paths", icon="LIBRARY_DATA_BROKEN")
    cleanup.operator("shiyume.clean_bone_collections", icon="OUTLINER_OB_ARMATURE")


TAB = Tab("animation", "动画", "骨骼方向、动画修复与清理", draw)
