import bpy
from . import offset_keyframes
from . import fix_all

classes = (
    offset_keyframes.SHIYUME_OT_AnimationOffset,
    fix_all.SHIYUME_OT_FixAllAnimationIssues,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
