"""预览用的网格角属性：把发片每个面角的程序输入（attributes.build 的表）三个一组写成 CORNER 三分量向量属性，预览材质里的属性节点读它们再拆开。

GPU 材质最多读 15 个网格属性，超了 EEVEE 整个材质编译失败，所以输入打包成向量，打包方式在 HairProcedural.json。
没有被任何发片覆盖到的面角取输入的缺省值。属性名以点开头，不出现在物体数据面板的属性列表里；清理按名字前缀删，不认具体名字。
"""

import bmesh
import numpy as np

from ...uv.uv_transfer import mesh_bind
from . import attributes
from . import procedural
from . import strips

STORAGE_DOMAIN = 'CORNER'
STORAGE_TYPE = 'FLOAT_VECTOR'


def write(obj, scene, uv_layer_name):
    """给物体写（或刷新）全部角属性；返回 (发片数, 不规则孤岛的原因汇总)。物体要在物体模式。"""
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.index_update()
        uv_layer = bm.loops.layers.uv.get(uv_layer_name or mesh_bind.render_uv_name(mesh))
        if uv_layer is None:
            raise ValueError("物体 '%s' 没有 UV 层 '%s'" % (obj.name, uv_layer_name))
        found, rejected = strips.collect(obj, bm, uv_layer, scene)
        table = attributes.build(found, uv_layer)
    finally:
        bm.free()
    defaults = procedural.default_geometry()
    column_of = {name: column for column, name in enumerate(attributes.ORDER)}
    for attribute, members in procedural.geometry_packs().items():
        values = np.zeros((len(mesh.loops), procedural.VECTOR_SIZE), dtype=np.float32)
        for component, name in enumerate(members):
            if name is not None:
                values[:, component] = defaults[name]
                values[table.loops, component] = table.values[:, column_of[name]]
        layer = mesh.attributes.get(attribute) or mesh.attributes.new(attribute, STORAGE_TYPE, STORAGE_DOMAIN)
        layer.data.foreach_set("vector", values.reshape(-1))
    mesh.update()
    return len(found), rejected


def remove(obj):
    prefix = procedural.attribute_prefix()
    for layer in [layer for layer in obj.data.attributes if layer.name.startswith(prefix)]:
        obj.data.attributes.remove(layer)
