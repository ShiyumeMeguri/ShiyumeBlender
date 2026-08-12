"""颜色源注册表：新增一种取色方式 = 加一条 descriptor，不动管线。

descriptor 只提供两个函数：run 产出图像，apply 把结果接回材质。
其余环节（UV 校验、写盘、UV 层收尾、汇报）全部由算子统一处理。
"""

from . import bake
from . import resample


class ColorSource:
    def __init__(self, identifier, label, description, run, apply):
        self.identifier = identifier
        self.label = label
        self.description = description
        self.run = run
        self.apply = apply


REGISTRY = (
    ColorSource(
        'IMAGE', "重采样贴图",
        "把源 UV 上的已有贴图逐像素重采样到目标 UV 排布，不经渲染引擎",
        resample.run, resample.apply,
    ),
    ColorSource(
        'BAKE', "烘焙最终颜色",
        "用 Cycles 烘焙材质算完的颜色到目标 UV 排布，可重定向程序化着色结果",
        bake.run, bake.apply,
    ),
)

_BY_IDENTIFIER = {source.identifier: source for source in REGISTRY}


def enum_items():
    return [(source.identifier, source.label, source.description)
            for source in REGISTRY]


def get(identifier):
    return _BY_IDENTIFIER[identifier]
