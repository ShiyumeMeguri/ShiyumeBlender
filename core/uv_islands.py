"""UV 孤岛收集(bmesh,编辑模式)。

桶式 O(L) 连通:把每条 loop 按 (顶点号, 量化UV) 放进桶,同桶的面即 UV 相连,
再对面做一次泛洪。不做逐对 epsilon 距离比较,复杂度与网格规模线性。
"""

_QUANT = 1.0e5  # UV 量化精度 1e-5


def _loop_key(loop, uv_layer):
    uv = loop[uv_layer].uv
    return (loop.vert.index, round(uv.x * _QUANT), round(uv.y * _QUANT))


def collect_islands(bm, uv_layer):
    """收集全部 UV 孤岛,每个孤岛返回其所有 loop 的列表。"""
    key_to_faces = {}
    for face in bm.faces:
        for loop in face.loops:
            key_to_faces.setdefault(_loop_key(loop, uv_layer), []).append(face)

    visited = set()
    islands = []
    for seed_face in bm.faces:
        if seed_face.index in visited:
            continue
        visited.add(seed_face.index)
        island_loops = []
        stack = [seed_face]
        while stack:
            face = stack.pop()
            for loop in face.loops:
                island_loops.append(loop)
                for neighbor in key_to_faces[_loop_key(loop, uv_layer)]:
                    if neighbor.index not in visited:
                        visited.add(neighbor.index)
                        stack.append(neighbor)
        islands.append(island_loops)
    return islands


def island_bounds(loops, uv_layer):
    """孤岛包围盒 (min_u, min_v, max_u, max_v)。"""
    first = loops[0][uv_layer].uv
    min_u = max_u = first.x
    min_v = max_v = first.y
    for loop in loops:
        uv = loop[uv_layer].uv
        if uv.x < min_u:
            min_u = uv.x
        elif uv.x > max_u:
            max_u = uv.x
        if uv.y < min_v:
            min_v = uv.y
        elif uv.y > max_v:
            max_v = uv.y
    return min_u, min_v, max_u, max_v
