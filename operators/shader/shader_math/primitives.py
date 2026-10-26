"""着色器数学的原语：每个原语在 numpy 里按 float32 实现，语义与 Blender 数学节点逐个对齐（除零、负数开方、对数、乘方都取节点的安全结果），
哈希噪声是 Blender 白噪声节点的 Jenkins 哈希的逐位移植，所以同一个键在 numpy 与着色器里得到同一个随机数。

原语的名字、元数与对应的 Blender 数学节点运算在 primitives.json 里，这里只有它们的数值实现。不引用 bpy。
"""

import functools
import json
import os

import numpy as np

PRIMITIVE_FILE = "primitives.json"
FLOAT = np.float32
HASH_BASE = 0xDEADBEEF
HASH_SCALE = FLOAT(2.0 ** -32)
RAMP_NAME = "table"


@functools.cache
def definitions():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), PRIMITIVE_FILE), encoding="utf-8") as stream:
        return json.load(stream)


def _real(values):
    return np.asarray(values, dtype=FLOAT)


def _add(first, second):
    return _real(first + second)


def _sub(first, second):
    return _real(first - second)


def _mul(first, second):
    return _real(first * second)


def _div(first, second):
    first, second = np.broadcast_arrays(_real(first), _real(second))
    result = np.zeros(first.shape, dtype=FLOAT)
    np.divide(first, second, out=result, where=second != 0)
    return result


def _pow(first, second):
    first, second = np.broadcast_arrays(_real(first), _real(second))
    undefined = (first < 0) & (second != np.trunc(second))
    with np.errstate(all="ignore"):
        result = np.power(first, second)
    result = np.where(second == 0, FLOAT(1.0), np.where(first == 0, FLOAT(0.0), result))
    return _real(np.where(undefined, FLOAT(0.0), result))


def _madd(first, second, third):
    return _real(np.asarray(first, dtype=np.float64) * np.asarray(second, dtype=np.float64) + np.asarray(third, dtype=np.float64))


def _ln(values, base=FLOAT(2.718281828459045)):
    values = _real(values)
    with np.errstate(all="ignore"):
        result = np.log(values) / np.log(FLOAT(base))
    return _real(np.where(values > 0, result, FLOAT(0.0)))


def _exp(values):
    with np.errstate(all="ignore"):
        return _real(np.exp(_real(values)))


def _sqrt(values):
    values = _real(values)
    return _real(np.sqrt(np.where(values > 0, values, FLOAT(0.0))))


def _fract(values):
    values = _real(values)
    return _real(values - np.floor(values))


def _sign(values):
    values = _real(values)
    return _real(np.where(values > 0, FLOAT(1.0), np.where(values < 0, FLOAT(-1.0), FLOAT(0.0))))


def _round(values):
    return _real(np.floor(_real(values) + FLOAT(0.5)))


def _less(first, second):
    return _real(np.where(first < second, FLOAT(1.0), FLOAT(0.0)))


def _greater(first, second):
    return _real(np.where(first > second, FLOAT(1.0), FLOAT(0.0)))


def _unary(function):
    def apply(values):
        with np.errstate(all="ignore"):
            return _real(function(_real(values)))
    return apply


def _binary(function):
    def apply(first, second):
        with np.errstate(all="ignore"):
            return _real(function(_real(first), _real(second)))
    return apply


def _bits(values):
    return np.array(values, dtype=FLOAT).view(np.uint32)


def _rotate(values, amount):
    return (values << np.uint32(amount)) | (values >> np.uint32(32 - amount))


def _final_mix(first, second, third):
    third = third ^ second
    third = third - _rotate(second, 14)
    first = first ^ third
    first = first - _rotate(third, 11)
    second = second ^ first
    second = second - _rotate(first, 25)
    third = third ^ second
    third = third - _rotate(second, 16)
    first = first ^ third
    first = first - _rotate(third, 4)
    second = second ^ first
    second = second - _rotate(first, 14)
    third = third ^ second
    third = third - _rotate(second, 24)
    return third


def _hash(*keys):
    """Blender 白噪声节点的哈希：键是 float32 的位模式，维度不同初值不同。"""
    shape = np.broadcast_shapes(*(np.shape(key) for key in keys))
    bits = [np.broadcast_to(_bits(key), shape).astype(np.uint32) for key in keys]
    start = np.uint32((HASH_BASE + (len(keys) << 2) + 13) & 0xFFFFFFFF)
    first = np.full(shape, start, dtype=np.uint32)
    second = first.copy()
    third = first.copy()
    with np.errstate(over="ignore"):
        if len(keys) == 1:
            first = first + bits[0]
        elif len(keys) == 2:
            second = second + bits[1]
            first = first + bits[0]
        else:
            third = third + bits[2]
            second = second + bits[1]
            first = first + bits[0]
        result = _final_mix(first, second, third)
    return _real(result.astype(FLOAT) * HASH_SCALE)


def _white_noise_one(first):
    return _hash(first)


def _white_noise_two(first, second):
    return _hash(first, second)


def _white_noise_three(first, second, third):
    return _hash(first, second, third)


PRIMITIVES = {
    "add": _add,
    "sub": _sub,
    "mul": _mul,
    "div": _div,
    "pow": _pow,
    "madd": _madd,
    "ln": _ln,
    "exp": _exp,
    "sqrt": _sqrt,
    "abs": _unary(np.abs),
    "floor": _unary(np.floor),
    "ceil": _unary(np.ceil),
    "fract": _fract,
    "sin": _unary(np.sin),
    "cos": _unary(np.cos),
    "tan": _unary(np.tan),
    "tanh": _unary(np.tanh),
    "sign": _sign,
    "round": _round,
    "trunc": _unary(np.trunc),
    "min": _binary(np.minimum),
    "max": _binary(np.maximum),
    "lt": _less,
    "gt": _greater,
    "atan2": _binary(np.arctan2),
    "wn1": _white_noise_one,
    "wn2": _white_noise_two,
    "wn3": _white_noise_three,
}
NOISE_ARITY = {"wn1": 1, "wn2": 2, "wn3": 3}


def arity(name):
    return NOISE_ARITY[name] if name in NOISE_ARITY else definitions()[name]["Arity"]


def interpolate(positions, values, x):
    return _real(np.interp(_real(x), np.asarray(positions, dtype=FLOAT), np.asarray(values, dtype=FLOAT)))
