"""把发片四边形光栅化进贴图空间：每个像素按重心坐标插值出程序输入（占比、尺度、编号、纹路方向），交给头发程序（procedural）算出输出。

纯 numpy，不引用 bpy；三角形光栅化与外扩沿用 UV 重定向的内核。
"""

from collections import namedtuple

import numpy as np

from ...uv.uv_transfer import kernel
from . import attributes
from . import procedural
from . import quads as quad_module

Field = namedtuple("Field", ("covered", "values", "conflicts"))

SLICE_SAMPLES = 250000
STRIP_BOUND = np.iinfo(np.int32).max
BARYCENTRIC_SOURCE = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]], dtype=np.float32)


def generate(quads, parameters, outputs, width, height):
    """返回 Field：覆盖到的像素 (H, W) bool、outputs 里各输出的值 (H, W, 输出数) 和被不同发片重叠覆盖的像素数。"""
    target, corner_values = quad_module.triangles(quads)
    basis = np.broadcast_to(BARYCENTRIC_SOURCE, (len(target), 3, 2))
    pixel_total = width * height
    covered = np.zeros(pixel_total, dtype=bool)
    values = np.zeros((pixel_total, len(outputs)), dtype=np.float32)
    lowest = np.full(pixel_total, STRIP_BOUND, dtype=np.int32)
    highest = np.full(pixel_total, -1, dtype=np.int32)
    strip_ids = np.unique(quads.strip, return_inverse=True)[1].reshape(-1).astype(np.int32)

    for pixel, weights, triangle in kernel.iter_samples(target, basis, width, height, 1):
        for start in range(0, pixel.size, SLICE_SAMPLES):
            part = slice(start, start + SLICE_SAMPLES)
            part_triangle = triangle[part]
            part_pixel = pixel[part]
            first = weights[part, 0]
            second = weights[part, 1]
            stacked = np.stack((first, second, np.float32(1.0) - first - second), axis=1)
            blended = np.einsum('sc,sck->sk', stacked, corner_values[part_triangle])
            result = procedural.evaluate(parameters, {name: blended[:, column] for column, name in enumerate(attributes.ORDER)}, outputs)
            for column, name in enumerate(outputs):
                values[part_pixel, column] = result[name]
            covered[part_pixel] = True
            quad = strip_ids[part_triangle // quad_module.TRIANGLES_PER_QUAD]
            np.minimum.at(lowest, part_pixel, quad)
            np.maximum.at(highest, part_pixel, quad)

    conflicts = int(np.count_nonzero(covered & (lowest != highest)))
    return Field(covered.reshape(height, width), values.reshape(height, width, len(outputs)), conflicts)
