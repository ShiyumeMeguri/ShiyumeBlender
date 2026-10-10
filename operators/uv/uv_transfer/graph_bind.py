"""着色器节点图适配层：材质里每个图像节点怎么采样——读哪个 UV 层、经怎样的仿射变换落到贴图坐标、越界与插值方式、
是不是切线空间法线。

UV 从图像节点的 Vector 输入往上游回溯：重路由与节点组原样穿过（进组走组输出，遇组输入回到组外那个组节点）；
映射节点与带常量的向量运算按仿射变换累乘；落到 UV 贴图 / 纹理坐标的 UV / 几何属性节点即得层名；
图像节点的 Vector 没接线就是渲染用的 UV 层。回溯不了的（非常量变换、非平面投影、UDIM、别的坐标源）
显式交给调用方报告，绝不当成恒等。
"""

import math

import numpy as np

_MAX_DEPTH = 64

CONVENTION_OPENGL = 'OPENGL'


class Sampling:
    """一个图像节点的采样方式。matrix 是 3x3 齐次二维仿射：贴图坐标 = matrix @ (u, v, 1)。

    normal 为 None 表示不是切线法线；否则是它的绿通道约定。depth 是节点所在的组嵌套层数（材质顶层为 0）。
    """

    def __init__(self, node, uv_name, matrix, depth, normal):
        self.node = node
        self.image = node.image
        self.label = node.label
        self.uv_name = uv_name
        self.matrix = matrix
        self.extension = node.extension
        self.nearest = node.interpolation == 'Closest'
        self.depth = depth
        self.normal = normal

    def addressing(self):
        """决定一张图被怎样读的全部参数——同一张图被几个节点读时，这一组必须一致才共用得了一张重定向图。"""
        return (self.matrix.round(9).tobytes(), self.extension, self.nearest)


def _socket(node, identifier):
    return next((socket for socket in node.inputs if socket.identifier == identifier), None)


def _constant(node, identifier):
    socket = _socket(node, identifier)
    if socket is None or socket.is_linked:
        return None
    return np.array(socket.default_value, dtype=np.float64)


def _translation(vector):
    matrix = np.identity(4)
    matrix[:3, 3] = vector
    return matrix


def _scaling(vector):
    return np.diag([vector[0], vector[1], vector[2], 1.0])


def _rotation(euler):
    """映射节点的欧拉旋转（XYZ 顺序，作用于列向量即 Rz·Ry·Rx）。"""
    x, y, z = euler
    rotate_x = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    rotate_y = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rotate_z = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    matrix = np.identity(4)
    matrix[:3, :3] = rotate_z @ rotate_y @ rotate_x
    return matrix


def _mapping_matrix(node):
    rotation = _constant(node, 'Rotation')
    scale = _constant(node, 'Scale')
    if rotation is None or scale is None:
        return None
    turn = _rotation(rotation)
    if node.vector_type == 'POINT':
        location = _constant(node, 'Location')
        if location is None:
            return None
        return _translation(location) @ turn @ _scaling(scale)
    if node.vector_type == 'TEXTURE':
        location = _constant(node, 'Location')
        if location is None or not np.all(scale != 0.0):
            return None
        return _scaling(1.0 / scale) @ turn.T @ _translation(-location)
    if node.vector_type == 'VECTOR':
        return turn @ _scaling(scale)
    return None


def _vector_math(node, linked):
    """带常量的向量运算的仿射矩阵；linked 是接着上游 UV 的那个输入标识。非仿射或两边都接线返回 None。"""
    operation = node.operation
    others = [identifier for identifier in ('Vector', 'Vector_001') if identifier != linked]
    if operation in ('ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE'):
        constant = _constant(node, others[0])
        if constant is None:
            return None
        if operation == 'ADD':
            return _translation(constant)
        if operation == 'MULTIPLY':
            return _scaling(constant)
        if operation == 'SUBTRACT':
            if linked == 'Vector':
                return _translation(-constant)
            return _translation(constant) @ _scaling(-np.ones(3))
        if linked == 'Vector' and np.all(constant != 0.0):
            return _scaling(1.0 / constant)
        return None
    if operation == 'SCALE' and linked == 'Vector':
        factor = _constant(node, 'Scale')
        return None if factor is None else _scaling(np.full(3, float(factor)))
    if operation == 'MULTIPLY_ADD' and linked in ('Vector', 'Vector_001'):
        factor = _constant(node, others[0])
        addend = _constant(node, 'Vector_002')
        if factor is None or addend is None:
            return None
        return _translation(addend) @ _scaling(factor)
    return None


def _group_output(tree):
    outputs = [node for node in tree.nodes if node.type == 'GROUP_OUTPUT']
    active = [node for node in outputs if node.is_active_output]
    return (active or outputs or [None])[0]


