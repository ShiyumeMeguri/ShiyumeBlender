"""头发程序化生成的数学：一份着色器数学程序（HairNoise.Math 与 HairProcedural.Math），输入输出与界面在 HairProcedural.json。

同一张图两处解释：numpy 后端给烘焙，节点后端搭成实时预览用的节点组，所以预览看到的就是烘焙写出的。
色域、疏密、变异幅度这些数据来自 HairColorGamut.json 与 HairDensity.json，在这里变成程序的常量与查表。
"""

import functools
import json
import os

import numpy as np

from ..shader_math import language
from ..shader_math import node_backend
from ..shader_math import numpy_backend

SPEC_FILE = "HairProcedural.json"
GAMUT_FILE = "HairColorGamut.json"
DENSITY_FILE = "HairDensity.json"
GAMUT_TABLES = (("gamutChromaHigh", "ChromaHigh"), ("gamutLightnessLow", "LightnessLow"), ("gamutLightnessHigh", "LightnessHigh"))
DEGREES_PER_TURN = 360.0
VECTOR_SIZE = 3
VERSION_KEY = "shiyume_hair_version"


def _read(name):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name), encoding="utf-8") as stream:
        return json.load(stream)


def _text(name):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name), encoding="utf-8") as stream:
        return stream.read()


def _packs_of(data):
    prefix = data["AttributePrefix"]
    packs = {}
    for entry in data["Inputs"]:
        if "Attribute" not in entry:
            continue
        members = packs.setdefault(prefix + entry["Attribute"], [None] * VECTOR_SIZE)
        if members[entry["Component"]] is not None:
            raise ValueError("网格属性 %s 的第 %d 个分量被 %s 与 %s 重复占用" % (entry["Attribute"], entry["Component"], members[entry["Component"]], entry["Name"]))
        members[entry["Component"]] = entry["Name"]
    if len(packs) > data["MaximumAttributes"]:
        raise ValueError("预览材质要读 %d 个网格属性，GPU 材质最多 %d 个，超了 EEVEE 整个材质编译失败" % (len(packs), data["MaximumAttributes"]))
    return packs


@functools.cache
def spec():
    data = _read(SPEC_FILE)
    _packs_of(data)
    return data


def _wrapped_table(hues, values):
    """色相是一圈：在 0 与 1 两端补上跨过 360 度的插值值，查表在整圈上连续。"""
    first = hues[0]
    last = hues[-1] - DEGREES_PER_TURN
    seam = values[-1] + (values[0] - values[-1]) * (0.0 - last) / (first - last)
    return [0.0] + [hue / DEGREES_PER_TURN for hue in hues] + [1.0], [seam] + list(values) + [seam]


def _constants(gamut, density):
    variation = gamut["Variation"]
    neutral = gamut["Neutral"]
    constants = dict(spec()["Constants"])
    constants.update({
        "ReferenceMillimetresPerUnit": density["ReferenceMillimetresPerUnit"],
        "ReferenceResolution": density["ReferenceResolution"],
        "FieldSpacing": variation["FieldSpacing"],
        "FieldLightness": variation["FieldLightness"],
        "FieldHue": variation["FieldHue"],
        "FieldChroma": variation["FieldChroma"],
        "CardLightness": variation["CardLightness"],
        "CardHue": variation["CardHue"],
        "CardChroma": variation["CardChroma"],
        "StrandLightness": variation["StrandLightness"],
        "StrandChroma": variation["StrandChroma"],
        "NeutralLightnessLow": neutral["LightnessLow"],
        "NeutralLightnessHigh": neutral["LightnessHigh"],
    })
    return constants


def _tables(gamut):
    hues = [entry["Hue"] for entry in gamut["HueBins"]]
    return {name: _wrapped_table(hues, [entry[key] for entry in gamut["HueBins"]]) for name, key in GAMUT_TABLES}


@functools.cache
def _gamut_tables():
    return _tables(_read(GAMUT_FILE))


