"""numpy 后端：逐节点解释着色器数学的图，输入可以是标量（参数）或数组（逐样本的量），输出是 float32。

用过一次就不再被后面用到的中间数组立刻释放，峰值内存只跟图的宽度有关，与图的节点数无关。不引用 bpy。
"""

import numpy as np

from . import language
from . import primitives


def _needed(program, wanted):
    needed = {program.outputs[name] for name in wanted}
    for index in range(len(program.nodes) - 1, -1, -1):
        if index in needed:
            needed.update(program.nodes[index].args)
    return sorted(needed)


def evaluate(program, values, wanted=None):
    """values 是 {输入名: 标量或数组}；wanted 是要的输出名（默认全部）；返回 {输出名: float32 数组或标量}。"""
    wanted = tuple(program.outputs) if wanted is None else tuple(wanted)
    order = _needed(program, wanted)
    keep = {program.outputs[name] for name in wanted}
    last_use = {}
    for index in order:
        for argument in program.nodes[index].args:
            last_use[argument] = index
    cache = {}
    for index in order:
        node = program.nodes[index]
        if node.op == language.CONSTANT:
            cache[index] = primitives.FLOAT(node.value)
        elif node.op == language.INPUT:
            cache[index] = np.asarray(values[node.value], dtype=primitives.FLOAT)
        elif node.op == language.TABLE:
            table = program.tables[node.value]
            cache[index] = primitives.interpolate(table.positions, table.values, cache[node.args[0]])
        else:
            cache[index] = primitives.PRIMITIVES[node.op](*(cache[argument] for argument in node.args))
        for argument in node.args:
            if last_use[argument] == index and argument not in keep:
                cache.pop(argument, None)
    return {name: cache[program.outputs[name]] for name in wanted}
