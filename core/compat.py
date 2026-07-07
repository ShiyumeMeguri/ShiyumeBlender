"""Blender 4.x / 5.x API 兼容层。

统一封装三处跨版本差异,其余模块一律只经此层访问:
1. Action 动画曲线 —— 5.0 槽位化动画系统(layers/strips/channelbags)与 4.x 传统 fcurves。
2. UV 选择状态 —— 5.x 移除 BMLoopUV.select,状态迁入隐藏 bool loop 层 ".vs.<UV名>"。
3. 颜色属性 —— 统一走 color_attributes,不触碰已废弃的 vertex_colors。
"""

import bmesh
import bpy


# ---------------------------------------------------------------------------
# Action 动画曲线(4.x fcurves / 5.x 槽位化)
# ---------------------------------------------------------------------------

def iter_action_fcurves(action):
    """逐条产出 (归属集合, fcurve);归属集合支持 .remove(fcurve)。"""
    if action is None:
        return
    if hasattr(action, 'fcurves'):
        for fcurve in action.fcurves:
            yield action.fcurves, fcurve
        return
    if hasattr(action, 'layers'):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, 'channelbags'):
                    for bag in strip.channelbags:
                        for fcurve in bag.fcurves:
                            yield bag.fcurves, fcurve


def list_action_fcurves(action):
    """一次性快照;遍历途中要删曲线时必须用这个。"""
    return list(iter_action_fcurves(action))


def get_active_action(obj):
    """物体上的激活 Action,没有返回 None。"""
    if obj is None:
        return None
    animation_data = getattr(obj, 'animation_data', None)
    if animation_data is None:
        return None
    return animation_data.action


# ---------------------------------------------------------------------------
# UV 选择状态(bmesh,同步模式感知,4.x/5.x 双轨)
# ---------------------------------------------------------------------------

def bm_uv_select_predicate(bm, uv_layer, tool_settings):
    """返回 `loop -> 是否选中` 的判断函数。

    同步选择开启时跟随网格面选择;关闭时读 UV 编辑器自身的选择状态:
    4.x 走 BMLoopUV.select,5.x 走隐藏 bool 层 ".vs.<UV名>"(懒创建,不存在=从未选过)。
    """
    if tool_settings.use_uv_select_sync:
        return lambda loop: loop.face.select
    if hasattr(bmesh.types.BMLoopUV, "select"):
        return lambda loop: loop[uv_layer].select
    select_layer = bm.loops.layers.bool.get(".vs." + uv_layer.name)
    if select_layer is None:
        return lambda loop: False
    return lambda loop: loop[select_layer]


# ---------------------------------------------------------------------------
# 颜色属性
# ---------------------------------------------------------------------------

def ensure_active_color_attribute(mesh):
    """取激活颜色属性;一个都没有则新建传统等价物(CORNER 域 BYTE_COLOR)。"""
    attributes = mesh.color_attributes
    attribute = attributes.active_color
    if attribute is None:
        attribute = attributes.new(name="Color", type='BYTE_COLOR', domain='CORNER')
        attributes.active_color = attribute
    return attribute


# ---------------------------------------------------------------------------
# 形态键杂项
# ---------------------------------------------------------------------------

def copy_shape_key_settings(source_shape_keys, new_obj):
    """把旧形态键的滑杆范围 / 静音 / 插值 / 顶点组 / 相对键关系复制到新物体的同名键上。"""
    new_shape_keys = new_obj.data.shape_keys
    if not source_shape_keys or not new_shape_keys:
        return

    source_blocks = source_shape_keys.key_blocks
    new_blocks = new_shape_keys.key_blocks

    relative_names = {}
    for source_key in source_blocks:
        relative_names[source_key.name] = (
            source_key.relative_key.name if source_key.relative_key else None
        )

    for source_key in source_blocks:
        new_key = new_blocks.get(source_key.name)
        if new_key is None:
            continue
        new_key.value = source_key.value
        new_key.slider_min = source_key.slider_min
        new_key.slider_max = source_key.slider_max
        new_key.mute = source_key.mute
        new_key.interpolation = source_key.interpolation
        new_key.vertex_group = source_key.vertex_group

    for source_key in source_blocks:
        new_key = new_blocks.get(source_key.name)
        relative_name = relative_names.get(source_key.name)
        if new_key is None or relative_name is None:
            continue
        relative_key = new_blocks.get(relative_name)
        if relative_key is not None:
            new_key.relative_key = relative_key
