"""平滑权重的纯数值内核：复刻 Blender 的 vgroup_smooth_subset，加上保持尖锐特征与保持权重总量，
再把结果最优地投影到「每顶点至多 N 个影响」。

平滑本身按组独立（雅可比迭代），所以先在稀疏表示里不受限地平滑到底，真正的 N 限制只在最后落一次：
每个顶点取权重最大的 N 个组，并把其余权重的质量按欧氏距离最小的方式摊给它们（单纯形投影，权重不超过 1），
这是「N 稀疏 + 质量守恒」约束下离不受限平滑结果最近的点，中途不截断，所以小权重照样能扩散。
选哪 N 个组按「邻域平滑过一次的权重」排序，相邻顶点因此倾向于挑同一批组，不会因为第 N 与第 N+1 名接近而逐顶点乱跳。

保持尖锐特征：每条边的传导系数由平滑开始前两端顶点权重的相对差异决定（0 = 完全相同，1 = 完全不相交，不要求权重归一化），
以这片区域自己的典型差异为尺度，只有真正突出的断崖被保护，普通的坑洼照常被磨圆；没有断崖的地方系数为 1，与自带平滑完全一致。

保持权重总量：自带平滑会让权重总量衰减，限制 N 时也会丢质量；这里把每个顶点的总量恢复成平滑前的值，平滑只重新分配，不削弱影响力。
"""

import numpy


PRUNE_THRESHOLD = 1.0e-7
FEATURE_SHARPNESS = 4.0
FEATURE_QUANTILE = 0.9
PROJECTION_STEPS = 48
RESCALE_STEPS = 6
SUPPORT_SCORE_FACTOR = 0.5


class SmoothingGraph:
    """哪些顶点会被改写、哪些顶点的权重可以被读到，以及由此得到的有向邻接。"""

    def __init__(self, vertex_count, edges, writable, readable):
        first = edges[:, 0]
        second = edges[:, 1]
        forward = writable[first] & readable[second]
        backward = writable[second] & readable[first]
        self.vertex_count = vertex_count
        self.destination = numpy.concatenate((first[forward], second[backward]))
        self.source = numpy.concatenate((second[forward], first[backward]))
        self.pair_count = len(self.destination)
        self.degree = numpy.bincount(self.destination, minlength=vertex_count)
        self.used = self.degree > 0
        self.out_pair = numpy.argsort(self.source, kind="stable")
        self.out_destination = self.destination[self.out_pair]
        self.out_offsets = numpy.concatenate(
            ([0], numpy.cumsum(numpy.bincount(self.source, minlength=vertex_count))))
        self.in_pair = numpy.argsort(self.destination, kind="stable")
        self.in_source = self.source[self.in_pair]
        self.in_offsets = numpy.concatenate(([0], numpy.cumsum(self.degree)))


def _expand_ranges(offsets, items):
    """对每个 item，展开 offsets[item]..offsets[item+1] 里的全部位置；返回 (属于第几个 item, 位置)。"""
    counts = offsets[items + 1] - offsets[items]
    owner = numpy.repeat(numpy.arange(len(items)), counts)
    starts = numpy.cumsum(counts) - counts
    position = numpy.arange(len(owner)) - numpy.repeat(starts, counts) + numpy.repeat(offsets[items], counts)
    return owner, position


def lookup(keys, values, query):
    """keys 升序；返回 query 对应的值，缺席为 0。"""
    if len(keys) == 0:
        return numpy.zeros(len(query))
    index = numpy.minimum(numpy.searchsorted(keys, query), len(keys) - 1)
    found = keys[index] == query
    return numpy.where(found, values[index], 0.0)


