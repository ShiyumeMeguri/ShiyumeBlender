"""图像适配层：bpy.types.Image 与 numpy 数组互转，并在着色器看到的数值空间里交换数据。

`Image.pixels` 给的是缓冲里存的原值：字节图是文件里的编码值（sRGB 图就是 sRGB 编码），浮点缓冲是场景线性值。
GPU 采样编码过的字节贴图时先解码再过滤，所以重采样前按色彩空间的传递函数把字节图解码成线性值、写回时再编码；
数据图（Non-Color）、浮点缓冲与线性编码的图按原值处理。传递函数取自色彩空间的 interop_id
（`<传递>_<原色>_<scene|display>`），不认名字。
"""

import os
import re

import bpy
import numpy as np

_RUN_INDEX = re.compile(r"_\d{3}$")
_INTEROP_PREFIXES = ("ocio:", "blender:")
_GAMMA_EXPONENTS = {"g18": 1.8, "g22": 2.2, "g24": 2.4}

TRANSFER_DATA = 'DATA'
TRANSFER_LINEAR = 'LINEAR'
TRANSFER_SRGB = 'SRGB'
TRANSFER_GAMMA = 'GAMMA'
TRANSFER_OPAQUE = 'OPAQUE'


class Encoding:
    """一张图的像素怎么编码：传递函数、原色（只对字节彩色图有意义）、幂次（纯幂传递）。

    OPAQUE 是解不开的编码（对数曲线、显示变换等）：只能原值搬运，且同一张输出里不许与别的编码混用。
    """

    def __init__(self, transfer, primaries=None, exponent=None, space=None):
        self.transfer = transfer
        self.primaries = primaries
        self.exponent = exponent
        self.space = space


def encoding_of(image):
    settings = image.colorspace_settings
    if settings.is_data:
        return Encoding(TRANSFER_DATA)
    if image.is_float:
        return Encoding(TRANSFER_LINEAR)
    interop = settings.interop_id
    for prefix in _INTEROP_PREFIXES:
        if interop.startswith(prefix):
            interop = interop[len(prefix):]
    parts = interop.split("_")
    if len(parts) >= 2:
        transfer, primaries = parts[0], parts[1]
        if transfer in ("lin", "linear"):
            return Encoding(TRANSFER_LINEAR, primaries)
        if transfer == "srgb":
            return Encoding(TRANSFER_SRGB, primaries)
        if transfer in _GAMMA_EXPONENTS:
            return Encoding(TRANSFER_GAMMA, primaries, _GAMMA_EXPONENTS[transfer])
    return Encoding(TRANSFER_OPAQUE, space=settings.name)


def mixing_problem(images):
    """同一张输出的参与图（目标图在前）能否在同一数值空间里混合；不能就返回原因。"""
    encodings = [(image, encoding_of(image)) for image in images]
    opaque = [(image, encoding) for image, encoding in encodings if encoding.transfer == TRANSFER_OPAQUE]
    if opaque:
        spaces = {encoding.space for _image, encoding in encodings if encoding.transfer != TRANSFER_DATA}
        if len(spaces) > 1:
            names = ", ".join(f"'{image.name}'（{encoding.space}）" for image, encoding in opaque)
            return f"色彩空间解不开的贴图不能与别的色彩空间混合: {names}"
    primaries = {encoding.primaries for _image, encoding in encodings
                 if encoding.primaries is not None}
    if len(primaries) > 1:
        names = ", ".join(f"'{image.name}'（{image.colorspace_settings.name}）" for image, _encoding in encodings)
        return f"这些贴图的原色不同，混合需要换色域: {names}"
    return None


def _decode_channels(values, encoding):
    if encoding.transfer == TRANSFER_SRGB:
        return np.where(values <= 0.04045, values / np.float32(12.92),
                        ((values + np.float32(0.055)) / np.float32(1.055)) ** np.float32(2.4))
    if encoding.transfer == TRANSFER_GAMMA:
        return np.clip(values, 0.0, None) ** np.float32(encoding.exponent)
    return values


