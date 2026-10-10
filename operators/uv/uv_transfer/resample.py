"""IMAGE 颜色源：把各面材质里的贴图逐像素重采样到目标排布，不经渲染引擎。

在目标排布上光栅化三角形，逐样本插值出源坐标再采样源图。每张输出由若干份「贡献」合成：一组三角形、它们从哪张
源图、经哪个 UV 层与哪个贴图坐标变换取色。贡献按着色器看到的数值（解码后的线性值）累加，RGB 与 alpha 一样只按
几何覆盖归一化、一样向外扩——alpha 是透明度、光滑度这类数据，不是覆盖率；切线法线在旋转/镜像过的孤岛上跟着转。

两种出图方式：

- 不合并：每张源图各出一张，贡献是用它的那些面。
- 合并到材质：选中网格的全部面改用指定材质；它每个经源 UV 采样的贴图节点按节点标签，从各面原材质里同标签的
  节点取色，合成一张。

两种写入方式：新建贴图（新数据块，自动编号），或写入现有贴图——直接画进目标图，只写本次网格新排布覆盖的像素
与就近的外扩，文件里其他网格经 UV 用到的像素一律保留。
"""

import bpy
import numpy as np

from . import image_bind
from . import kernel
from . import mesh_bind

_PROTECTION_SUPERSAMPLE = 2
_PROTECTION_RING = 1
_CONFLICT_TEXELS = 3.0


class PlanError(Exception):
    pass


class Contribution:
    """一组三角形从一张源图取色。target 是已折进 0~1 的目标贴图坐标，source 是对应的源贴图坐标，
    turns 是每个三角形的切线法线转向矩阵（不是法线则为 None）。"""

    def __init__(self, image, target, source, extension, nearest, turns):
        self.image = image
        self.target = target
        self.source = source
        self.extension = extension
        self.nearest = nearest
        self.turns = turns


class Output:
    """一张输出图：template 决定新建时的色彩空间、位深与 alpha 解释，destination 是写入现有贴图时的目标图；
    extension 与 matrix 是这张图将来被读时的越界方式与贴图坐标变换——目标三角形按它们落位。"""

    def __init__(self, key, template, destination, extension, matrix):
        self.key = key
        self.template = template
        self.destination = destination
        self.extension = extension
        self.matrix = matrix
        self.width = 0
        self.height = 0
        self.contributions = []
        self.rebind = []
        self.uncovered = []
        self.outside = 0


def _contribute(job, output, entry, slot, sampling):
    target_uv, loops = entry.layout.slots[slot]
    source_uv = entry.layout.loop_uv[sampling.uv_name][loops]
    target = kernel.transform(output.matrix, target_uv)
    source = kernel.transform(sampling.matrix, source_uv)
    folded, owner, outside = kernel.fold_triangles(target, output.extension)
    output.outside += outside
    turns = None
    if sampling.normal is not None:
        turns = kernel.normal_turns(source_uv, target_uv, sampling.normal)[owner]
        job.normals_declared = True
    elif (sampling.image.colorspace_settings.is_data and image_bind.has_content(sampling.image)
          and kernel.is_turned(kernel.normal_turns(source_uv, target_uv, kernel.CONVENTION_OPENGL)).any()):
        job.turned_data_images.add(sampling.image.name)
    output.contributions.append(Contribution(
        sampling.image, folded, source[owner], sampling.extension, sampling.nearest, turns))


def _output_size(job, images, fallback):
    if job.settings.resolution != 'SOURCE':
        size = int(job.settings.resolution)
        return size, size
    sizes = [tuple(image.size) for image in images
             if image_bind.has_content(image) and image.size[0] > 0 and image.size[1] > 0]
    if not sizes:
        sizes = [tuple(fallback.size)]
    return max(width for width, _height in sizes), max(height for _width, height in sizes)


