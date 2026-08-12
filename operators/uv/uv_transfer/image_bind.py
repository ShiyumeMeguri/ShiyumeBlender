"""图像适配层：bpy.types.Image 与 numpy 数组互转，并保持色彩空间语义不变。

Image.pixels 给出的是该图色彩空间解码后的值（sRGB 图 → 线性，Non-Color 图 → 原值）。
输出图沿用源图的色彩空间名，写回时 Blender 会做对称的编码，因此往返是无损的。
"""

import os
import re

import bpy
import numpy as np

_RUN_INDEX = re.compile(r"_\d{3}$")


def read_rgba(image):
    """读出 (height, width, 4) float32，第 0 行对应 v=0。"""
    width, height = image.size
    if width == 0 or height == 0:
        return None
    buffer = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    return buffer.reshape(height, width, 4)


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


def create_output(name, width, height, source_image):
    """建立输出图像数据块，色彩空间与位深跟随源图。"""
    return create(name, width, height,
                  use_float=source_image.is_float,
                  colorspace=source_image.colorspace_settings.name)


def write_rgba(image, rgba):
    image.pixels.foreach_set(rgba.reshape(-1))
    image.update()


def save(image, directory):
    """写盘到 directory/<name>.png，返回绝对路径。"""
    resolved = bpy.path.abspath(directory)
    os.makedirs(resolved, exist_ok=True)
    path = os.path.join(resolved, image.name + ".png")
    image.filepath_raw = path
    image.file_format = 'PNG'
    image.save()
    return path
