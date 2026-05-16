import bpy
from . import aabb_select
from . import grid_sort
from . import grid_cut
from . import topology_cut
from . import cleanup_vgs
from . import weight_prune
from . import batch_rename
from . import select_avg_size_half
from . import vg_smooth_merge
from . import match_weights_active
from . import clear_zero_vgs

classes = (
    aabb_select.SHIYUME_OT_AABBSelect,
    grid_sort.SHIYUME_OT_GridSort,
    grid_cut.SHIYUME_OT_GridCut,
    topology_cut.SHIYUME_OT_TopologyCut,
    cleanup_vgs.SHIYUME_OT_CleanupVertexGroups,
    weight_prune.SHIYUME_OT_WeightPrune,
    batch_rename.SHIYUME_OT_BatchRename,
    select_avg_size_half.SHIYUME_OT_SelectAvgSizeHalf,
    vg_smooth_merge.SHIYUME_OT_VGSmoothMerge,
    match_weights_active.SHIYUME_OT_MatchWeightsActive,
    clear_zero_vgs.SHIYUME_OT_ClearZeroVertexGroups,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