def _plan_by_image(job):
    users = {}
    for entry_index, entry in enumerate(job.entries):
        for slot, material in entry.slot_materials():
            for sampling in job.samplings(material, entry.mesh):
                if sampling.uv_name == job.source_uv and image_bind.has_content(sampling.image):
                    users.setdefault(sampling.image, []).append((entry_index, slot, sampling))

    outputs = []
    for image, uses in users.items():
        if len({sampling.addressing() for _entry, _slot, sampling in uses}) > 1:
            raise PlanError(f"图像 '{image.name}' 被几个节点以不同的坐标变换、越界或插值方式采样，"
                            f"共用不了一张重定向图")
        reference = uses[0][2]
        output = Output(image.name, image, image if job.writes_existing else None,
                        reference.extension, reference.matrix)
        contributed = set()
        for entry_index, slot, sampling in uses:
            output.rebind.append(sampling.node)
            if (entry_index, slot) in contributed:
                continue
            contributed.add((entry_index, slot))
            _contribute(job, output, job.entries[entry_index], slot, sampling)
        output.width, output.height = (tuple(image.size) if job.writes_existing
                                       else _output_size(job, [image], image))
        outputs.append(output)
    return outputs


def _role_source(job, entry, material, label):
    """某个面原材质里与合并目标同标签的节点：有贴图内容的优先（必须唯一），否则取最外层的占位图。"""
    if material is None:
        return None
    candidates = [sampling for sampling in job.samplings(material, entry.mesh)
                  if sampling.label == label and sampling.uv_name in entry.layout.loop_uv]
    content = [sampling for sampling in candidates if image_bind.has_content(sampling.image)]
    if len({sampling.image for sampling in content}) > 1:
        raise PlanError(f"材质 '{material.name}' 里标签 '{label}' 对应了几张不同的贴图，分不清哪张是这些面的颜色")
    pool = content or candidates
    return min(pool, key=lambda sampling: sampling.depth) if pool else None


def _plan_merge(job, material):
    roles = {}
    unlabeled = set()
    for entry in job.entries:
        for sampling in job.samplings(material, entry.mesh):
            if sampling.uv_name != job.source_uv or not image_bind.has_content(sampling.image):
                continue
            if not sampling.label:
                unlabeled.add(sampling.image.name)
                continue
            known = roles.get(sampling.label)
            if known is None:
                roles[sampling.label] = [sampling]
            elif known[0].image != sampling.image or known[0].addressing() != sampling.addressing():
                raise PlanError(f"合并目标 '{material.name}' 里标签 '{sampling.label}' 对应了不同的贴图或采样方式，"
                                f"分不清写进哪张")
            else:
                known.append(sampling)
    if unlabeled:
        job.warn(f"合并按节点标签配对，'{material.name}' 里这些贴图节点没有标签，未参与: "
                 f"{', '.join(sorted(unlabeled))}")
    if not roles:
        raise PlanError(f"合并目标 '{material.name}' 里没有带标签、经 '{job.source_uv}' 采样的贴图节点")

    outputs = []
    for label, destinations in roles.items():
        reference = destinations[0]
        output = Output(label, reference.image, reference.image if job.writes_existing else None,
                        reference.extension, reference.matrix)
        output.rebind = [sampling.node for sampling in destinations]
        for entry in job.entries:
            for slot, slot_material in entry.slot_materials():
                source = _role_source(job, entry, slot_material, label)
                if source is None:
                    owner = slot_material.name if slot_material is not None else "空槽"
                    output.uncovered.append(f"{entry.obj.name} / {owner}")
                    continue
                _contribute(job, output, entry, slot, source)
        output.width, output.height = (
            tuple(reference.image.size) if job.writes_existing
            else _output_size(job, [contribution.image for contribution in output.contributions], reference.image))
        outputs.append(output)
    return outputs


def _check_mixing(outputs):
    for output in outputs:
        images = [output.template] + [contribution.image for contribution in output.contributions]
        problem = image_bind.mixing_problem(images)
        if problem is not None:
            raise PlanError(f"'{output.key}': {problem}")


def _check_rebind(job, outputs):
    """新建贴图并应用到物体时要换节点上的图：换的若是被选中网格以外的网格也在用的材质或节点组，它们会一起错位。"""
    for output in outputs:
        for node in output.rebind:
            for material in job.materials_owning(node.id_data):
                foreign = job.foreign_users(material)
                if foreign:
                    raise PlanError(
                        f"材质 '{material.name}' 还被 {', '.join(foreign[:5])} 使用，给它换上新图会让这些物体错位 —— "
                        f"改用「写入现有贴图」，或先把材质单独给选中物体用")


