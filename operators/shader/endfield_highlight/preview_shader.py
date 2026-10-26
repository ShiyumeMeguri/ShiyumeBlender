"""实时预览的材质一侧：在分离法线贴图节点的输出后串一个预览节点组，属性有效时它的 B、A 顶替贴图的 B、A。

只动材质树顶层这一个图像节点和它的消费者；摘掉时把消费者接回图像节点，材质回到原样。
"""

import functools
import os

import bpy

from ..endfield_target import importer
from ..node_graph import builder
from .preview_names import ATTRIBUTE
from .preview_names import MARKER

SPEC_FILE = "PreviewShader.json"
ATTRIBUTE_NODE = "Attribute"
OUTPUTS = ("Color", "Alpha")
NODE_OFFSET = (260.0, 0.0)


@functools.cache
def _spec():
    return builder.load(os.path.dirname(os.path.abspath(__file__)), SPEC_FILE)


def _group():
    group = bpy.data.node_groups.get(_spec()["Name"])
    if group is None:
        group = builder.build(_spec())
        group.nodes[ATTRIBUTE_NODE].attribute_name = ATTRIBUTE
    return group


def wire(material):
    """把预览节点组串进材质；已经串好返回 True，材质里找不到分离法线贴图节点或它没有接到任何地方返回 False。"""
    tree = material.node_tree
    if tree is None:
        return False
    if MARKER in tree.nodes:
        return True
    image_node = importer.preview_node(material, importer.slots()["NormalSlot"])
    if image_node is None:
        return False
    consumers = {name: [link.to_socket for link in image_node.outputs[name].links] for name in OUTPUTS}
    if not any(consumers.values()):
        return False
    node = tree.nodes.new('ShaderNodeGroup')
    node.name = MARKER
    node.label = MARKER
    node.node_tree = _group()
    node.location = (image_node.location[0] + NODE_OFFSET[0], image_node.location[1] + NODE_OFFSET[1])
    for name in OUTPUTS:
        tree.links.new(image_node.outputs[name], node.inputs[name])
    for name in OUTPUTS:
        for socket in consumers[name]:
            tree.links.new(node.outputs[name], socket)
    return True


def _unwire(tree, node):
    feeding = node.inputs[OUTPUTS[0]].links
    if feeding:
        source = feeding[0].from_node
        for name in OUTPUTS:
            for link in list(node.outputs[name].links):
                tree.links.new(source.outputs[name], link.to_socket)
    tree.nodes.remove(node)


def strip(keep):
    """除了 keep 里的材质，其余材质里的预览节点全部摘掉并把消费者接回；没有节点再用就把节点组一起删。"""
    for material in bpy.data.materials:
        tree = material.node_tree
        if tree is None:
            continue
        node = tree.nodes.get(MARKER)
        if node is not None and material not in keep:
            _unwire(tree, node)
    group = bpy.data.node_groups.get(_spec()["Name"])
    if group is not None and group.users == 0:
        bpy.data.node_groups.remove(group)
