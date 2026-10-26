"""预览接线：没装导入器时把锚定贴图接回 Principled 材质，以及 flat 预览（不开渲染模式）要的活动纹理节点与视口设置。

图像节点读锚定贴图；法线贴图节点把 RGB 当切线空间法线、A（生成遮罩）当强度，接到还没接法线的 Principled BSDF；
颜色贴图接到还没接的 Base Color。节点按标签认领，重复生成只更新图，不重复建节点。
"""

import numpy as np

NORMAL_IMAGE_LABEL = "ShiyumeHairNormal"
COLOR_IMAGE_LABEL = "ShiyumeHairBaseColor"
NORMAL_LABEL = "ShiyumeHairNormalMap"
UV_LABEL = "ShiyumeHairNormalUV"
LINEAR_BREAK = 0.04045


def _node(tree, type_name, label, location):
    for node in tree.nodes:
        if node.bl_idname == type_name and node.label == label:
            return node
    node = tree.nodes.new(type_name)
    node.label = label
    node.location = location
    return node


def attach(material, normal_image, color_image, uv_name, render_uv_name):
    """把锚定贴图接进 Principled 材质；返回 (给用户看的话, 预览用的图像节点)。"""
    tree = material.node_tree
    if tree is None:
        return "材质 '%s' 没有节点树，贴图已存好但没有接" % material.name, None
    shaders = [node for node in tree.nodes if node.bl_idname == 'ShaderNodeBsdfPrincipled']
    if not shaders:
        return "材质 '%s' 里没有 Principled BSDF，贴图已存好，自己接节点读它们" % material.name, None
    coordinates = None
    if uv_name != render_uv_name:
        coordinates = _node(tree, 'ShaderNodeUVMap', UV_LABEL, (-950.0, 0.0))
        coordinates.uv_map = uv_name
    texture = _node(tree, 'ShaderNodeTexImage', NORMAL_IMAGE_LABEL, (-700.0, 0.0))
    texture.image = normal_image
    normal = _node(tree, 'ShaderNodeNormalMap', NORMAL_LABEL, (-350.0, 0.0))
    normal.space = 'TANGENT'
    normal.uv_map = uv_name
    tree.links.new(texture.outputs['Color'], normal.inputs['Color'])
    tree.links.new(texture.outputs['Alpha'], normal.inputs['Strength'])
    painted = None
    if color_image is not None:
        painted = _node(tree, 'ShaderNodeTexImage', COLOR_IMAGE_LABEL, (-700.0, -320.0))
        painted.image = color_image
    if coordinates is not None:
        for node in (texture, painted):
            if node is not None:
                tree.links.new(coordinates.outputs['UV'], node.inputs['Vector'])
    normal_connected = 0
    color_connected = 0
    for shader in shaders:
        if not shader.inputs['Normal'].is_linked:
            tree.links.new(normal.outputs['Normal'], shader.inputs['Normal'])
            normal_connected += 1
        if painted is not None and not shader.inputs['Base Color'].is_linked:
            tree.links.new(painted.outputs['Color'], shader.inputs['Base Color'])
            color_connected += 1
    parts = ["法线接上了" if normal_connected else "法线原来就接着别的，只更新了贴图"]
    if painted is not None:
        parts.append("颜色接上了" if color_connected else "颜色原来就接着别的，只更新了贴图")
    return "材质 '%s'：%s" % (material.name, "，".join(parts)), painted or texture


def activate(material, node):
    """flat 预览读材质的活动纹理节点：把它设成活动的。"""
    tree = material.node_tree
    for other in tree.nodes:
        other.select = False
    node.select = True
    tree.nodes.active = node


def tint(material, srgb_mean):
    """实体视图的「材质」着色取这个颜色（线性）。"""
    srgb = np.clip(np.asarray(srgb_mean, dtype=np.float64), 0.0, 1.0)
    linear = np.where(srgb <= LINEAR_BREAK, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    material.diffuse_color = (float(linear[0]), float(linear[1]), float(linear[2]), 1.0)


def show_material_preview(context):
    """当前 3D 视口切到材质预览（实体与线框视图看不到节点材质的效果）；没有 3D 视口返回 False。"""
    space = context.space_data
    if space is None or space.type != 'VIEW_3D':
        return False
    if space.shading.type in {'WIREFRAME', 'SOLID'}:
        space.shading.type = 'MATERIAL'
    return True


def show_flat(context):
    """当前 3D 视口切到实体 + Flat 光照 + 贴图颜色，不开渲染模式就能看颜色；没有 3D 视口返回 False。"""
    space = context.space_data
    if space is None or space.type != 'VIEW_3D':
        return False
    space.shading.type = 'SOLID'
    space.shading.light = 'FLAT'
    space.shading.color_type = 'TEXTURE'
    return True