def _encode_channels(values, encoding):
    if encoding.transfer == TRANSFER_SRGB:
        clipped = np.clip(values, 0.0, 1.0)
        return np.where(clipped <= 0.0031308, clipped * np.float32(12.92),
                        np.float32(1.055) * clipped ** np.float32(1.0 / 2.4) - np.float32(0.055))
    if encoding.transfer == TRANSFER_GAMMA:
        return np.clip(values, 0.0, 1.0) ** np.float32(1.0 / encoding.exponent)
    return values


def decode(raw, encoding):
    """原值 → 着色值：只解 RGB，alpha 本来就是线性数据。"""
    shading = raw.copy()
    shading[..., 0:3] = _decode_channels(raw[..., 0:3], encoding)
    return shading


def encode(shading, encoding, clamp):
    """着色值 → 原值；字节图要钳进 0~1。"""
    raw = shading.copy()
    raw[..., 0:3] = _encode_channels(shading[..., 0:3], encoding)
    if clamp:
        np.clip(raw, 0.0, 1.0, out=raw)
    return raw.astype(np.float32)


def read_raw(image):
    """读出缓冲原值 (height, width, 4) float32，第 0 行对应 v=0；尺寸为 0 返回 None。"""
    width, height = image.size
    if width == 0 or height == 0:
        return None
    buffer = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    return buffer.reshape(height, width, 4)


def read_shading(image):
    raw = read_raw(image)
    if raw is None:
        return None
    return decode(raw, encoding_of(image)).astype(np.float32)


def write_raw(image, raw):
    image.pixels.foreach_set(np.ascontiguousarray(raw, dtype=np.float32).reshape(-1))
    image.update()


def has_content(image):
    """图里有没有可搬运的贴图内容：没画过、没打包的生成图只是纯色/测试网格占位，不算。"""
    return not (image.source == 'GENERATED' and not image.is_dirty and image.packed_file is None)


def output_name(source_image, suffix="_Retarget"):
    """由源图名推导输出名基底；反复重定向不会把后缀和序号叠成一串。"""
    base = os.path.splitext(source_image.name)[0]
    shrinking = True
    while shrinking:
        shrinking = False
        stripped = _RUN_INDEX.sub("", base)
        if stripped != base:
            base = stripped
            shrinking = True
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            shrinking = True
    return base + suffix


def unique_name(base, directory=None):
    """挑一个还没被占用的名字——已有的数据块与磁盘文件都不覆盖。"""
    resolved = bpy.path.abspath(directory) if directory else None

    def taken(name):
        if name in bpy.data.images:
            return True
        return bool(resolved) and os.path.exists(os.path.join(resolved, name + ".png"))

    if not taken(base):
        return base
    index = 1
    while taken(f"{base}_{index:03d}"):
        index += 1
    return f"{base}_{index:03d}"


def create(name, width, height, use_float=False, colorspace='sRGB'):
    """按指定规格新建图像数据块；名字须由 unique_name 挑过，这里不做覆盖。"""
    image = bpy.data.images.new(
        name, width=width, height=height, alpha=True, float_buffer=use_float,
    )
    image.colorspace_settings.name = colorspace
    return image


def create_output(name, width, height, template):
    """建立输出图像数据块，色彩空间、位深与 alpha 解释都跟随它要顶替的那张图。"""
    image = create(name, width, height,
                   use_float=template.is_float,
                   colorspace=template.colorspace_settings.name)
    image.alpha_mode = template.alpha_mode
    return image


def save(image, directory):
    """写盘到 directory/<name>.png，返回绝对路径。"""
    resolved = bpy.path.abspath(directory)
    os.makedirs(resolved, exist_ok=True)
    path = os.path.join(resolved, image.name + ".png")
    image.filepath_raw = path
    image.file_format = 'PNG'
    image.save()
    return path


def store_in_place(image):
    """把改过像素的现有图存回它自己的来处：文件图写回原文件（原格式），打包的与没有文件的打包进 .blend。返回去处描述。"""
    if image.packed_file is None and image.filepath:
        image.save()
        return bpy.path.abspath(image.filepath)
    image.pack()
    return f"{image.name}（打包进 .blend）"
