"""IMAGE 颜色源：直接把源 UV 上的贴图重采样到目标 UV 排布。

在目标 UV 空间光栅化三角形，逐样本插值出源 UV 再采样源图——不经渲染引擎，
因此没有抗锯齿边缘与背景混色，边缘像素永远不会被外扩区反向污染。
"""

import numpy as np

from . import graph_bind
from . import image_bind
from . import kernel
from . import mesh_bind

# 一批同时驻留内存的源图字节上限
_SOURCE_MEMORY_BUDGET = 512 * 1024 * 1024


def _memory_batches(images, budget):
    """按源图内存占用把图像分批，避免一次读入过多大图。"""
    batches = []
    current = []
    current_bytes = 0
    for image in images:
        width, height = image.size
        needed = width * height * 4 * 4
        if current and current_bytes + needed > budget:
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(image)
        current_bytes += needed
    if current:
        batches.append(current)
    return batches


def discover(job):
    """找出所有采样源 UV 的图像纹理节点，按图像归并其所属 (物体, 材质槽)。"""
    image_slots = {}
    image_nodes = {}
    unresolved = 0

    for index, entry in enumerate(job.entries):
        render_uv = mesh_bind.render_uv_name(entry.mesh)
        for slot_index, material in enumerate(entry.mesh.materials):
            bound, unknown = graph_bind.image_nodes_using_uv(
                material, job.source_uv, render_uv)
            unresolved += unknown
            for node, image in bound:
                image_slots.setdefault(image, set()).add((index, slot_index))
                image_nodes.setdefault(image, {})[node.as_pointer()] = node

    return image_slots, image_nodes, unresolved


def _group_by_workload(job, image_slots):
    """按 (材质槽集合, 输出尺寸) 归组——同组共用一次光栅化。"""
    groups = {}
    for image, slots in image_slots.items():
        if job.settings.resolution == 'SOURCE':
            width, height = image.size
        else:
            width = height = int(job.settings.resolution)
        if width <= 0 or height <= 0:
            job.warn(f"图像 '{image.name}' 尺寸为 0，跳过")
            continue
        groups.setdefault((frozenset(slots), width, height), []).append(image)
    return groups


def _gather_triangles(job, slots):
    target_parts = []
    source_parts = []
    for entry_index, slot_index in sorted(slots):
        pair = job.entries[entry_index].triangles.get(slot_index)
        if pair is None:
            continue
        target_parts.append(pair[0])
        source_parts.append(pair[1])

    if not target_parts:
        return None, None
    return np.concatenate(target_parts), np.concatenate(source_parts)


def _transfer(job, batch, target_triangles, source_triangles, width, height, outputs):
    """一次光栅化，供本批所有源图共用；返回检测到的重叠像素数。"""
    settings = job.settings
    pixel_total = width * height
    supersample = int(settings.supersample)
    subsamples = float(supersample * supersample)

    sources = {}
    for image in batch:
        pixels = image_bind.read_rgba(image)
        if pixels is not None:
            sources[image] = pixels
    if not sources:
        return 0

    accumulators = {image: np.zeros((pixel_total, 4), dtype=np.float32)
                    for image in sources}
    coverage = np.zeros(pixel_total, dtype=np.float32)

    for pixel, uv in kernel.iter_samples(target_triangles, source_triangles,
                                         width, height, supersample):
        coverage += np.bincount(pixel, minlength=pixel_total).astype(np.float32)
        for image, pixels in sources.items():
            sampled = kernel.sample_bilinear(pixels, uv, settings.extension)
            accumulator = accumulators[image]
            for channel in range(4):
                accumulator[:, channel] += np.bincount(
                    pixel, weights=sampled[:, channel],
                    minlength=pixel_total).astype(np.float32)

    covered = coverage > 0.0
    if not covered.any():
        return 0

    for image in sources:
        accumulator = accumulators[image]
        rgba = np.zeros((pixel_total, 4), dtype=np.float32)
        # RGB 只按几何覆盖归一化——边缘像素拿到的是纯表面色，绝不掺背景
        np.divide(accumulator[:, 0:3], coverage[:, None],
                  out=rgba[:, 0:3], where=covered[:, None])
        # alpha 按整像素足迹归一化，未覆盖的子采样点自然把边缘压软
        np.divide(accumulator[:, 3], subsamples, out=rgba[:, 3], where=covered)
        np.clip(rgba[:, 3], 0.0, 1.0, out=rgba[:, 3])

        planar = rgba.reshape(height, width, 4)
        kernel.dilate_edges(planar, covered.reshape(height, width), settings.margin)

        name = image_bind.unique_name(
            image_bind.output_name(image), job.output_directory)
        output = image_bind.create_output(name, width, height, image)
        image_bind.write_rgba(output, planar)
        outputs[image] = output

    return int((coverage > subsamples + 0.5).sum())


def run(job):
    image_slots, image_nodes, unresolved = discover(job)
    if unresolved:
        job.warn(f"{unresolved} 个图像节点的 UV 来源无法判定（Vector 接了自定义节点），未参与重定向")
    if not image_slots:
        job.error(f"没有找到采样 '{job.source_uv}' 的图像纹理节点")
        return None

    outputs = {}
    overlapped = 0

    for (slots, width, height), images in _group_by_workload(job, image_slots).items():
        target_triangles, source_triangles = _gather_triangles(job, slots)
        if target_triangles is None:
            continue
        for batch in _memory_batches(images, _SOURCE_MEMORY_BUDGET):
            overlapped += _transfer(job, batch, target_triangles, source_triangles,
                                    width, height, outputs)

    if not outputs:
        job.error("目标 UV 上没有任何三角形落进 0~1 范围")
        return None

    if overlapped:
        job.warn(f"目标 UV 有 {overlapped} 个像素被多个面覆盖，重叠处取最后写入的面")

    return {
        'outputs': list(outputs.values()),
        'replacements': outputs,
        'nodes': image_nodes,
    }


def apply(job, result):
    """把新贴图接回原本采样源 UV 的那些图像节点。"""
    for source_image, output in result['replacements'].items():
        for node in result['nodes'].get(source_image, {}).values():
            node.image = output
