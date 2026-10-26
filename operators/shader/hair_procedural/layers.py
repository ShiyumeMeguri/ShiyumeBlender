"""头发预览层：每一层是一张带标记的预览材质，参数就是它的预览节点组里那个程序节点组实例的输入。

整头发一层，叫基础层：头发每张原材质（头发、羽毛这些）各有一张基础层材质，替换原材质占着原来的槽，但它们共用同一个预览节点组，
所以参数只有一份，不同材质的头发颜色与纹路天然一致；编辑模式里选一批面再来一层，叫局部层，追加一个新槽、选中的面改指向它，
局部层有自己的预览节点组。层的状态全在数据里（材质上的标记与指向原材质、所属物体的指针），所以存盘重开、撤销之后都还在，
取消和烘焙只是照着这些标记把槽与面还原。
"""

import bmesh
import bpy
import numpy as np

from . import procedural

MARKER = "shiyume_hair_layer"
ORIGINAL = "shiyume_hair_original"
OWNER = "shiyume_hair_owner"
PREVIEW_NODE = "ShiyumeHairPreview"
GENERATOR_NODE = "ShiyumeHairGenerator"


def is_layer(material):
    return material is not None and MARKER in material


def is_local(material):
    return material.get(OWNER) is not None


def original_of(material):
    return material.get(ORIGINAL)


def preview_group(material):
    node = material.node_tree.nodes.get(PREVIEW_NODE) if material.node_tree is not None else None
    group = node.node_tree if node is not None else None
    return group if procedural.is_current(group) else None


def generator_of(material):
    group = preview_group(material)
    return group.nodes.get(GENERATOR_NODE) if group is not None else None


def shared_group():
    """已有的基础层共用的预览节点组，没有基础层返回 None。"""
    for material in all_layers():
        if not is_local(material) and preview_group(material) is not None:
            return preview_group(material)
    return None


def all_layers():
    return [material for material in bpy.data.materials if is_layer(material)]


def active_layer(context):
    obj = context.active_object
    material = obj.active_material if obj is not None and obj.type == 'MESH' else None
    return material if is_layer(material) else None


def objects_with_layers():
    return [obj for obj in bpy.data.objects if obj.type == 'MESH' and any(is_layer(slot.material) for slot in obj.material_slots)]


def base_slot(obj, original):
    """物体里占着这张原材质的基础层所在的槽下标，没有返回 None。"""
    for index, slot in enumerate(obj.material_slots):
        if is_layer(slot.material) and not is_local(slot.material) and original_of(slot.material) is original:
            return index
    return None


def slot_of(obj, layer):
    for index, slot in enumerate(obj.material_slots):
        if slot.material is layer:
            return index
    return None


def selected_face_slots(obj):
    """编辑模式里选中的面各自的材质槽下标集合。"""
    bm = bmesh.from_edit_mesh(obj.data)
    return {face.material_index for face in bm.faces if face.select and not face.hide}


def release_local(obj, index):
    """局部层占着的槽 index 删掉，它的面回到所属基础层的槽（找不到就回到第一个槽）。"""
    mesh = obj.data
    indices = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", indices)
    parent = base_slot(obj, original_of(obj.material_slots[index].material))
    indices[indices == index] = 0 if parent is None else parent
    mesh.polygons.foreach_set("material_index", indices)
    mesh.materials.pop(index=index)


def restore(obj):
    """把物体还原：局部层的面回到所属基础层的槽、槽删掉；基础层的槽换回原材质。预览材质本身留给调用方删。"""
    for index in reversed(range(len(obj.material_slots))):
        layer = obj.material_slots[index].material
        if not is_layer(layer):
            continue
        if is_local(layer):
            release_local(obj, index)
        else:
            obj.material_slots[index].material = original_of(layer)
