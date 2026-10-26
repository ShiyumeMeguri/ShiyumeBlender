"""烘焙：把所有预览层按各自的参数光栅化，写进各自原材质的贴图落点（法线的 R、G 与配套颜色），再把落点接回材质。

每一层的面取成四边形，交给头发程序（procedural）逐像素算出法线编码与颜色；同一个落点的几层依次写，局部层的面和基础层的面互不重叠。
写之前先量好别人占着的像素，外扩不写到它们上面；整个落点的像素在贴图里原样保留，只改覆盖到的和它们的外扩。
"""

from collections import namedtuple

import bmesh
import numpy as np

from ...uv.uv_transfer import mesh_bind
from ..endfield_target import occupancy
from ..endfield_target import targets
from . import attributes
from . import layers
from . import procedural
from . import quads as quad_module
from . import raster
from . import strips

Part = namedtuple("Part", ("quads", "parameters"))
Batch = namedtuple("Batch", ("target", "parts", "bindings"))
Written = namedtuple("Written", ("batch", "texels", "mean_color"))

NORMAL_OUTPUTS = ("normalRed", "normalGreen", "normalBlue")
COLOR_OUTPUTS = ("colorRed", "colorGreen", "colorBlue")
BYTE_LEVELS = 255.0


def _quantized(values):
    return (np.round(np.clip(values, 0.0, 1.0) * BYTE_LEVELS) / BYTE_LEVELS).astype(np.float32)


def collect(objects, scene, uv_layer_name, settings, problems):
    """返回 ({落点键: Batch}, {物体名: Generation}, [不规则孤岛的原因汇总])。"""
    batches = {}
    generations = {}
    rejected = []
    for obj in objects:
        mesh = obj.data
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.faces.index_update()
            render_uv_name = mesh_bind.render_uv_name(mesh)
            uv_name = uv_layer_name or render_uv_name
            uv_layer = bm.loops.layers.uv.get(uv_name)
            if uv_layer is None:
                problems.append("物体 '%s' 没有 UV 层 '%s'，跳过" % (obj.name, uv_name))
                continue
            found, skipped = strips.collect(obj, bm, uv_layer, scene)
            rejected.extend(skipped)
            table = attributes.build(found, uv_layer)
            included = np.zeros(len(bm.faces), dtype=bool)
            regular = np.zeros(len(bm.faces), dtype=bool)
            for index, slot in enumerate(obj.material_slots):
                layer = slot.material
                if not layers.is_layer(layer):
                    continue
                original = layers.original_of(layer)
                if original is None:
                    problems.append("预览层 '%s' 找不到它的原材质，跳过" % layer.name)
                    continue
                if layers.generator_of(layer) is None:
                    problems.append("预览层 '%s' 是别的版本做的，对不上现在的参数，跳过（取消预览后重新开始）" % layer.name)
                    continue
                parameters = procedural.parameters_of(layers.generator_of(layer))
                if not parameters["bake"]:
                    continue
                quads = quad_module.build(found, uv_layer, table, lambda face, slot_index=index: face.material_index == slot_index)
                if not len(quads.face):
                    continue
                included[quads.face] = True
                regular[quads.face[quads.regular]] = True
                key = targets.key_of(original, settings)
                if key not in batches:
                    try:
                        batches[key] = Batch(targets.resolve(original, settings), [], [])
                    except targets.TargetError as error:
                        problems.append(str(error))
                        batches[key] = None
                batch = batches[key]
                if batch is None:
                    continue
                batch.parts.append(Part(quads, parameters))
                base = layers.base_slot(obj, original) if layers.is_local(layer) else index
                batch.bindings.append(targets.Binding(obj, base, original, uv_name, render_uv_name))
            generations[obj.name] = occupancy.Generation(uv_name, included, regular)
        finally:
            bm.free()
    return batches, generations, rejected


def write(batch, margin, generations, settings, problems):
    """把一个落点的各层写进它的贴图；返回 Written(batch, 写入的像素数, 颜色通道的平均 sRGB 或 None)。"""
    target = batch.target
    texels = 0
    mean_color = None
    for channel in target.channels():
        is_normal = channel.kind == targets.KIND_NORMAL
        width, height = channel.anchored.size
        outputs = (NORMAL_OUTPUTS if is_normal else COLOR_OUTPUTS)[:len(channel.destination)]
        covered = np.zeros((height, width), dtype=bool)
        values = np.zeros((height, width, len(outputs)), dtype=np.float32)
        conflicts = 0
        for part in batch.parts:
            quads = quad_module.select(part.quads, part.quads.regular) if is_normal else part.quads
            if not len(quads.face):
                continue
            field = raster.generate(quads, part.parameters, outputs, width, height)
            conflicts += field.conflicts
            values[field.covered] = field.values[field.covered]
            covered |= field.covered
        if not covered.any():
            problems.append("'%s' 上没有面落进贴图范围%s" % (channel.anchored.name, "（法线只生成规则长条）" if is_normal else ""))
            continue
        if conflicts:
            problems.append("'%s' 里有 %d 个像素被不同发片的 UV 重叠覆盖，纹路在那里会互相盖掉" % (channel.anchored.name, conflicts))
        values = _quantized(values)
        blocked = occupancy.protected(target.key, width, height, generations, settings, is_normal)
        channel.anchored.paint(values, covered, channel.destination, channel.alpha, margin, blocked)
        texels += int(covered.sum())
        if not is_normal:
            mean_color = values[covered].mean(axis=0)
    return Written(batch, texels, mean_color)
