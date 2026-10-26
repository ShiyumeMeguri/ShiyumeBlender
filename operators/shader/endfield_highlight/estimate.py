"""高光椭球的初始摆放：参考是一对手工调好的头发与椭球，按头发顶部一圈的范围把参考椭球等比搬到新头发上。

世界坐标 Z 朝上；顶部一圈取发顶往下 CapDepth 米内的顶点，范围取 X、Y 的分位数跨度，对离群发丝稳健。
"""

import functools
import json
import math
import os
from collections import namedtuple

import numpy as np

REFERENCE_FILE = "HighlightEllipsoidReference.json"

Placement = namedtuple("Placement", ("center", "euler", "semi_axes"))


@functools.cache
def reference():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), REFERENCE_FILE), encoding="utf-8") as stream:
        return json.load(stream)


def place(points):
    """points 是头发全部顶点的世界坐标 (N, 3)；返回椭球的中心、欧拉角（XYZ 序，弧度）、局部三轴半径。"""
    data = reference()
    top = float(points[:, 2].max())
    cap = points[points[:, 2] >= top - data["CapDepth"]]
    low_x, high_x = np.percentile(cap[:, 0], [data["PercentileLow"], data["PercentileHigh"]])
    low_y, high_y = np.percentile(cap[:, 1], [data["PercentileLow"], data["PercentileHigh"]])
    ratio_x = float(high_x - low_x) / data["CapExtent"][0]
    ratio_y = float(high_y - low_y) / data["CapExtent"][1]
    ratio_z = (ratio_x + ratio_y) / 2.0
    center = (
        float((low_x + high_x) / 2.0) + data["CenterOffset"][0] * ratio_x,
        float((low_y + high_y) / 2.0) + data["CenterOffset"][1] * ratio_y,
        top + data["CenterBelowTop"] * ratio_z,
    )
    semi_axes = (data["SemiAxes"][0] * ratio_x, data["SemiAxes"][1] * ratio_y, data["SemiAxes"][2] * ratio_z)
    return Placement(center, tuple(math.radians(degrees) for degrees in data["EulerDegrees"]), semi_axes)
