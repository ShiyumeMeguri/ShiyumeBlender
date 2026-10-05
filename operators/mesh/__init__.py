import bpy
from . import aabb_select
from . import grid_sort
from . import topology_cut
from . import cleanup_vgs
from . import weight_prune
from . import select_avg_size_half
from . import vg_smooth_merge
from . import match_weights_active
from . import pair_weights
from . import lossless_mirror
from . import select_island_inner

classes = (
    aabb_select.SHIYUME_OT_AABBSelect,
    grid_sort.SHIYUME_OT_GridSort,
    topology_cut.SHIYUME_OT_TopologyCut,
    cleanup_vgs.SHIYUME_OT_CleanupVertexGroups,
    weight_prune.SHIYUME_OT_WeightPrune,
    select_avg_size_half.SHIYUME_OT_SelectAvgSizeHalf,
    vg_smooth_merge.SHIYUME_OT_VGSmoothMerge,
    match_weights_active.SHIYUME_OT_MatchWeightsActive,
    pair_weights.SHIYUME_OT_SwapVertexWeights,
    pair_weights.SHIYUME_OT_CopyVertexWeights,
    lossless_mirror.SHIYUME_OT_LosslessMirror,
    select_island_inner.SHIYUME_OT_SelectIslandInner,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
