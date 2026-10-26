"""预览层的材质：材质里只有一个预览节点组实例，节点组里是读网格角属性的属性节点、头发程序节点组实例和自发光，
算出的颜色（或法线编码色）直接当自发光输出，不受光照，所见即烘焙的内容。

参数在预览节点组里那个头发程序实例的输入上。同一个头发的各张材质的基础层共用同一个预览节点组，所以改一处，头发和羽毛这些不同材质一起变；
局部层各用自己的预览节点组。材质上的标记与指向原材质、所属物体的指针见 layers。
"""

import bpy

from . import layers
from . import procedural

NODE_SPACING = 300.0
SOLID_DISPLAY_ALPHA = 1.0
SHADER_OUTPUT = "Shader"


def generator_group():
    group = bpy.data.node_groups.get(procedural.spec()["Name"])
    if group is None:
        return procedural.build_group()
    if not procedural.is_current(group):
        raise ValueError("文件里有旧版本留下的头发预览，先点「取消预览」清掉再开始")
    return group


def create_group(parameters):
    """新建一个预览节点组并按 {程序输入名: 值} 设好参数：属性节点读网格角属性，进头发程序，出自发光。"""
    group = bpy.data.node_groups.new(procedural.spec()["PreviewName"], 'ShaderNodeTree')
    group.interface.new_socket(SHADER_OUTPUT, in_out='OUTPUT', socket_type='NodeSocketShader')
    nodes = group.nodes
    links = group.links
    generator = nodes.new('ShaderNodeGroup')
    generator.name = layers.GENERATOR_NODE
    generator.label = "头发程序参数"
    generator.node_tree = generator_group()
    generator.location = (0.0, 0.0)
    generator.width = 280.0
    labels = {entry["Name"]: entry.get("Label", entry["Name"]) for entry in procedural.spec()["Inputs"]}
    for row, (attribute, members) in enumerate(procedural.geometry_packs().items()):
        reader = nodes.new('ShaderNodeAttribute')
        reader.attribute_type = 'GEOMETRY'
        reader.attribute_name = attribute
        reader.location = (-2.0 * NODE_SPACING, -row * 60.0)
        reader.hide = True
        split = nodes.new('ShaderNodeSeparateXYZ')
        split.location = (-NODE_SPACING, -row * 60.0)
        split.hide = True
        links.new(reader.outputs["Vector"], split.inputs["Vector"])
        for component, input_name in enumerate(members):
            if input_name is not None:
                links.new(split.outputs[component], generator.inputs[labels[input_name]])
    combine = nodes.new('ShaderNodeCombineColor')
    combine.location = (NODE_SPACING, 0.0)
    emission = nodes.new('ShaderNodeEmission')
    emission.location = (2.0 * NODE_SPACING, 0.0)
    output = nodes.new('NodeGroupOutput')
    output.location = (3.0 * NODE_SPACING, 0.0)
    for channel, name_of_output in (("Red", "displayRed"), ("Green", "displayGreen"), ("Blue", "displayBlue")):
        links.new(generator.outputs[name_of_output], combine.inputs[channel])
    links.new(combine.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs[SHADER_OUTPUT])
    procedural.apply_parameters(generator, parameters)
    group[layers.MARKER] = True
    group[procedural.VERSION_KEY] = procedural.spec()["Version"]
    return group


def create(name, original, owner, group):
    """新建一层：original 是烘焙时贴图落点所属的原材质，owner 是局部层所属的物体（基础层给 None），group 是这一层用的预览节点组。"""
    material = bpy.data.materials.new(name)
    tree = material.node_tree
    tree.nodes.clear()
    holder = tree.nodes.new('ShaderNodeGroup')
    holder.name = layers.PREVIEW_NODE
    holder.node_tree = group
    holder.location = (0.0, 0.0)
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    output.location = (NODE_SPACING, 0.0)
    tree.links.new(holder.outputs[SHADER_OUTPUT], output.inputs["Surface"])
    material[layers.MARKER] = True
    material[layers.ORIGINAL] = original
    if owner is not None:
        material[layers.OWNER] = owner
    parameters = procedural.parameters_of(layers.generator_of(material))
    material.diffuse_color = (parameters["rootRed"], parameters["rootGreen"], parameters["rootBlue"], SOLID_DISPLAY_ALPHA)
    return material


def remove_unused_groups():
    """没有材质再用的预览节点组删掉，然后没有预览节点组再用的头发程序节点组也删掉。"""
    for group in [group for group in bpy.data.node_groups if layers.MARKER in group and group.users == 0]:
        bpy.data.node_groups.remove(group)
    generator = bpy.data.node_groups.get(procedural.spec()["Name"])
    if generator is not None and generator.users == 0:
        bpy.data.node_groups.remove(generator)
