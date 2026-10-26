"""节点后端：把着色器数学的图逐节点搭成一棵 Blender 着色器节点组，节点与 numpy 后端的原语一一对应。

数学原语是数学节点（常量直接写在输入的默认值上），哈希噪声是白噪声节点，查表是色带节点（值放在 Alpha 里）。
组的接口输入按描述建：名字（Label 优先）、类型（Float、Integer、Boolean、Color，颜色拆成三个分量）、Float 的子类型（如 FACTOR）、默认、范围、说明、分组面板；输出都是浮点。
"""

import bpy

from . import language
from . import primitives

NOISE_NODE = 'ShaderNodeTexWhiteNoise'
MATH_NODE = 'ShaderNodeMath'
RAMP_NODE = 'ShaderNodeValToRGB'
SOCKET_TYPES = {"Float": 'NodeSocketFloat', "Integer": 'NodeSocketInt', "Boolean": 'NodeSocketBool', "Color": 'NodeSocketColor'}
COLOR_CHANNELS = ("Red", "Green", "Blue")
COLUMN_WIDTH = 220.0
ROW_HEIGHT = 90.0


def label_of(entry):
    return entry.get("Label", entry["Name"])


def _interface(tree, panels, inputs, outputs):
    panel_items = {panel["Name"]: tree.interface.new_panel(panel["Name"], default_closed=panel.get("Closed", False)) for panel in panels}
    for entry in inputs:
        kind = entry.get("Type", "Float")
        socket = tree.interface.new_socket(name=label_of(entry), in_out='INPUT', socket_type=SOCKET_TYPES[kind], parent=panel_items.get(entry.get("Panel")))
        if "Subtype" in entry:
            socket.subtype = entry["Subtype"]
        socket.default_value = (*entry["Default"], 1.0) if kind == "Color" else entry["Default"]
        if kind in ("Float", "Integer"):
            socket.min_value = entry["Min"]
            socket.max_value = entry["Max"]
        socket.description = entry.get("Description", "")
    for name in outputs:
        tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type='NodeSocketFloat')


def _ramp(node, table):
    ramp = node.color_ramp
    ramp.interpolation = 'LINEAR'
    positions = list(table.positions)
    ramp.elements[0].position = positions[0]
    ramp.elements[1].position = positions[-1]
    for position in positions[1:-1]:
        ramp.elements.new(position)
    for element, value in zip(ramp.elements, table.values):
        element.alpha = value


class _Placer:
    def __init__(self):
        self.rows = {}

    def place(self, depth):
        row = self.rows.get(depth, 0)
        self.rows[depth] = row + 1
        return (depth * COLUMN_WIDTH, -row * ROW_HEIGHT)


def build_group(program, name, inputs, outputs, panels=()):
    """inputs 是接口输入的描述列表（Name 是程序里的输入名；Label、Type、Default、Min、Max、Description、Panel、Components 见模块说明），
    outputs 是输出名，panels 是分组面板（Name、Closed）；返回新建的节点组。"""
    tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    _interface(tree, panels, inputs, outputs)
    group_input = tree.nodes.new('NodeGroupInput')
    group_output = tree.nodes.new('NodeGroupOutput')
    group_input.location = (-COLUMN_WIDTH, 0.0)
    input_sockets = {}
    for entry in inputs:
        if entry.get("Type") == "Color":
            separate = tree.nodes.new('ShaderNodeSeparateColor')
            separate.location = (-COLUMN_WIDTH / 2.0, -ROW_HEIGHT * len(input_sockets))
            tree.links.new(group_input.outputs[label_of(entry)], separate.inputs["Color"])
            for component, channel in zip(entry["Components"], COLOR_CHANNELS):
                input_sockets[component] = separate.outputs[channel]
        else:
            input_sockets[entry["Name"]] = group_input.outputs[label_of(entry)]
    placer = _Placer()
    depth = {}
    sources = {}

    def connect(target, argument):
        kind, source = sources[argument]
        if kind == language.CONSTANT:
            target.default_value = source
        else:
            tree.links.new(source, target)

    def make(index, node):
        depth[index] = 1 + max((depth[argument] for argument in node.args if sources[argument][0] != language.CONSTANT), default=0)
        location = placer.place(depth[index])
        if node.op == language.TABLE:
            created = tree.nodes.new(RAMP_NODE)
            _ramp(created, program.tables[node.value])
            connect(created.inputs["Fac"], node.args[0])
            output = created.outputs["Alpha"]
        elif node.op in primitives.NOISE_ARITY:
            count = primitives.NOISE_ARITY[node.op]
            created = tree.nodes.new(NOISE_NODE)
            created.noise_dimensions = "%dD" % count
            if count == 1:
                connect(created.inputs["W"], node.args[0])
            else:
                combine = tree.nodes.new('ShaderNodeCombineXYZ')
                combine.location = (location[0] - COLUMN_WIDTH / 2.0, location[1])
                combine.hide = True
                for axis, argument in zip(("X", "Y", "Z"), node.args):
                    connect(combine.inputs[axis], argument)
                tree.links.new(combine.outputs["Vector"], created.inputs["Vector"])
            output = created.outputs["Value"]
        else:
            definition = primitives.definitions()[node.op]
            created = tree.nodes.new(MATH_NODE)
            created.operation = definition["Operation"]
            for position, argument in enumerate(node.args):
                connect(created.inputs[position], argument)
            for position, value in definition.get("Fixed", {}).items():
                created.inputs[int(position)].default_value = value
            output = created.outputs["Value"]
        created.location = location
        created.hide = True
        sources[index] = ("node", output)

    for index, node in enumerate(program.nodes):
        if node.op == language.CONSTANT:
            sources[index] = (language.CONSTANT, node.value)
        elif node.op == language.INPUT:
            sources[index] = ("node", input_sockets[node.value])
            depth[index] = 0
        else:
            make(index, node)
    last = max(depth.values(), default=0) + 1
    group_output.location = (last * COLUMN_WIDTH, 0.0)
    for output_name, index in program.outputs.items():
        connect(group_output.inputs[output_name], index)
    return tree
