"""贴图落点：生成的法线与颜色写进哪几张图、挂到哪张材质上。

装了 RuriRipperImporter：新建（或更新）一张按它的头发着色栈编出来的材质球，法线进它的分离法线贴图的 R、G，颜色进它的 BaseMap；
两张图都先拷模板材质原来的图，再只写生成范围，范围外与别的通道原样不动；材质换到发片用的槽上，原来的材质保留。
没装：每张材质一对锚定贴图（材质名_Normal.png、材质名_BaseColor.png），接到 Principled BSDF 上。
锚定名只由材质名决定（去掉 Blender 的 .001 重名后缀），重启后按名字找回，不依赖任何会丢的状态。
"""

import importlib
import os
import re
from collections import namedtuple

import bpy
import numpy as np

from ...uv.uv_transfer import image_bind
from ...uv.uv_transfer import kernel
from . import importer
from . import shader_link

Settings = namedtuple("Settings", ("directory", "resolution", "variant", "color"))
Channel = namedtuple("Channel", ("kind", "anchored", "destination", "alpha"))
Binding = namedtuple("Binding", ("obj", "slot", "material", "uv_name", "render_uv_name"))

KIND_NORMAL = 'normal'
KIND_COLOR = 'color'
NORMAL_SUFFIX = "_Normal"
COLOR_SUFFIX = "_BaseColor"
GENERATED_SUFFIX = "_Procedural"
NAMING_MODULE = "RuriBridge.Kernel.texture_naming"
DUPLICATE_SUFFIX = re.compile(r"\.\d{3}$")
FORBIDDEN_CHARACTERS = re.compile(r'[<>:"/\\|?*]')
PACKED_ALPHA = 'CHANNEL_PACKED'
EXACT_ALPHA_MODES = ('STRAIGHT', PACKED_ALPHA)
DATA_COLORSPACE = 'Non-Color'
COLOR_COLORSPACE = 'sRGB'
FLAT_NORMAL = (0.5, 0.5, 1.0, 0.0)
FLAT_SPLIT_NORMAL = (0.5, 0.5, 0.5, 0.5)
FLAT_COLOR = (0.5, 0.5, 0.5, 0.0)
FLAT_BASE_MAP = (0.5, 0.5, 0.5, 1.0)


class TargetError(Exception):
    pass


def texture_stem(shader, texture_set, slot, variant):
    try:
        naming = importlib.import_module(NAMING_MODULE)
    except ImportError as error:
        raise TargetError("贴图文件名读 RuriBridge 的 Kernel/TextureNaming.json：先装好 RuriBridge（%s）" % error)
    return naming.stem(shader, texture_set, slot, variant)


def normalized(material):
    return FORBIDDEN_CHARACTERS.sub("_", DUPLICATE_SUFFIX.sub("", material.name))


def _variant_part(settings):
    return "_" + FORBIDDEN_CHARACTERS.sub("_", settings.variant) if settings.variant else ""


def generated_name(material, settings):
    return (material.get(importer.MARKER) or normalized(material)) + _variant_part(settings) + GENERATED_SUFFIX


def anchor_base(material, settings):
    return normalized(material) + _variant_part(settings)


def key_of(material, settings):
    """同一个落点的材质键相同：装了导入器按生成材质名，没装按锚定名。"""
    if importer.available():
        return ("importer", generated_name(material, settings))
    return ("file", anchor_base(material, settings))


def _check_exact(image):
    if min(image.size) == 0:
        raise TargetError("贴图 '%s' 没有像素" % image.name)
    if image.is_float:
        raise TargetError("贴图 '%s' 是浮点图，只支持 8 位贴图" % image.name)
    if not (image.colorspace_settings.is_data or image.alpha_mode in EXACT_ALPHA_MODES):
        raise TargetError("贴图 '%s' 是 %s 色彩空间配 %s Alpha，读进来的像素与文件不一致，拷出来会改掉没碰的像素；"
                          "改成 Non-Color，或 Alpha 改成 Straight / Channel Packed" % (
                              image.name, image.colorspace_settings.name, image.alpha_mode))


