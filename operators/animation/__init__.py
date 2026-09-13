import bpy
from . import offset_keyframes
from . import fix_all
from . import cleanup_bake
from . import cleanup_transforms
from . import fix_paths
from . import clean_bone_collections
from . import auto_bone_orientation
from . import rig_sync

classes = (
    offset_keyframes.SHIYUME_OT_AnimationOffset,
    fix_all.SHIYUME_OT_FixAllAnimationIssues,
    cleanup_bake.SHIYUME_OT_CleanupBakeFrames,
    cleanup_transforms.SHIYUME_OT_CleanupSelectedBoneLocScale,
    fix_paths.SHIYUME_OT_FixInvalidAnimPaths,
    clean_bone_collections.SHIYUME_OT_CleanBoneCollections,
    auto_bone_orientation.SHIYUME_OT_AutoBoneOrientation,
    rig_sync.SHIYUME_OT_RigBind,
    rig_sync.SHIYUME_OT_RigPush,
    rig_sync.SHIYUME_OT_RigPull,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
