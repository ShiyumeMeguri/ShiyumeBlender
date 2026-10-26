"""随机配色：从参考头发的配色里抽一套，在明度、浓淡、色相上抖一点，换算成线性 RGB 当发色参数。

一套配色是参考头发整体的颜色，以及（开渐变发梢色时）从发根到发梢两端的颜色，数据在 HairPalette.json；
Oklab 到线性 RGB 的数学与头发程序共用 HairColor.Math，换算走同一个着色器数学解释器。同一个随机数发生器给同一套配色。
"""

import functools
import json
import os

import numpy as np

from ..shader_math import language
from ..shader_math import numpy_backend
from . import procedural

SPEC_FILE = "HairPalette.json"


def _text(name):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name), encoding="utf-8") as stream:
        return stream.read()


@functools.cache
def spec():
    return json.loads(_text(SPEC_FILE))


@functools.cache
def program():
    data = spec()
    return language.compile_source("\n".join(_text(name) for name in data["Sources"]), data["Inputs"], data["Outputs"], {}, {})


def _components(input_name):
    return next(entry["Components"] for entry in procedural.spec()["Inputs"] if entry["Name"] == input_name)


def _linear(color, hue_shift, lightness_shift, chroma_factor):
    data = spec()
    hue = color["Hue"] + hue_shift
    coordinates = (color["Lightness"] + lightness_shift, min(color["Chroma"] * chroma_factor, procedural.gamut_chroma_limit(hue)), hue)
    result = numpy_backend.evaluate(program(), {name: np.array([value], dtype=np.float32) for name, value in zip(data["Inputs"], coordinates)}, data["Outputs"])
    return tuple(float(result[name][0]) for name in data["Outputs"])


def random_scheme(rng, with_tip):
    """{程序输入名: 线性值}：发色三个分量，with_tip 时再加发梢色三个分量。rng 是 random.Random。
    开渐变发梢色时只在发根与发梢真的有明显差别的配色里抽；偏爱浓一点的颜色，参考头发里灰黑米色占大半，全按原比例抽会太素。"""
    data = spec()
    pool = [scheme for scheme in data["Schemes"] if not with_tip or scheme["Distance"] >= data["GradientDistance"]]
    scheme = rng.choices(pool, weights=[item["Whole"]["Chroma"] + data["ChromaWeightFloor"] for item in pool])[0]
    jitter = data["Jitter"]
    hue_shift = rng.uniform(-jitter["Hue"], jitter["Hue"])
    lightness_shift = rng.uniform(-jitter["Lightness"], jitter["Lightness"])
    chroma_factor = 1.0 + rng.uniform(-jitter["ChromaFactor"], jitter["ChromaFactor"])
    result = dict(zip(_components(data["RootInput"]), _linear(scheme["Root" if with_tip else "Whole"], hue_shift, lightness_shift, chroma_factor)))
    if with_tip:
        result.update(zip(_components(data["TipInput"]), _linear(scheme["Tip"], hue_shift, lightness_shift, chroma_factor)))
    return result
