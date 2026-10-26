"""RuriRipperImporter 的接口：装了它，生成的法线与颜色就挂在按它的头发着色栈新建的材质球上，立刻能预览。

材质记录（ruri_uber_*）是内容，节点树是栈照记录编出来的：新材质 = 拿一张头发材质当模板抄它的记录、
换上生成的图、让栈照记录编一张。
"""

import functools
import importlib
import json
import os
import sys

import bpy

ADDON = "RuriRipperImporter"
SLOTS_FILE = "ImporterSlots.json"
STACK_KEY = "ruri_uber_stack"
PART_KEY = "ruri_uber_part"
IMAGES_KEY = "ruri_uber_images"
MARKER = "shiyume_hair_generated"
FAKE_RECIPE_SUFFIX = ".recipe"


@functools.cache
def slots():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SLOTS_FILE)
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _panel():
    if ADDON not in sys.modules:
        return None
    return importlib.import_module(ADDON + ".Host.Blender.material_panel")


def available():
    return _panel() is not None


def stack_of(material):
    panel = _panel()
    entry = panel.stack_of(material) if panel is not None else None
    return entry["stack"] if entry is not None else None


def is_hair(material):
    return material.get(PART_KEY) == slots()["Part"] and stack_of(material) is not None


def other_part(material):
    """材质是导入器别的部件（脸、身体、衣服……）时返回部件名，不是返回 None。"""
    if material is None or stack_of(material) is None or material.get(PART_KEY) == slots()["Part"]:
        return None
    return material.get(PART_KEY) or ""


def find_template(preferred):
    """生成用的模板头发材质：物体自己用的这张是我们生成的就回到它的原材质，不是就用它自己；
    都不行再在文件里找任何一张别人导入的头发材质（不是我们生成的）。"""
    origin = bpy.data.materials.get(preferred.get(MARKER, "")) if preferred is not None else None
    candidates = [origin or preferred] + [material for material in bpy.data.materials
                                          if material.library is None and MARKER not in material and material is not preferred]
    for material in candidates:
        if material is not None and is_hair(material):
            return stack_of(material), material
    return None, None


def _plain(value):
    if isinstance(value, bpy.types.ID):
        return value
    if hasattr(value, "to_dict"):
        return {key: _plain(item) for key, item in value.to_dict().items()}
    if hasattr(value, "to_list"):
        return [_plain(item) for item in value.to_list()]
    return value


def shader_of(stack, template):
    return str(template[stack.SHADING_KEY]["name"])


def template_image(template, slot):
    images = template.get(IMAGES_KEY)
    image = images.get(slot) if images is not None else None
    return image if isinstance(image, bpy.types.Image) else None


def build(stack, template, name, images):
    """照模板的记录新编一张材质：记录整份抄来，hair 的贴图槽换成生成的图，名字给 name。"""
    skipped = set(stack.RECORD_KEYS) | set(stack.SUPERSEDED_KEYS) | {STACK_KEY, stack.BLEND_KEY, stack.SHADING_KEY, MARKER}
    recipe = bpy.data.materials.new(name + FAKE_RECIPE_SUFFIX)
    for key in stack.RECORD_KEYS:
        recipe[key] = _plain(template[key])
    recipe[IMAGES_KEY] = dict(_plain(template[IMAGES_KEY]), **images)
    for key in template.keys():
        if key not in skipped:
            recipe[key] = _plain(template[key])
    recipe[STACK_KEY] = stack.PANEL_KEY
    try:
        material = stack.recompile(recipe)
    finally:
        bpy.data.materials.remove(recipe)
    material.name = name
    return material


def rebind(stack, material, images):
    """材质已经存在：把它的贴图槽重新指到这次的图（已经是就不动）。"""
    bound = material.get(IMAGES_KEY)
    for slot, image in images.items():
        if bound is None or bound.get(slot) is not image:
            stack.panel_write_image(material, {"name": slot}, image)


def _slot_of(label):
    base, dot, tail = label.rpartition('.')
    return base if dot and tail.isdigit() else label


def preview_node(material, slot):
    """材质树顶层读这个槽的图像节点（节点标签就是槽名，重名时带 .001 之类的后缀）。"""
    if material.node_tree is None:
        return None
    for node in material.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and _slot_of(node.label or '') == slot:
            return node
    return None