class Anchored:
    """一张按名字锚定的 PNG：数据块在就用数据块，不在就按名字从目录里打开，都没有就按模板图（或纯平的初值）新建。"""

    def __init__(self, name, directory, colorspace, resolution, source, flat):
        self.name = name
        self.directory = directory
        self.colorspace = colorspace
        self.resolution = resolution
        self.source = source
        self.flat = flat
        self.note = ""
        self._image = None

    @property
    def image(self):
        if self._image is None:
            self._image = bpy.data.images.get(self.name) or self._open_or_create()
        return self._image

    @property
    def size(self):
        return tuple(self.image.size)

    def _path(self):
        return os.path.join(bpy.path.abspath(self.directory), self.name + ".png")

    @staticmethod
    def _relative(path):
        return bpy.path.relpath(path).replace("\\", "/")

    def _initial(self):
        if self.source is not None:
            if min(self.source.size) > 0:
                _check_exact(self.source)
                return image_bind.read_raw(self.source)
            self.note = "模板的贴图 '%s' 没有像素，生成范围以外的部分用纯平的初值" % self.source.name
        return np.tile(np.array(self.flat, dtype=np.float32), (self.resolution, self.resolution, 1))

    def _open_or_create(self):
        path = self._path()
        if os.path.isfile(path):
            image = bpy.data.images.load(self._relative(path), check_existing=True)
            image.name = self.name
            image.colorspace_settings.name = self.colorspace
            image.alpha_mode = PACKED_ALPHA
            return image
        initial = self._initial()
        image = image_bind.create(self.name, initial.shape[1], initial.shape[0], colorspace=self.colorspace)
        image.alpha_mode = PACKED_ALPHA
        image_bind.write_raw(image, initial)
        return image

    def compose(self, region, values, destination, alpha):
        raw = image_bind.read_raw(self.image)
        for position, index in enumerate(destination):
            raw[..., index][region] = values[..., position][region]
        if alpha is not None:
            raw[..., 3][region] = alpha
        image_bind.write_raw(self.image, raw)

    def paint(self, values, covered, destination, alpha, margin, blocked):
        """写覆盖到的像素，再向外扩 margin 像素（不写别人占着的 blocked 像素），其余像素原样保留。"""
        filled = kernel.dilate(values, covered, margin, blocked & ~covered)
        self.compose(covered | filled, values, destination, alpha)

    def save(self):
        image = self.image
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        image.filepath_raw = path
        image.file_format = 'PNG'
        image.save()
        image.filepath = self._relative(path)
        return path


class FileTarget:
    def __init__(self, material, settings):
        if not bpy.data.filepath:
            raise TargetError("先保存 .blend：法线贴图要存到它旁边的相对目录里")
        base = anchor_base(material, settings)
        self.key = ("file", base)
        self.label = base
        self.normal = Anchored(base + NORMAL_SUFFIX, settings.directory, DATA_COLORSPACE, settings.resolution, None, FLAT_NORMAL)
        self.color = Anchored(base + COLOR_SUFFIX, settings.directory, COLOR_COLORSPACE, settings.resolution, None, FLAT_COLOR) \
            if settings.color else None

    def channels(self):
        found = [Channel(KIND_NORMAL, self.normal, (0, 1, 2), 1.0)]
        if self.color is not None:
            found.append(Channel(KIND_COLOR, self.color, (0, 1, 2), 1.0))
        return found

    def notes(self):
        return [anchored.note for anchored in (self.normal, self.color) if anchored is not None and anchored.note]

    def finish(self, bindings):
        """存盘并把锚定贴图接回材质；返回 (给用户看的话, 预览用的材质, 预览用的图像节点)。"""
        messages = ["'%s' → %s" % (anchored.name, anchored.save()) for anchored in (self.normal, self.color) if anchored is not None]
        preview = None
        material = None
        for binding in bindings:
            if binding.material is material:
                continue
            material = binding.material
            message, node = shader_link.attach(material, self.normal.image, self.color.image if self.color is not None else None,
                                               binding.uv_name, binding.render_uv_name)
            messages.append(message)
            if preview is None and node is not None:
                preview = (material, node)
        return messages, preview


