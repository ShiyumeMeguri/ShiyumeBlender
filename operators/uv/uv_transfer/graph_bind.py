"""着色器节点图适配层：找出真正采样某个 UV 层的图像纹理节点。"""

_MAX_VECTOR_DEPTH = 16


def _resolve_uv(socket, render_uv, depth=0):
    """回溯 Vector 输入，返回该节点实际采样的 UV 层名；判定不了返回 None。"""
    if not socket.links:
        return render_uv
    if depth >= _MAX_VECTOR_DEPTH:
        return None

    link = socket.links[0]
    node = link.from_node

    if node.type == 'UVMAP':
        return node.uv_map or render_uv
    if node.type == 'ATTRIBUTE':
        return node.attribute_name or None
    if node.type == 'TEX_COORD':
        return render_uv if link.from_socket.name == 'UV' else None
    if node.type == 'MAPPING':
        return _resolve_uv(node.inputs['Vector'], render_uv, depth + 1)
    if node.type == 'REROUTE':
        return _resolve_uv(node.inputs[0], render_uv, depth + 1)
    return None


def _walk_trees(root_tree):
    """深度遍历节点树，含节点组，返回所有节点树（去重）。"""
    trees = []
    pending = [root_tree]
    seen = set()
    while pending:
        tree = pending.pop()
        if tree is None or tree.as_pointer() in seen:
            continue
        seen.add(tree.as_pointer())
        trees.append(tree)
        for node in tree.nodes:
            if node.type == 'GROUP':
                pending.append(node.node_tree)
    return trees


def image_nodes_using_uv(material, uv_name, render_uv):
    """收集材质里采样 uv_name 的图像纹理节点，返回 [(node, image), ...]。

    第二个返回值是无法判定 UV 来源的节点数，交由调用方显式报告。
    """
    bound = []
    unresolved = 0

    if material is None or not material.use_nodes or material.node_tree is None:
        return bound, unresolved

    for tree in _walk_trees(material.node_tree):
        for node in tree.nodes:
            if node.type != 'TEX_IMAGE' or node.image is None:
                continue
            resolved = _resolve_uv(node.inputs['Vector'], render_uv)
            if resolved is None:
                unresolved += 1
            elif resolved == uv_name:
                bound.append((node, node.image))

    return bound, unresolved