def gamut_chroma_limit(hue):
    """色相 hue（度）处参考头发实际占用的浓淡上限。"""
    positions, values = _gamut_tables()["gamutChromaHigh"]
    return float(np.interp((hue / DEGREES_PER_TURN) % 1.0, positions, values))


def input_names():
    names = []
    for entry in spec()["Inputs"]:
        names.extend(entry["Components"] if entry.get("Type") == "Color" else [entry["Name"]])
    return names


@functools.cache
def program():
    source = "\n".join(_text(name) for name in spec()["Sources"])
    return language.compile_source(source, input_names(), spec()["Outputs"], _constants(_read(GAMUT_FILE), _read(DENSITY_FILE)), _tables(_read(GAMUT_FILE)))


def attribute_prefix():
    return spec()["AttributePrefix"]


def geometry_inputs():
    """程序里来自网格属性的输入，按描述里的顺序：{输入名: (网格属性名, 在属性里的分量下标)}。"""
    prefix = attribute_prefix()
    return {entry["Name"]: (prefix + entry["Attribute"], entry["Component"]) for entry in spec()["Inputs"] if "Attribute" in entry}


def geometry_packs():
    """{网格属性名: [每个分量对应的输入名，空着的分量是 None]}：三个输入共用一个三分量向量属性，GPU 材质读的属性数有上限。"""
    return _packs_of(spec())


def default_parameters():
    values = {}
    for entry in spec()["Inputs"]:
        if "Attribute" in entry:
            continue
        if entry.get("Type") == "Color":
            values.update(zip(entry["Components"], entry["Default"]))
        else:
            values[entry["Name"]] = float(entry["Default"])
    return values


def is_current(group):
    """节点组是不是这一版做的：接口或预览结构一变就升 HairProcedural.json 的 Version，旧版留在存盘里的预览一律不认，取消重来。"""
    return group is not None and group.get(VERSION_KEY) == spec()["Version"]


def default_geometry():
    """来自网格属性的输入的缺省值（没有被发片覆盖到的面角取它）。"""
    return {entry["Name"]: float(entry["Default"]) for entry in spec()["Inputs"] if "Attribute" in entry}


def parameters_of(node):
    """从预览节点组实例读出参数：{程序输入名: 浮点}，颜色拆成三个分量。"""
    values = {}
    for entry in spec()["Inputs"]:
        if "Attribute" in entry:
            continue
        value = node.inputs[node_backend.label_of(entry)].default_value
        if entry.get("Type") == "Color":
            values.update(zip(entry["Components"], (float(channel) for channel in value[:3])))
        else:
            values[entry["Name"]] = float(value)
    return values


def apply_parameters(node, values):
    """把 {程序输入名: 值} 写进预览节点组实例的输入；没给的输入不动。"""
    for entry in spec()["Inputs"]:
        if "Attribute" in entry:
            continue
        socket = node.inputs[node_backend.label_of(entry)]
        if entry.get("Type") == "Color":
            if all(component in values for component in entry["Components"]):
                socket.default_value = (*(values[component] for component in entry["Components"]), 1.0)
        elif entry["Name"] in values:
            value = values[entry["Name"]]
            socket.default_value = bool(value) if entry.get("Type") == "Boolean" else int(value) if entry.get("Type") == "Integer" else float(value)


def set_parameter(node, name, value):
    apply_parameters(node, {name: value})


def evaluate(parameters, geometry, wanted):
    """parameters 是 parameters_of 那样的标量字典，geometry 是 {输入名: 逐样本数组}；返回 {输出名: 数组}。"""
    return numpy_backend.evaluate(program(), {**parameters, **geometry}, wanted)


def build_group(name=None):
    group = node_backend.build_group(program(), name or spec()["Name"], spec()["Inputs"], spec()["Outputs"], spec()["Panels"])
    group[VERSION_KEY] = spec()["Version"]
    return group