def _pair_triples(graph, group_count, keys, values):
    """每条有向邻接 (目标 i ← 来源 j) 上，每个 i 或 j 有权重的组一条 (目标, 组, i 的权重, j 的权重, 邻接编号)。"""
    rows = keys // group_count
    groups = keys % group_count
    positive = values > 0.0

    source_rows = rows[positive]
    source_groups = groups[positive]
    source_values = values[positive]
    owner, position = _expand_ranges(graph.out_offsets, source_rows)
    target_a = graph.out_destination[position]
    group_a = source_groups[owner]
    other_a = source_values[owner]
    own_a = lookup(keys, values, target_a * group_count + group_a)
    pair_a = graph.out_pair[position]

    used_entries = positive & graph.used[rows]
    base_rows = rows[used_entries]
    base_groups = groups[used_entries]
    base_values = values[used_entries]
    owner, position = _expand_ranges(graph.in_offsets, base_rows)
    neighbour = graph.in_source[position]
    group_b = base_groups[owner]
    other_b = lookup(keys, values, neighbour * group_count + group_b)
    missing = other_b <= 0.0
    target_b = base_rows[owner][missing]
    group_b = group_b[missing]
    own_b = base_values[owner][missing]
    pair_b = graph.in_pair[position][missing]
    other_b = numpy.zeros(len(own_b))

    return (numpy.concatenate((target_a, target_b)),
            numpy.concatenate((group_a, group_b)),
            numpy.concatenate((own_a, own_b)),
            numpy.concatenate((other_a, other_b)),
            numpy.concatenate((pair_a, pair_b)))


def edge_conductance(graph, group_count, keys, values, threshold):
    """每条有向邻接的传导系数。两端权重的相对差异 Σ|a-b| / Σ(a+b)（不要求权重归一化）以这片区域自己的典型差异
    （第 FEATURE_QUANTILE 分位）为尺度：差异远小于 threshold 倍的尺度时传导为 1，明显超过时趋近 0，
    所以只保护这片区域里真正突出的断崖，普通的坑洼照常被磨圆。threshold <= 0 表示不保护。"""
    if threshold <= 0.0:
        return numpy.ones(graph.pair_count)
    _target, _group, own, other, pair = _pair_triples(graph, group_count, keys, values)
    difference = numpy.bincount(pair, numpy.abs(own - other), minlength=graph.pair_count)
    magnitude = numpy.bincount(pair, own + other, minlength=graph.pair_count)
    distance = difference / numpy.where(magnitude > 0.0, magnitude, 1.0)
    active = distance[distance > 0.0]
    if len(active) == 0:
        return numpy.ones(graph.pair_count)
    scale = threshold * numpy.quantile(active, FEATURE_QUANTILE)
    return numpy.exp(-(distance / scale) ** FEATURE_SHARPNESS)


def smooth_step(graph, group_count, keys, values, factor, expand, conductance):
    """一轮平滑。keys = 顶点 * group_count + 组号（升序），values 为对应权重。"""
    inverse_factor = 1.0 - factor
    expand_sign = int(numpy.sign(expand))
    magnitude = abs(expand)
    inverse_magnitude = 1.0 - magnitude

    rows = keys // group_count
    target, group, own, other, pair = _pair_triples(graph, group_count, keys, values)
    strength = conductance[pair]

    if expand_sign == 1:
        modified = other < own
    elif expand_sign == -1:
        modified = other > own
    else:
        modified = numpy.zeros(len(other), dtype=bool)
    blended = numpy.where(modified, own * magnitude + other * inverse_magnitude, other)
    scale = numpy.where(modified, inverse_magnitude, 1.0)
    contribution = strength * scale * blended

    pair_keys = target * group_count + group
    unique_keys, inverse = numpy.unique(pair_keys, return_inverse=True)
    accumulated = numpy.bincount(inverse, contribution, minlength=len(unique_keys))
    modified_strength = numpy.bincount(inverse, strength * modified, minlength=len(unique_keys))
    unique_rows = unique_keys // group_count
    previous = lookup(keys, values, unique_keys)
    total = numpy.bincount(graph.destination, conductance, minlength=graph.vertex_count)[unique_rows] \
        - magnitude * modified_strength
    safe_total = numpy.where(total > 0.0, total, 1.0)
    smoothed = previous * inverse_factor + factor * accumulated / safe_total
    smoothed = numpy.where(total > 0.0, numpy.clip(smoothed, 0.0, 1.0), previous)

    untouched = ~graph.used[rows]
    merged_keys = numpy.concatenate((keys[untouched], unique_keys))
    merged_values = numpy.concatenate((values[untouched], smoothed))
    order = numpy.argsort(merged_keys, kind="stable")
    merged_keys = merged_keys[order]
    merged_values = merged_values[order]
    keep = merged_values > PRUNE_THRESHOLD
    return merged_keys[keep], merged_values[keep]