def _render(job, output):
    """把一张输出的全部贡献光栅化、采样、累加，返回 (着色值 (H, W, 4), 覆盖 (H, W), 内容冲突的像素数)。"""
    width, height = output.width, output.height
    pixel_total = width * height
    supersample = int(job.settings.supersample)

    accumulator = np.zeros((pixel_total, 4), dtype=np.float32)
    coverage = np.zeros(pixel_total, dtype=np.float32)
    first_image = np.full(pixel_total, -1, dtype=np.int32)
    first_texel = np.zeros((pixel_total, 2), dtype=np.float32)
    conflicted = np.zeros(pixel_total, dtype=bool)

    sources = {}
    identities = {}
    for contribution in output.contributions:
        image = contribution.image
        if image not in sources:
            sources[image] = image_bind.read_shading(image)
            identities[image] = len(identities)
        pixels = sources[image]
        if pixels is None:
            continue
        size = np.array([pixels.shape[1], pixels.shape[0]], dtype=np.float32)
        identity = identities[image]
        for pixel, uv, triangle in kernel.iter_samples(contribution.target, contribution.source,
                                                       width, height, supersample):
            sampled = kernel.sample(pixels, uv, contribution.extension, contribution.nearest)
            if contribution.turns is not None:
                sampled = kernel.turn_normals(sampled, contribution.turns[triangle])

            texel = (uv - np.floor(uv)) * size
            fresh = first_image[pixel] < 0
            first_image[pixel[fresh]] = identity
            first_texel[pixel[fresh]] = texel[fresh]
            seen = ~fresh
            gap = np.abs(texel[seen] - first_texel[pixel[seen]])
            gap = np.minimum(gap, size - gap)
            clash = (first_image[pixel[seen]] != identity) | (gap.max(axis=1) > _CONFLICT_TEXELS)
            conflicted[pixel[seen][clash]] = True

            coverage += np.bincount(pixel, minlength=pixel_total).astype(np.float32)
            for channel in range(4):
                accumulator[:, channel] += np.bincount(
                    pixel, weights=sampled[:, channel], minlength=pixel_total).astype(np.float32)
    sources.clear()

    covered = coverage > 0.0
    shading = np.zeros((pixel_total, 4), dtype=np.float32)
    np.divide(accumulator, coverage[:, None], out=shading, where=covered[:, None])
    return shading.reshape(height, width, 4), covered.reshape(height, width), int(conflicted.sum())


def _protected(job, output):
    """目标图里被选中网格以外的网格经 UV 读到的像素（含双线性读到的一圈），返回 (H, W) bool。"""
    image = output.destination
    width, height = output.width, output.height
    mask = np.zeros((height, width), dtype=bool)
    relaid = job.relaid_meshes()
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.data.as_pointer() in relaid:
            continue
        mesh = obj.data
        slot_loops = None
        uv_layers = {}
        for slot_index, slot in enumerate(obj.material_slots):
            material = slot.material
            if material is None:
                continue
            if any(item.uv_dependent and item.image == image for item in job.unresolved(material, mesh)):
                job.unprotected.add(f"{obj.name} / {material.name}")
            uses = [sampling for sampling in job.samplings(material, mesh) if sampling.image == image]
            if not uses:
                continue
            if slot_loops is None:
                slot_loops = mesh_bind.loops_by_material(mesh)
            loops = slot_loops.get(slot_index)
            if loops is None:
                continue
            for sampling in uses:
                if sampling.uv_name not in uv_layers:
                    uv_layers[sampling.uv_name] = mesh_bind.read_uv(mesh, sampling.uv_name)
                uv = uv_layers[sampling.uv_name]
                if uv is None:
                    job.unprotected.add(f"{obj.name} / {material.name}")
                    continue
                triangles = kernel.transform(sampling.matrix, uv[loops])
                folded, _owner, _outside = kernel.fold_triangles(triangles, sampling.extension)
                mask |= kernel.coverage_mask(folded, width, height, _PROTECTION_SUPERSAMPLE)
    return kernel.grow(mask, _PROTECTION_RING)


