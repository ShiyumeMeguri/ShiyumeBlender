"""BAKE 颜色源：用 Cycles 把材质的最终着色结果烘焙到目标 UV 排布。

与 IMAGE 源的区别在于它取的是着色器算完的颜色（含程序化节点、光照），
因此能重定向"最终颜色"而不只是某一张已有贴图。边缘外扩交给 Cycles 自己的
bake margin——它基于烘焙器自身的覆盖信息，不该由外部再猜一遍。
"""

import bpy

from . import graph_bind
from . import image_bind
from . import mesh_bind

_BAKE_NODE_NAME = "_ShiyumeBakeTarget"


def _resolve_size(job):
    """'跟随源图' 对烘焙意味着沿用源 UV 上最大的那张贴图尺寸，以保持纹素密度。"""
    if job.settings.resolution != 'SOURCE':
        size = int(job.settings.resolution)
        return size, size

    width = 0
    height = 0
    for mesh in job.meshes.values():
        render_uv = mesh_bind.render_uv_name(mesh)
        for material in mesh.materials:
            bound, _unknown = graph_bind.image_nodes_using_uv(
                material, job.source_uv, render_uv)
            for _node, image in bound:
                width = max(width, image.size[0])
                height = max(height, image.size[1])
    return width, height


def _unique_materials(job):
    materials = {}
    for mesh in job.meshes.values():
        for material in mesh.materials:
            if material is not None and material.use_nodes and material.node_tree:
                materials[material.as_pointer()] = material
    return list(materials.values())


def _add_bake_targets(materials, image):
    """给每个材质插入一个被选中且激活的图像纹理节点——Cycles 以此确定烘焙目标。"""
    created = []
    for material in materials:
        tree = material.node_tree
        node = tree.nodes.new('ShaderNodeTexImage')
        node.name = _BAKE_NODE_NAME
        node.label = _BAKE_NODE_NAME
        node.image = image
        node.location = (400, 400)
        for other in tree.nodes:
            other.select = False
        node.select = True
        tree.nodes.active = node
        created.append((tree, node))
    return created


def _remove_bake_targets(created):
    for tree, node in created:
        if node.name in tree.nodes:
            tree.nodes.remove(node)


def _capture_scene(scene):
    bake = scene.render.bake
    return {
        'engine': scene.render.engine,
        'samples': scene.cycles.samples if hasattr(scene, 'cycles') else None,
        'margin': bake.margin,
        'margin_type': bake.margin_type,
        'use_clear': bake.use_clear,
        'target': bake.target,
        'use_selected_to_active': bake.use_selected_to_active,
        'use_pass_direct': bake.use_pass_direct,
        'use_pass_indirect': bake.use_pass_indirect,
        'use_pass_color': bake.use_pass_color,
    }


def _restore_scene(scene, state):
    bake = scene.render.bake
    scene.render.engine = state['engine']
    if state['samples'] is not None and hasattr(scene, 'cycles'):
        scene.cycles.samples = state['samples']
    bake.margin = state['margin']
    bake.margin_type = state['margin_type']
    bake.use_clear = state['use_clear']
    bake.target = state['target']
    bake.use_selected_to_active = state['use_selected_to_active']
    bake.use_pass_direct = state['use_pass_direct']
    bake.use_pass_indirect = state['use_pass_indirect']
    bake.use_pass_color = state['use_pass_color']


def _configure_scene(scene, settings):
    bake = scene.render.bake
    scene.render.engine = 'CYCLES'
    if hasattr(scene, 'cycles'):
        scene.cycles.samples = settings.bake_samples
    bake.margin = settings.margin
    bake.margin_type = 'ADJACENT_FACES'
    bake.use_clear = True
    bake.target = 'IMAGE_TEXTURES'
    bake.use_selected_to_active = False
    if settings.bake_type == 'DIFFUSE':
        bake.use_pass_direct = False
        bake.use_pass_indirect = False
        bake.use_pass_color = True


def run(job):
    settings = job.settings
    scene = job.context.scene

    width, height = _resolve_size(job)
    if width <= 0 or height <= 0:
        job.error("'跟随源图' 需要源 UV 上至少有一张贴图；请改选明确的分辨率")
        return None

    materials = _unique_materials(job)
    if not materials:
        job.error("选中网格上没有使用节点的材质，无法烘焙")
        return None

    name = image_bind.unique_name(
        f"{job.objects[0].name}_Bake", job.output_directory)
    image = image_bind.create(name, width, height, use_float=False)

    state = _capture_scene(scene)
    created = _add_bake_targets(materials, image)
    try:
        _configure_scene(scene, settings)

        bpy.ops.object.select_all(action='DESELECT')
        for obj in job.objects:
            obj.select_set(True)
        job.context.view_layer.objects.active = job.objects[0]

        bpy.ops.object.bake(type=settings.bake_type, uv_layer=job.target_uv)
    except RuntimeError as exception:
        job.error(f"Cycles 烘焙失败: {exception}")
        return None
    finally:
        _remove_bake_targets(created)
        _restore_scene(scene, state)

    return {'outputs': [image], 'image': image}


def apply(job, result):
    """把烘焙结果接到每个材质的 Principled Base Color 上。"""
    image = result['image']
    missing = []

    for material in _unique_materials(job):
        tree = material.node_tree
        principled = next(
            (node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED'), None)
        if principled is None:
            missing.append(material.name)
            continue

        base_color = principled.inputs.get("Base Color")
        if base_color is None:
            missing.append(material.name)
            continue

        texture = None
        if base_color.links:
            linked = base_color.links[0].from_node
            if linked.type == 'TEX_IMAGE':
                texture = linked
        if texture is None:
            texture = tree.nodes.new('ShaderNodeTexImage')
            texture.location = (principled.location.x - 300, principled.location.y)
            tree.links.new(texture.outputs['Color'], base_color)
        texture.image = image

    if missing:
        job.warn(f"这些材质没有 Principled BSDF，烘焙图未接入: {', '.join(missing)}")
