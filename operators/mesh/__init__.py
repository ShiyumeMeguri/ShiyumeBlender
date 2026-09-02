import bpy
from . import aabb_select
from . import grid_sort
from . import grid_cut
from . import topology_cut
from . import cleanup_vgs
from . import weight_prune
from . import select_avg_size_half
from . import vg_smooth_merge
from . import match_weights_active
from . import pair_weights
from . import common_sync

classes = (
    aabb_select.SHIYUME_OT_AABBSelect,
    grid_sort.SHIYUME_OT_GridSort,
    grid_cut.SHIYUME_OT_GridCut,
    topology_cut.SHIYUME_OT_TopologyCut,
    cleanup_vgs.SHIYUME_OT_CleanupVertexGroups,
    weight_prune.SHIYUME_OT_WeightPrune,
    select_avg_size_half.SHIYUME_OT_SelectAvgSizeHalf,
    vg_smooth_merge.SHIYUME_OT_VGSmoothMerge,
    match_weights_active.SHIYUME_OT_MatchWeightsActive,
    pair_weights.SHIYUME_OT_SwapVertexWeights,
    pair_weights.SHIYUME_OT_CopyVertexWeights,
    common_sync.SHIYUME_OT_CommonBindPick,
    common_sync.SHIYUME_OT_CommonBind,
    common_sync.SHIYUME_OT_CommonUnbind,
    common_sync.SHIYUME_OT_CommonPush,
    common_sync.SHIYUME_OT_CommonPull,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