def smooth(graph, group_count, keys, values, factor, repeat, expand, feature_threshold):
    order = numpy.argsort(keys, kind="stable")
    keys = keys[order]
    values = values[order]
    conductance = edge_conductance(graph, group_count, keys, values, feature_threshold)
    for _step in range(repeat):
        keys, values = smooth_step(graph, group_count, keys, values, factor, expand, conductance)
    return keys, values


def support_scores(graph, group_count, keys, values):
    """挑选保留哪些组时用的排序分数：权重在邻域里再平滑一次。返回 (keys, 分数)。"""
    order = numpy.argsort(keys, kind="stable")
    return smooth_step(graph, group_count, keys[order], values[order],
                       SUPPORT_SCORE_FACTOR, 0.0, numpy.ones(graph.pair_count))


def _project_capped(top, mass):
    """把每行 top 投影到 {0 <= w <= 1, 总和 = mass} 上的欧氏最近点：w = clip(top - τ, 0, 1)，τ 用二分求。"""
    low = top.min(axis=1) - 1.0
    high = top.max(axis=1)
    for _step in range(PROJECTION_STEPS):
        middle = 0.5 * (low + high)
        total = numpy.clip(top - middle[:, None], 0.0, 1.0).sum(axis=1)
        too_much = total > mass
        low = numpy.where(too_much, middle, low)
        high = numpy.where(too_much, high, middle)
    return numpy.clip(top - (0.5 * (low + high))[:, None], 0.0, 1.0)


def _rescale_capped(rows, values, target, vertex_count):
    """每个顶点按比例缩放到目标总量，权重封顶 1，被封顶的多出来的量摊给没封顶的。"""
    for _step in range(RESCALE_STEPS):
        saturated = values >= 1.0
        fixed_mass = numpy.bincount(rows, values * saturated, minlength=vertex_count)
        free_mass = numpy.bincount(rows, values * ~saturated, minlength=vertex_count)
        remaining = numpy.maximum(target - fixed_mass, 0.0)
        ratio = numpy.where(free_mass > 0.0, remaining / numpy.where(free_mass > 0.0, free_mass, 1.0), 1.0)
        values = numpy.where(saturated, values, numpy.minimum(values * ratio[rows], 1.0))
    return values


def limit_influences(vertex_count, rows, groups, values, ranking, limit, mass):
    """每个顶点至多保留 limit 个影响。ranking 为每条记录挑组用的分数（可以挑到当前权重为 0 的组）；
    mass 为每个顶点的目标权重总和（None 则沿用各自当前的总和）。
    超限的顶点取分数最高的 limit 个组，再按封顶单纯形投影把总和补回 mass；没超限的顶点只在给了 mass 时按比例缩放。"""
    own_mass = numpy.bincount(rows, values, minlength=vertex_count)
    target_mass = own_mass if mass is None else mass
    positive_counts = numpy.bincount(rows[values > 0.0], minlength=vertex_count)
    heavy_row = positive_counts > limit

    order = numpy.lexsort((-ranking, rows))
    rows = rows[order]
    groups = groups[order]
    values = values[order]
    counts = numpy.bincount(rows, minlength=vertex_count)
    starts = numpy.cumsum(counts) - counts
    rank = numpy.arange(len(rows)) - starts[rows]

    new_values = values.copy()
    light = ~heavy_row[rows]
    if mass is not None:
        new_values[light] = _rescale_capped(rows[light], values[light], target_mass, vertex_count)

    heavy = numpy.flatnonzero(heavy_row)
    if len(heavy):
        top_index = starts[heavy][:, None] + numpy.arange(limit)[None, :]
        projected = _project_capped(values[top_index], numpy.minimum(target_mass[heavy], float(limit)))
        new_values[top_index.ravel()] = projected.ravel()

    keep = numpy.where(heavy_row[rows], rank < limit, True) & (new_values > 0.0)
    return rows[keep], groups[keep], new_values[keep]
