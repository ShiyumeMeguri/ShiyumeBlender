"""UV 传输内核：目标三角形按越界方式折进 0~1、光栅化、源图按越界方式采样、切线法线转向、带保护区的 JFA 外扩。

纯 numpy，不引用 bpy，也不认识材质/物体/图像数据块——只处理数组。
"""

import numpy as np

# 单块样本数上限，控制光栅化过程的峰值内存
SAMPLE_CHUNK_BUDGET = 2_000_000

EXTENSION_REPEAT = 'REPEAT'
EXTENSION_EXTEND = 'EXTEND'
EXTENSION_CLIP = 'CLIP'
EXTENSION_MIRROR = 'MIRROR'
FOLDING_EXTENSIONS = (EXTENSION_REPEAT, EXTENSION_MIRROR)

CONVENTION_OPENGL = 'OPENGL'
CONVENTION_DIRECTX = 'DIRECTX'


def transform(matrix, triangles):
    """按 3x3 齐次二维仿射变换 (T, 3, 2) 的坐标。"""
    linear = matrix[:2, :2].astype(np.float64)
    offset = matrix[:2, 2].astype(np.float64)
    return (triangles.astype(np.float64) @ linear.T + offset).astype(np.float32)


def _fold_axis(values, tiles, extension):
    shifted = values - tiles
    if extension == EXTENSION_MIRROR:
        shifted = np.where(tiles % 2 == 1, 1.0 - shifted, shifted)
    return shifted