def _compose_new(job, output, shading, covered):
    kernel.dilate(shading, covered, job.settings.margin)
    template = output.template
    raw = image_bind.encode(shading, image_bind.encoding_of(template), clamp=not template.is_float)
    name = image_bind.unique_name(image_bind.output_name(template), job.output_directory)
    image = image_bind.create_output(name, output.width, output.height, template)
    image_bind.write_raw(image, raw)
    return image


def _compose_existing(job, output, shading, covered):
    destination = output.destination
    protected = _protected(job, output)
    writable = covered & ~protected
    clashed = int(np.count_nonzero(covered & protected))
    filled = kernel.dilate(shading, writable, job.settings.margin, protected)
    written = writable | filled
    raw = image_bind.read_raw(destination)
    raw[written] = image_bind.encode(shading[written], image_bind.encoding_of(destination),
                                     clamp=not destination.is_float)
    image_bind.write_raw(destination, raw)
    return clashed


def run(job):
    merge_material = job.settings.merge_material
    try:
        outputs = _plan_merge(job, merge_material) if merge_material is not None else _plan_by_image(job)
        _check_mixing(outputs)
        if job.settings.apply_to_object and not job.writes_existing:
            _check_rebind(job, outputs)
    except PlanError as problem:
        job.error(str(problem))
        return None

    unresolved = job.unresolved_images()
    if unresolved:
        job.warn(f"这些贴图经无法换算的坐标采样 UV（非常量变换、视差、非平面投影或 UDIM），没有参与重定向: "
                 f"{', '.join(unresolved)}")
    outputs = [output for output in outputs if output.contributions]
    if not outputs:
        job.error(f"没有找到经 '{job.source_uv}' 采样、带贴图内容的图像节点")
        return None
    if job.writes_existing:
        locked = [output.destination.name for output in outputs
                  if output.destination.library is not None or output.destination.source not in ('FILE', 'GENERATED')]
        if locked:
            job.error(f"这些目标图来自库文件或不是单张图片，不能就地写入: {', '.join(locked)}")
            return None

    rendered = [(output,) + _render(job, output) for output in outputs]

    created = []
    updated = []
    conflicts = 0
    clashes = 0
    for output, shading, covered, conflicted in rendered:
        conflicts += conflicted
        if not covered.any():
            continue
        if job.writes_existing:
            clashes += _compose_existing(job, output, shading, covered)
            updated.append(output.destination)
        else:
            created.append((output, _compose_new(job, output, shading, covered)))

    if not created and not updated:
        job.error("目标排布上没有任何三角形落进贴图范围")
        return None

    outside = sum(output.outside for output in outputs)
    if outside:
        job.warn(f"{outside} 个三角形落在 0~1 外，而读它们的节点越界方式是延展/裁剪，排布里放不下，未写入")
    if conflicts:
        job.warn(f"目标排布里有 {conflicts} 个像素被内容不同的面重叠覆盖，已取平均")
    if clashes:
        job.warn(f"{clashes} 个像素与其他网格用到的区域重叠，为保护它们未写入")
    if job.unprotected:
        job.warn(f"这些网格读目标图的坐标无法判定，写入时没能避开它们: {', '.join(sorted(job.unprotected))}")
    fate = "保持目标图原样" if job.writes_existing else "留空"
    for output in outputs:
        if output.uncovered:
            job.warn(f"'{output.key}' 在这些面上没有同标签的来源，那里{fate}: {', '.join(output.uncovered)}")
    if job.turned_data_images and not job.normals_declared:
        job.warn(f"有孤岛旋转/镜像过，但这次没有任何贴图被当作切线法线，这些非颜色贴图按普通数值搬运: "
                 f"{', '.join(sorted(job.turned_data_images))} —— 其中若有切线法线贴图，把它的节点标签填进「切线法线」")

    return {
        'outputs': [image for _output, image in created] + updated,
        'created': created,
        'updated': updated,
    }


def apply(job, result):
    """新建的贴图接回要读它的那些节点；写入现有贴图的节点不用动。"""
    for output, image in result['created']:
        for node in output.rebind:
            node.image = image
