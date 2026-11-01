"""RuriRipperImporter 的接口：装了它，生成的法线与颜色就挂在按它的头发着色栈新建的材质球上，立刻能预览。

材质记录（ruri_uber_*）是内容，节点树是栈照记录编出来的：新材质 = 取一份记录、换上生成的图、让栈照记录编一张；
文件里有导入的头发材质就抄它的记录，一张都没有就取栈声明的游戏缺省。
"""

import functools
import json
import os
import sys

import bpy

PANEL_SUFFIX = ".Host.Blender.material_panel"
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


def panel():
    for name, module in sys.modules.items():
        if name.endswith(PANEL_SUFFIX) and module is not None:
            return module
    return None


def stack():
    """导入器注册的头发着色栈（栈键在 ImporterSlots.json），没装导入器或它没注册这个栈返回 None。"""
    host = panel()
    return host.stack_by_key(slots()["Stack"]) if host is not None else None


def available():
    return stack() is not None


def stack_of(material):
    host = panel()
    entry = host.stack_of(material) if host is not None else None
    return entry["stack"] if entry is not None else None


def is_hair(material):
    claimed = stack_of(material)
    return claimed is not None and claimed is stack() and material.get(PART_KEY) == slots()["Part"]


def find_template(preferred):
    """生成用的模板头发材质：物体自己用的这张是我们生成的就回到它的原材质，不是就用它自己；
    都不行再在文件里找任何一张别人导入的头发材质（不是我们生成的）；一张都没有返回 None。"""
    origin = bpy.data.materials.get(preferred.get(MARKER, "")) if preferred is not None else None
    candidates = [origin or preferred] + [material for material in bpy.data.materials
                                          if material.library is None and MARKER not in material and material is not preferred]
    for material in candidates:
        if material is not None and is_hair(material):
            return material
    return None


def _plain(value):
    if isinstance(value, bpy.types.ID):
        return value
    if hasattr(value, "to_dict"):
        return {key: _plain(item) for key, item in value.to_dict().items()}
    if hasattr(value, "to_list"):
        return [_plain(item) for item in value.to_list()]
    return value


def template_image(template, slot):
    images = template.get(IMAGES_KEY) if template is not None else None
    image = images.get(slot) if images is not None else None
    return image if isinstance(image, bpy.types.Image) else None


def copied_record(stack, template, images):
    """模板的记录整份抄来，贴图槽换成生成的图；记录以外的键（基座骨名之类）也跟着抄，栈自己写的与我们的标记除外。"""
    skipped = set(stack.RECORD_KEYS) | set(stack.SUPERSEDED_KEYS) | {STACK_KEY, stack.BLEND_KEY, stack.SHADING_KEY, MARKER}
    record = {key: _plain(template[key]) for key in stack.RECORD_KEYS}
    record[IMAGES_KEY] = dict(record[IMAGES_KEY], **images)
    record.update({key: _plain(template[key]) for key in template.keys() if key not in skipped})
    return record


def default_record(stack, images):
    """栈声明的游戏缺省记录：参数取作者模式的缺省，描边那一趟按部件声明的标签记上，贴图只有给的这些。"""
    part = slots()["Part"]
    meta = stack.PART_META[part]
    defaults = stack.SCHEMA_DEFAULTS[part]
    return {
        PART_KEY: part,
        IMAGES_KEY: dict(images),
        "ruri_uber_floats": {name: float(value[0]) for name, value in defaults.items() if len(value) == 1},
        "ruri_uber_colors": {name: [float(component) for component in value] for name, value in defaults.items() if len(value) != 1},
        "ruri_uber_st": {},
        "ruri_uber_disabled_passes": [],
        "ruri_uber_shader_passes": list(meta["outline"]),
        "ruri_uber_shader_guid": "",
        "ruri_uber_shader": meta["shader"],
    }


def build(stack, template, name, images):
    """新编一张材质：有模板就抄它的记录，没有就取栈声明的游戏缺省；hair 的贴图槽换成生成的图，名字给 name。"""
    record = default_record(stack, images) if template is None else copied_record(stack, template, images)
    recipe = bpy.data.materials.new(name + FAKE_RECIPE_SUFFIX)
    try:
        for key, value in record.items():
            recipe[key] = value
        recipe[STACK_KEY] = stack.PANEL_KEY
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