def fold_triangles(triangles, extension):
    """把贴图坐标里的三角形折进 0~1：重复按整格平移，镜像在奇数格翻转，跨格的三角形每格各出一份。

    返回 (折好的三角形, 每份对应的原三角形下标, 无法表示的三角形数)。延展/裁剪不折叠——渲染时 0~1 以外读的是
    边缘或透明，排布里没有它的位置，这些三角形只统计出来交给调用方报告。
    """
    count = triangles.shape[0]
    if count == 0:
        return triangles, np.zeros(0, dtype=np.int64), 0
    if extension not in FOLDING_EXTENSIONS:
        outside = (triangles < 0.0).any(axis=(1, 2)) | (triangles > 1.0).any(axis=(1, 2))
        return triangles, np.arange(count, dtype=np.int64), int(np.count_nonzero(outside))

    low = np.floor(triangles.min(axis=1)).astype(np.int64)
    high = np.maximum(np.ceil(triangles.max(axis=1)).astype(np.int64) - 1, low)
    span = high - low + 1
    copies = span[:, 0] * span[:, 1]
    owner = np.repeat(np.arange(count, dtype=np.int64), copies)
    starts = np.cumsum(copies) - copies
    local = np.arange(owner.size, dtype=np.int64) - np.repeat(starts, copies)
    tile_u = low[owner, 0] + local % span[owner, 0]
    tile_v = low[owner, 1] + local // span[owner, 0]

    folded = triangles[owner].astype(np.float64)
    folded[:, :, 0] = _fold_axis(folded[:, :, 0], tile_u[:, None], extension)
    folded[:, :, 1] = _fold_axis(folded[:, :, 1], tile_v[:, None], extension)
    return folded.astype(np.float32), owner, 0


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
    """光栅化目标三角形，分块产出 (最终像素扁平下标, 该样本对应的源坐标, 样本所在三角形下标)。

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
        yield pixel, np.stack((u, v), axis=1), hit_triangles.astype(np.int64)


def coverage_mask(triangles, width, height, supersample):
    """三角形碰到的像素（任一超采样点落在里面即算），返回 (height, width) bool。"""
    covered = np.zeros(width * height, dtype=bool)
    for pixel, _uv, _triangle in iter_samples(triangles, triangles, width, height, supersample):
        covered[pixel] = True
    return covered.reshape(height, width)


def _address(index, size, extension):
    """越界的纹素下标按越界方式换回图内；裁剪额外给出哪些下标真在图内。"""
    if extension == EXTENSION_REPEAT:
        return index % size, None
    if extension == EXTENSION_MIRROR:
        period = index % (2 * size)
        return np.where(period < size, period, 2 * size - 1 - period), None
    if extension == EXTENSION_CLIP:
        return np.clip(index, 0, size - 1), (index >= 0) & (index < size)
    return np.clip(index, 0, size - 1), None


def _texels(image, rows, columns, row_inside, column_inside):
    values = image[rows, columns]
    if row_inside is None:
        return values
    return values * (row_inside & column_inside)[:, None].astype(np.float32)


def sample(image, uv, extension, nearest):
    """在 (H, W, 4) 源图上按 (K, 2) 坐标采样，返回 (K, 4) float32；nearest 为最近纹素，否则双线性。"""
    height, width = image.shape[0], image.shape[1]

    x = uv[:, 0] * np.float32(width)
    y = uv[:, 1] * np.float32(height)
    if nearest:
        columns, column_inside = _address(np.floor(x).astype(np.int64), width, extension)
        rows, row_inside = _address(np.floor(y).astype(np.int64), height, extension)
        return _texels(image, rows, columns, row_inside, column_inside).astype(np.float32)

    x = x - np.float32(0.5)
    y = y - np.float32(0.5)
    x_floor = np.floor(x)
    y_floor = np.floor(y)
    fraction_x = (x - x_floor).astype(np.float32)[:, None]
    fraction_y = (y - y_floor).astype(np.float32)[:, None]

    x_index = x_floor.astype(np.int64)
    y_index = y_floor.astype(np.int64)
    x0, x0_inside = _address(x_index, width, extension)
    x1, x1_inside = _address(x_index + 1, width, extension)
    y0, y0_inside = _address(y_index, height, extension)
    y1, y1_inside = _address(y_index + 1, height, extension)

    top = (_texels(image, y0, x0, y0_inside, x0_inside) * (1.0 - fraction_x)
           + _texels(image, y0, x1, y0_inside, x1_inside) * fraction_x)
    bottom = (_texels(image, y1, x0, y1_inside, x0_inside) * (1.0 - fraction_x)
              + _texels(image, y1, x1, y1_inside, x1_inside) * fraction_x)
    return (top * (1.0 - fraction_y) + bottom * fraction_y).astype(np.float32)


def normal_turns(source_uv, target_uv, convention):
    """每个三角形把切线空间法线 XY 从源排布的切线框架换到目标排布框架的 2x2 正交矩阵。

    切线框架跟着 UV 的 u/v 轴走：目标 UV 对源 UV 的雅可比取极分解的正交部分（旋转，或带镜像的反射），
    法线 XY 跟着它转；DirectX 约定的绿通道朝 -V，先翻到 +V 再转、转完翻回。退化三角形给单位阵。
    """
    source_edges = np.stack((source_uv[:, 1] - source_uv[:, 0],
                             source_uv[:, 2] - source_uv[:, 0]), axis=2).astype(np.float64)
    target_edges = np.stack((target_uv[:, 1] - target_uv[:, 0],
                             target_uv[:, 2] - target_uv[:, 0]), axis=2).astype(np.float64)
    turns = np.tile(np.identity(2), (source_uv.shape[0], 1, 1))
    determinant = np.linalg.det(source_edges)
    valid = np.abs(determinant) > 1e-14
    if not valid.any():
        return turns
    jacobian = target_edges[valid] @ np.linalg.inv(source_edges[valid])
    a = jacobian[:, 0, 0]
    b = jacobian[:, 0, 1]
    c = jacobian[:, 1, 0]
    d = jacobian[:, 1, 1]
    mirrored = (a * d - b * c) < 0.0
    angle = np.where(mirrored, np.arctan2(c + b, a - d), np.arctan2(c - b, a + d))
    cosine = np.cos(angle)
    sine = np.sin(angle)
    orthogonal = np.empty((angle.size, 2, 2))
    orthogonal[:, 0, 0] = cosine
    orthogonal[:, 1, 0] = sine
    orthogonal[:, 0, 1] = np.where(mirrored, sine, -sine)
    orthogonal[:, 1, 1] = np.where(mirrored, -cosine, cosine)
    if convention == CONVENTION_DIRECTX:
        flip = np.diag([1.0, -1.0])
        orthogonal = flip @ orthogonal @ flip
    turns[valid] = orthogonal
    return turns


def is_turned(turns, tolerance=1e-4):
    """哪些三角形的法线框架真的转了（不是单位阵）。"""
    return np.abs(turns - np.identity(2)).max(axis=(1, 2)) > tolerance


def turn_normals(sampled, turns):
    """按每个样本的 2x2 矩阵转动 RG 里编码的切线法线 XY（值域 0~1，0.5 为零）。"""
    xy = sampled[:, 0:2].astype(np.float64) * 2.0 - 1.0
    turned = np.einsum('kij,kj->ki', turns, xy)
    result = sampled.copy()
    result[:, 0:2] = ((turned + 1.0) * 0.5).astype(np.float32)
    return result


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


def grow(mask, radius):
    """把 (H, W) bool 区域向外长 radius 像素（八邻域）。"""
    grown = mask.copy()
    for _step in range(radius):
        layer = grown.copy()
        for offset_y in (-1, 0, 1):
            for offset_x in (-1, 0, 1):
                if offset_x or offset_y:
                    layer |= _gather(grown, offset_x, offset_y, False)
        grown = layer
    return grown


def dilate(color, coverage, margin, protected=None):
    """把已覆盖像素的四个通道向外扩散 margin 像素（JFA 求最近种子），返回被填写的像素 (H, W) bool。

    protected 是别人占着的像素：它们也作种子参与求最近，却不出颜色——外扩只写离本次覆盖比离保护区更近的空像素。
    覆盖区与保护区原样保留，边缘像素永远不会被外扩区反向污染。
    """
    filled = np.zeros(coverage.shape, dtype=bool)
    seeds = coverage if protected is None else (coverage | protected)
    if margin <= 0 or not coverage.any() or seeds.all():
        return filled

    height, width = coverage.shape
    columns = np.broadcast_to(np.arange(width, dtype=np.int32), (height, width))
    rows = np.broadcast_to(np.arange(height, dtype=np.int32)[:, None], (height, width))

    unreached = np.iinfo(np.int32).max
    seed_x = np.where(seeds, columns, -1).astype(np.int32)
    seed_y = np.where(seeds, rows, -1).astype(np.int32)
    distance = np.where(seeds, 0, unreached).astype(np.int32)

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

    reached = (~seeds) & (seed_x >= 0) & (distance <= margin * margin)
    owned = np.zeros(coverage.shape, dtype=bool)
    owned[reached] = coverage[seed_y[reached], seed_x[reached]]
    color[owned] = color[seed_y[owned], seed_x[owned]]
    return owned
