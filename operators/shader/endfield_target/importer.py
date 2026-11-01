"""RuriRipperImporter 的接口：装了它，生成的法线与颜色就挂在按它的头发着色栈新建的材质球上，立刻能预览。

材质记录（ruri_uber_*）是内容，节点树是栈照记录编出来的：新材质 = 取一份记录、换上生成的图、让栈照记录编一张。
记录抄文件里一张导入的头发材质的；文件里一张都没有，就抄本机声明的头发模板（presets 里的 HairTemplate.json，
写着模板 .blend 与里面的头发材质名）：只带它的参数与公共贴图，角色自己的贴图（各槽的 UV 只对它自己的网格有意义）一张不带。
"""

import functools
import json
import os
import shutil
import sys

import bpy

PANEL_SUFFIX = ".Host.Blender.material_panel"
SLOTS_FILE = "ImporterSlots.json"
PRESET_FILE = "HairTemplate.json"
STACK_KEY = "ruri_uber_stack"
PART_KEY = "ruri_uber_part"
IMAGES_KEY = "ruri_uber_images"
MARKER = "shiyume_hair_generated"
FAKE_RECIPE_SUFFIX = ".recipe"


class TemplateError(Exception):
    pass


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


def preset_path():
    return os.path.join(bpy.utils.user_resource('SCRIPTS', path="presets"), __package__.split(".")[0], PRESET_FILE)


def _declared():
    path = preset_path()
    if not os.path.isfile(path):
        raise TemplateError("文件里没有导入的头发材质，本机也没有声明头发模板：在 %s 里写 "
                            "{\"File\": 模板 .blend 的路径, \"Material\": 它里面的头发材质名}" % path)
    with open(path, encoding="utf-8") as stream:
        declared = json.load(stream)
    missing = [key for key in ("File", "Material") if key not in declared]
    if missing:
        raise TemplateError("头发模板声明 %s 缺 %s" % (path, "、".join(missing)))
    return declared["File"], declared["Material"]


def check_template():
    """没有导入的头发材质可抄时，本机声明的模板要真在：文件存在、里面有这张材质。"""
    file, name = _declared()
    if not os.path.isfile(file):
        raise TemplateError("头发模板文件不存在：%s" % file)
    with bpy.data.libraries.load(file) as (available_data, _wanted):
        if name not in available_data.materials:
            raise TemplateError("头发模板文件 %s 里没有材质 '%s'" % (file, name))


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


def copied_record(stack, template):
    """模板的记录整份抄来；记录以外的键（基座骨名之类）也跟着抄，栈自己写的与我们的标记除外。"""
    skipped = set(stack.RECORD_KEYS) | set(stack.SUPERSEDED_KEYS) | {STACK_KEY, stack.BLEND_KEY, stack.SHADING_KEY, MARKER}
    record = {key: _plain(template[key]) for key in stack.RECORD_KEYS}
    record.update({key: _plain(template[key]) for key in template.keys() if key not in skipped})
    return record


def _localized(image, directory):
    """模板库里的一张公共图变成这个文件里的普通图：同名的已经在就用它，否则把文件拷进输出目录再按相对路径指过去，
    图上的设置与标记（色彩空间、采样寻址）跟着复制。源文件不在返回 None。"""
    existing = bpy.data.images.get((image.name, None))
    if existing is not None:
        return existing
    source = bpy.path.abspath(image.filepath, library=image.library)
    if not os.path.isfile(source):
        return None
    destination = os.path.join(directory, os.path.basename(source))
    if not os.path.isfile(destination):
        os.makedirs(directory, exist_ok=True)
        shutil.copy2(source, destination)
    local = image.copy()
    local.filepath = bpy.path.relpath(destination)
    return local


def borrowed_record(stack, directory, per_model_slots):
    """本机声明的头发模板的记录：参数整份抄来，贴图只带公共图（不在 per_model_slots 里的槽）拷进 directory；
    返回 (记录, 给用户看的话)。模板库读完立刻整个移除，文件里不留它的任何数据块。"""
    file, name = _declared()
    with bpy.data.libraries.load(file, link=True) as (_available, wanted):
        wanted.materials = [name]
    template = wanted.materials[0]
    library = template.library
    notes = ["参数与公共贴图抄自 %s 里的 '%s'" % (os.path.basename(file), name)]
    try:
        record = {key: _plain(template[key]) for key in stack.RECORD_KEYS}
        shared = {}
        for slot, image in record[IMAGES_KEY].items():
            if slot in per_model_slots:
                continue
            local = _localized(image, directory)
            if local is None:
                notes.append("公共贴图 '%s' 的源文件找不到，这一槽没绑" % image.name)
            else:
                shared[slot] = local
        record[IMAGES_KEY] = shared
    finally:
        bpy.data.libraries.remove(library)
    return record, notes


def build(stack, template, name, images, directory, per_model_slots):
    """新编一张材质：有模板就抄它的记录，没有就抄本机声明的头发模板；hair 的贴图槽换成生成的图，名字给 name。
    返回 (材质, 给用户看的话)。"""
    if template is None:
        record, notes = borrowed_record(stack, directory, per_model_slots)
    else:
        record, notes = copied_record(stack, template), ["参数抄自 '%s'" % template.name]
    record[IMAGES_KEY] = dict(record[IMAGES_KEY], **images)
    recipe = bpy.data.materials.new(name + FAKE_RECIPE_SUFFIX)
    try:
        for key, value in record.items():
            recipe[key] = value
        recipe[STACK_KEY] = stack.PANEL_KEY
        material = stack.recompile(recipe)
    finally:
        bpy.data.materials.remove(recipe)
    material.name = name
    return material, notes


def repair_switches(stack, material):
    """角色自有的、中性图会把画面带歪的贴图槽没绑图，它的使用开关就关掉，返回关掉了哪些开关（槽与开关的对应在 ImporterSlots.json）：
    头发的 P 图中性是全白，R = 1 让高光的切线全走网格切线，方向听 UV 的；RMOS 中性的遮蔽是 0，整张材质发黑。"""
    bound = set(material.get(IMAGES_KEY) or {})
    floats = dict(material.get("ruri_uber_floats") or {})
    closed = [switch for slot, switch in slots()["SlotSwitches"].items() if slot not in bound and float(floats.get(switch, 0.0)) > 0.5]
    for switch in closed:
        stack.panel_write(material, stack.PROPERTIES[switch], 0.0)
    return closed


def rebind(stack, material, images):
    """材质已经存在：把它的贴图槽重新指到这次的图（已经是就不动）。"""
    bound = dict(material.get(IMAGES_KEY) or {})
    for slot, image in images.items():
        if bound.get(slot) != image:
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