class ImporterTarget:
    def __init__(self, material, settings, stack, template):
        names = importer.slots()
        self.stack = stack
        self.template = template
        self.base = template_base(material)
        self.name = generated_name(material, settings)
        self.key = ("importer", self.name)
        self.label = self.name
        self.normal_slot = names["NormalSlot"]
        self.color_slot = names["ColorSlot"]
        self.normal_channels = tuple(names["NormalChannels"])
        self.highlight_channels = tuple(names["HighlightChannels"])
        shader = importer.shader_of(stack, template)
        variant = "_".join(part for part in (_variant_part(settings).lstrip("_"), GENERATED_SUFFIX.lstrip("_")) if part)
        self.normal = Anchored(texture_stem(shader, self.base, self.normal_slot, variant), settings.directory, DATA_COLORSPACE,
                               settings.resolution, importer.template_image(template, self.normal_slot), FLAT_SPLIT_NORMAL)
        self.color = Anchored(texture_stem(shader, self.base, self.color_slot, variant), settings.directory, COLOR_COLORSPACE,
                              settings.resolution, importer.template_image(template, self.color_slot), FLAT_BASE_MAP) \
            if settings.color else None
        if not bpy.data.filepath:
            raise TargetError("先保存 .blend：生成的贴图要存到它旁边的相对目录里")

    def channels(self):
        found = [Channel(KIND_NORMAL, self.normal, self.normal_channels, None)]
        if self.color is not None:
            found.append(Channel(KIND_COLOR, self.color, (0, 1, 2), None))
        return found

    def notes(self):
        return [anchored.note for anchored in (self.normal, self.color) if anchored is not None and anchored.note]

    def finish(self, bindings):
        """存盘、新建或更新材质、把发片用的槽换成它；返回 (给用户看的话, 预览用的材质, 预览用的图像节点)。"""
        messages = ["'%s' → %s" % (anchored.name, anchored.save()) for anchored in (self.normal, self.color) if anchored is not None]
        images = {self.normal_slot: self.normal.image}
        if self.color is not None:
            images[self.color_slot] = self.color.image
        material = bpy.data.materials.get(self.name)
        if material is None:
            material = importer.build(self.stack, self.template, self.name, images)
            messages.append("新建材质 '%s'（照导入器的头发着色栈）" % self.name)
        else:
            importer.rebind(self.stack, material, images)
            messages.append("更新材质 '%s'" % self.name)
        material[importer.MARKER] = self.base
        replaced = set()
        for binding in bindings:
            slot = binding.obj.material_slots[binding.slot]
            if slot.material is not material:
                if slot.material is not None:
                    replaced.add(slot.material)
                slot.material = material
        for old in replaced:
            if old.users == 0:
                old.use_fake_user = True
                messages.append("原材质 '%s' 已加上保护，不会随存盘丢掉" % old.name)
        return messages, (material, importer.preview_node(material, self.color_slot))


def template_base(material):
    return material.get(importer.MARKER) or normalized(material)


def resolve(material, settings):
    if importer.available():
        part = importer.other_part(material)
        if part is not None:
            raise TargetError("材质 '%s' 是导入器的 %s 部件，不是头发，没有动它" % (material.name, part or "未命名"))
        stack, template = importer.find_template(material)
        if stack is None:
            raise TargetError("文件里没有 RuriRipperImporter 导入的头发材质可当模板：先用导入器载入头发")
        return ImporterTarget(material, settings, stack, template)
    return FileTarget(material, settings)
