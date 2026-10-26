"""按数据描述搭节点树：描述是 JSON（接口插槽、节点、连线），这里只有一个通用解释器，加新图只加数据。

插槽用标识符或名字指定（重名的插槽用标识符，如数学节点的 Value_001）；节点按描述里的 Name 取名。
"""

import json
import os

import bpy


def load(directory, file_name):
    with open(os.path.join(directory, file_name), encoding="utf-8") as stream:
        return json.load(stream)


def _socket(sockets, selector):
    for socket in sockets:
        if socket.identifier == selector:
            return socket
    for socket in sockets:
        if socket.name == selector:
            return socket
    raise KeyError("没有插槽 '%s'：%s" % (selector, [(socket.name, socket.identifier) for socket in sockets]))


def _interface(tree, entries):
    for entry in entries:
        socket = tree.interface.new_socket(name=entry["Name"], in_out=entry["InOut"], socket_type=entry["SocketType"])
        if "Default" in entry:
            socket.default_value = entry["Default"]


def _node(tree, entry):
    node = tree.nodes.new(entry["Type"])
    node.name = entry["Name"]
    node.label = entry.get("Label", entry["Name"])
    node.location = entry.get("Location", (0.0, 0.0))
    for name, value in entry.get("Properties", {}).items():
        setattr(node, name, value)
    for selector, value in entry.get("Inputs", {}).items():
        _socket(node.inputs, selector).default_value = value
    return node


def build(spec):
    """按描述新建一棵节点树（同名的先由调用方清掉）。"""
    tree = bpy.data.node_groups.new(spec["Name"], spec["TreeType"])
    _interface(tree, spec["Interface"])
    nodes = {entry["Name"]: _node(tree, entry) for entry in spec["Nodes"]}
    for source, output, target, input_name in spec["Links"]:
        tree.links.new(_socket(nodes[source].outputs, output), _socket(nodes[target].inputs, input_name))
    return tree
