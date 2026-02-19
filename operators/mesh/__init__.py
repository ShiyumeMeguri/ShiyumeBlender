import bpy
from . import aabb_select
from . import grid_sort
from . import grid_cut
from . import cleanup_vgs
from . import weight_prune
from . import batch_rename
from . import material_link

classes = (
    aabb_select.SHIYUME_OT_AABBSelect,
    grid_sort.SHIYUME_OT_GridSort,
    grid_cut.SHIYUME_OT_GridCut,
    cleanup_vgs.SHIYUME_OT_CleanupVertexGroups,
    weight_prune.SHIYUME_OT_WeightPrune,
    batch_rename.SHIYUME_OT_BatchRename,
    material_link.SHIYUME_OT_MaterialLinkObject,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