def _trace(socket, render_uv, stack, depth):
    """回溯一个接了线的 Vector 输入，返回 (UV 层名, 4x4 变换) 或 None。"""
    if depth > _MAX_DEPTH or not socket.is_linked:
        return None
    link = socket.links[0]
    if link.is_muted or not link.is_valid:
        return None
    node = link.from_node
    if node.mute:
        return None
    kind = node.type
    identity = np.identity(4)

    if kind == 'REROUTE':
        return _trace(node.inputs[0], render_uv, stack, depth + 1)
    if kind == 'UVMAP':
        return (node.uv_map or render_uv), identity
    if kind == 'TEX_COORD':
        return (render_uv, identity) if link.from_socket.identifier == 'UV' else None
    if kind == 'ATTRIBUTE':
        if (node.attribute_type == 'GEOMETRY' and node.attribute_name
                and link.from_socket.identifier in ('Vector', 'Color')):
            return node.attribute_name, identity
        return None
    if kind == 'MAPPING':
        matrix = _mapping_matrix(node)
        upstream = _trace(node.inputs['Vector'], render_uv, stack, depth + 1) if matrix is not None else None
        return None if upstream is None else (upstream[0], matrix @ upstream[1])
    if kind == 'VECT_MATH':
        linked = [candidate for candidate in node.inputs
                  if candidate.identifier in ('Vector', 'Vector_001', 'Vector_002')
                  and candidate.is_linked and getattr(candidate, "enabled", True)]
        if len(linked) != 1:
            return None
        matrix = _vector_math(node, linked[0].identifier)
        upstream = _trace(linked[0], render_uv, stack, depth + 1) if matrix is not None else None
        return None if upstream is None else (upstream[0], matrix @ upstream[1])
    if kind == 'GROUP':
        tree = node.node_tree
        output = _group_output(tree) if tree is not None else None
        inner = _socket(output, link.from_socket.identifier) if output is not None else None
        return None if inner is None else _trace(inner, render_uv, stack + [node], depth + 1)
    if kind == 'GROUP_INPUT':
        if not stack:
            return None
        outer = _socket(stack[-1], link.from_socket.identifier)
        return None if outer is None else _trace(outer, render_uv, stack[:-1], depth + 1)
    return None


def _reaches_uv(socket, stack, depth, visited, uv_names):
    """这个输入的上游有没有落到任何 UV 层——判定回溯不了的节点是不是本该参与重定向。"""
    if depth > _MAX_DEPTH or not socket.is_linked:
        return False
    link = socket.links[0]
    node = link.from_node
    key = (node.as_pointer(), link.from_socket.identifier, tuple(outer.as_pointer() for outer in stack))
    if key in visited:
        return False
    visited.add(key)
    kind = node.type
    if kind == 'UVMAP' or (kind == 'TEX_COORD' and link.from_socket.identifier == 'UV'):
        return True
    if kind == 'ATTRIBUTE':
        return node.attribute_name in uv_names
    if kind.startswith('TEX_') and kind != 'TEX_COORD':
        return False
    if kind == 'GROUP':
        output = _group_output(node.node_tree) if node.node_tree is not None else None
        inner = _socket(output, link.from_socket.identifier) if output is not None else None
        return inner is not None and _reaches_uv(inner, stack + [node], depth + 1, visited, uv_names)
    if kind == 'GROUP_INPUT':
        outer = _socket(stack[-1], link.from_socket.identifier) if stack else None
        return outer is not None and _reaches_uv(outer, stack[:-1], depth + 1, visited, uv_names)
    return any(_reaches_uv(upstream, stack, depth + 1, visited, uv_names)
               for upstream in node.inputs if upstream.is_linked)


def _planar(matrix):
    """4x4 变换在 z=0 的 UV 上的二维部分，取成 3x3 齐次矩阵。"""
    planar = np.identity(3)
    planar[:2, :2] = matrix[:2, :2]
    planar[:2, 2] = matrix[:2, 3]
    return planar


def _feeds_tangent_normal_map(node):
    """图像节点的颜色输出（可经重路由）直接接进切线空间的法线贴图节点。"""
    pending = [link for link in node.outputs['Color'].links]
    seen = set()
    while pending:
        link = pending.pop()
        target = link.to_node
        if target.as_pointer() in seen or link.is_muted:
            continue
        seen.add(target.as_pointer())
        if target.type == 'NORMAL_MAP' and target.space == 'TANGENT':
            return True
        if target.type == 'REROUTE':
            pending.extend(target.outputs[0].links)
    return False


class Unresolved:
    """回溯不了的图像节点；uv_dependent 表示它的坐标上游确实落到了某个 UV 层（经非仿射的路子），本该参与重定向。"""

    def __init__(self, node, uv_dependent):
        self.node = node
        self.image = node.image
        self.uv_dependent = uv_dependent


def samplings(material, render_uv, uv_names, normal_labels, normal_convention):
    """材质里每个带图的图像节点的采样方式，连同回溯不了的节点。

    返回 ([Sampling], [Unresolved])。uv_names 是网格上的 UV 层名（判断属性节点读的是不是 UV）；
    normal_labels 里列出的节点标签按 normal_convention 当切线法线，
    直接接切线空间法线贴图节点的按 OpenGL（Blender 的定义）。
    """
    found = []
    unresolved = []
    tree = material.node_tree if material is not None else None
    if tree is None:
        return found, unresolved

    def visit(tree, stack):
        for node in tree.nodes:
            if node.type == 'GROUP' and node.node_tree is not None:
                if len(stack) < _MAX_DEPTH and all(outer.node_tree != node.node_tree for outer in stack):
                    visit(node.node_tree, stack + [node])
                continue
            if node.type != 'TEX_IMAGE' or node.image is None or node.mute:
                continue
            vector = node.inputs['Vector']
            resolved = None
            if node.projection == 'FLAT' and node.image.source != 'TILED':
                if vector.is_linked:
                    resolved = _trace(vector, render_uv, stack, 0)
                else:
                    resolved = (render_uv, np.identity(4))
            if resolved is None:
                dependent = not vector.is_linked or _reaches_uv(vector, stack, 0, set(), uv_names)
                unresolved.append(Unresolved(node, dependent))
                continue
            normal = None
            if node.label and node.label in normal_labels:
                normal = normal_convention
            elif _feeds_tangent_normal_map(node):
                normal = CONVENTION_OPENGL
            found.append(Sampling(node, resolved[0], _planar(resolved[1]), len(stack), normal))

    visit(tree, [])
    return found, unresolved
