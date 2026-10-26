"""实时预览的几何一侧：头发物体上挂一个几何节点修改器，把椭球上离每个顶点最近的点的平滑法线写成顶点属性。

属性在头发物体的局部空间；椭球没了（修改器的对象为空或椭球被删）属性就是零向量，材质一侧据此退回贴图。
"""

import functools
import os

import bpy

from ..node_graph import builder
from .preview_names import ATTRIBUTE
from .preview_names import MARKER

SPEC_FILE = "PreviewGeometry.json"
STORE_NODE = "Store"
ELLIPSOID_SOCKET = "Ellipsoid"


@functools.cache
def _spec():
    return builder.load(os.path.dirname(os.path.abspath(__file__)), SPEC_FILE)


def _group():
    group = bpy.data.node_groups.get(_spec()["Name"])
    if group is None:
        group = builder.build(_spec())
        group.nodes[STORE_NODE].inputs["Name"].default_value = ATTRIBUTE
    return group


def _ellipsoid_identifier(group):
    for item in group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == ELLIPSOID_SOCKET:
            return item.identifier
    raise KeyError(ELLIPSOID_SOCKET)


def attach(obj, ellipsoid):
    group = _group()
    modifier = obj.modifiers.get(MARKER)
    if modifier is None:
        modifier = obj.modifiers.new(MARKER, 'NODES')
        modifier.show_expanded = False
    if modifier.node_group is not group:
        modifier.node_group = group
    socket = getattr(modifier.properties.inputs, _ellipsoid_identifier(group))
    if socket.value is not ellipsoid:
        socket.value = ellipsoid


def strip(keep):
    """除了 keep 里的物体，其余物体上的预览修改器全部摘掉；没有修改器再用就连节点组一起删。"""
    for obj in bpy.data.objects:
        modifier = obj.modifiers.get(MARKER)
        if modifier is not None and obj not in keep:
            obj.modifiers.remove(modifier)
    group = bpy.data.node_groups.get(_spec()["Name"])
    if group is not None and group.users == 0:
        bpy.data.node_groups.remove(group)
