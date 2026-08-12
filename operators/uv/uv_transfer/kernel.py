"""UV 传输内核：目标 UV 三角形光栅化、源图双线性采样、JFA 边缘膨胀。

纯 numpy，不引用 bpy，也不认识材质/物体/图像数据块——只处理数组。
"""

import numpy as np

# 单块样本数上限，控制光栅化过程的峰值内存
SAMPLE_CHUNK_BUDGET = 2_000_000

EXTENSION_REPEAT = 'REPEAT'
EXTENSION_EXTEND = 'EXTEND'


def _chunk_bounds(counts, budget):
    """按累计样本数把三角形切成若干块，返回 [(lo, hi), ...] 半开区间。"""
    cumulative = np.cumsum(counts, dtype=np.int64)
    total = int(cumulative[-1])
    if total <= budget:
        return [(0, len(counts))]

    cuts = np.searchsorted(cumulative, np.arange(budget, total, budget))
    cuts = np.unique(np.clip(cuts + 1, 1, len(counts)))

    bounds = []
    previous = 0
    for cut in cuts:
        cut = int(cut)
        if cut > previous:
            bounds.append((previous, cut))
            previous = cut
    if previous < len(counts):
        bounds.append((previous, len(counts)))
    return bounds


def iter_samples(target_uv, source_uv, width, height, supersample,
                 budget=SAMPLE_CHUNK_BUDGET):
    """光栅化目标 UV 三角形，分块产出 (最终像素扁平下标, 该样本对应的源 UV)。

    target_uv / source_uv 均为 (T, 3, 2) float32；超采样样本按 supersample 折回最终像素，
    因此调用方用 bincount 累加即可得到覆盖数与颜色和。
    """
    triangle_count = target_uv.shape[0]
    if triangle_count == 0:
        return

    grid_width = width * supersample
    grid_height = height * supersample

    # 采样点 i 的中心在 (i + 0.5) / grid，换算到采样索引空间即 uv * grid - 0.5
    px = target_uv[:, :, 0] * np.float32(grid_width) - np.float32(0.5)
    py = target_uv[:, :, 1] * np.float32(grid_height) - np.float32(0.5)

    x_min = np.clip(np.ceil(px.min(axis=1)), 0, grid_width - 1).astype(np.int32)
    x_max = np.clip(np.floor(px.max(axis=1)), 0, grid_width - 1).astype(np.int32)
    y_min = np.clip(np.ceil(py.min(axis=1)), 0, grid_height - 1).astype(np.int32)
    y_max = np.clip(np.floor(py.max(axis=1)), 0, grid_height - 1).astype(np.int32)

    box_width = (x_max - x_min + 1).astype(np.int64)
    box_height = (y_max - y_min + 1).astype(np.int64)
    counts = box_width * box_height

    keep = np.nonzero(counts > 0)[0].astype(np.int32)
    if keep.size == 0:
        return
    kept_counts = counts[keep]

    for low, high in _chunk_bounds(kept_counts, budget):
        block_triangles = keep[low:high]
        block_counts = kept_counts[low:high]
        block_total = int(block_counts.sum())

        repeated = np.repeat(block_triangles, block_counts)
        starts = np.cumsum(block_counts) - block_counts
        local = np.arange(block_total, dtype=np.int64) - np.repeat(starts, block_counts)

        repeated_width = box_width[repeated]
        ix = x_min[repeated] + (local % repeated_width).astype(np.int32)
        iy = y_min[repeated] + (local // repeated_width).astype(np.int32)

        ax = px[repeated, 0]
        ay = py[repeated, 0]
        edge0_x = px[repeated, 1] - ax
        edge0_y = py[repeated, 1] - ay
        edge1_x = px[repeated, 2] - ax
        edge1_y = py[repeated, 2] - ay

        denominator = edge0_x * edge1_y - edge1_x * edge0_y
        non_degenerate = denominator != 0
        inverse = np.zeros_like(denominator)
        np.divide(np.float32(1.0), denominator, out=inverse, where=non_degenerate)

        qx = ix.astype(np.float32) - ax
        qy = iy.astype(np.float32) - ay
        weight1 = (qx * edge1_y - edge1_x * qy) * inverse
        weight2 = (edge0_x * qy - qx * edge0_y) * inverse
        weight0 = np.float32(1.0) - weight1 - weight2

        inside = non_degenerate & (weight0 >= 0) & (weight1 >= 0) & (weight2 >= 0)
        hit = np.nonzero(inside)[0]
        if hit.size == 0:
            continue

        hit_triangles = repeated[hit]
        w0 = weight0[hit]
        w1 = weight1[hit]
        w2 = weight2[hit]

        u = (source_uv[hit_triangles, 0, 0] * w0
             + source_uv[hit_triangles, 1, 0] * w1
             + source_uv[hit_triangles, 2, 0] * w2)
        v = (source_uv[hit_triangles, 0, 1] * w0
             + source_uv[hit_triangles, 1, 1] * w1
             + source_uv[hit_triangles, 2, 1] * w2)

        pixel = ((iy[hit] // supersample).astype(np.int64) * width
                 + (ix[hit] // supersample))
        yield pixel, np.stack((u, v), axis=1)


def sample_bilinear(image, uv, extension):
    """在 (H, W, 4) 源图上按 (K, 2) UV 做双线性采样，返回 (K, 4) float32。"""
    height, width = image.shape[0], image.shape[1]

    x = uv[:, 0] * np.float32(width) - np.float32(0.5)
    y = uv[:, 1] * np.float32(height) - np.float32(0.5)

    x_floor = np.floor(x)
    y_floor = np.floor(y)
    fraction_x = (x - x_floor).astype(np.float32)[:, None]
    fraction_y = (y - y_floor).astype(np.float32)[:, None]

    x0 = x_floor.astype(np.int64)
    y0 = y_floor.astype(np.int64)
    x1 = x0 + 1
    y1 = y0 + 1

    if extension == EXTENSION_REPEAT:
        x0 %= width
        x1 %= width
        y0 %= height
        y1 %= height
    else:
        np.clip(x0, 0, width - 1, out=x0)
        np.clip(x1, 0, width - 1, out=x1)
        np.clip(y0, 0, height - 1, out=y0)
        np.clip(y1, 0, height - 1, out=y1)

    top = image[y0, x0] * (1.0 - fraction_x) + image[y0, x1] * fraction_x
    bottom = image[y1, x0] * (1.0 - fraction_x) + image[y1, x1] * fraction_x
    return (top * (1.0 - fraction_y) + bottom * fraction_y).astype(np.float32)


def _gather(array, offset_x, offset_y, empty):
    """返回 out[y, x] = array[y + offset_y, x + offset_x]，越界处填 empty。"""
    out = np.full_like(array, empty)
    height, width = array.shape

    destination_y = slice(max(0, -offset_y), height - max(0, offset_y))
    source_y = slice(max(0, offset_y), height - max(0, -offset_y))
    destination_x = slice(max(0, -offset_x), width - max(0, offset_x))
    source_x = slice(max(0, offset_x), width - max(0, -offset_x))

    out[destination_y, destination_x] = array[source_y, source_x]
    return out


def dilate_edges(color, coverage, margin):
    """把已覆盖像素的 RGB 向外扩散 margin 像素（JFA 求最近种子），alpha 保持不变。

    只写未覆盖像素，覆盖区原样保留——这样边缘像素永远不会被外扩区反向污染。
    """
    if margin <= 0 or not coverage.any() or coverage.all():
        return color

    height, width = coverage.shape
    columns = np.broadcast_to(np.arange(width, dtype=np.int32), (height, width))
    rows = np.broadcast_to(np.arange(height, dtype=np.int32)[:, None], (height, width))

    unreached = np.iinfo(np.int32).max
    seed_x = np.where(coverage, columns, -1).astype(np.int32)
    seed_y = np.where(coverage, rows, -1).astype(np.int32)
    distance = np.where(coverage, 0, unreached).astype(np.int32)

    offsets = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy]

    step = 1 << max(0, int(margin - 1).bit_length())
    while step >= 1:
        for offset_x, offset_y in offsets:
            candidate_x = _gather(seed_x, offset_x * step, offset_y * step, -1)
            candidate_y = _gather(seed_y, offset_x * step, offset_y * step, -1)

            delta_x = candidate_x - columns
            delta_y = candidate_y - rows
            candidate_distance = delta_x * delta_x + delta_y * delta_y

            better = (candidate_x >= 0) & (candidate_distance < distance)
            seed_x = np.where(better, candidate_x, seed_x)
            seed_y = np.where(better, candidate_y, seed_y)
            distance = np.where(better, candidate_distance, distance)
        step >>= 1

    fill = (~coverage) & (seed_x >= 0) & (distance <= margin * margin)
    color[fill, 0:3] = color[seed_y[fill], seed_x[fill], 0:3]
    return color
