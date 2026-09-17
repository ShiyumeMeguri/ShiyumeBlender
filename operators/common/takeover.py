"""进编辑模式那一刻的接管。

跟源的数据块是库覆盖, Blender 不让进编辑模式 —— 报的是
`RuntimeError: Error: Unable to execute 'Edit Mode', error changing modes`。
更要命的是**直接写顶点不报错**: 当场读得回来, 存盘重开被 resync 静默抹掉。所以接管不是
图方便, 是正确性要求: 任何几何改动之前必须先把数据块摘下来。

Blender 没有"算子失败"钩子, 所以只能抢在前面。Tab 挂在 Object Non-modal 键位图上 ——
插件键位图先于默认键位图求值, 于是这一下先落到本算子手里: 该摘的摘掉, 再原样转发给
`object.editmode_toggle`。不该摘的一个字不动, 行为与原生完全一致。

头部那个模式下拉菜单走的是 RNA 属性不是算子, 拦不到; 面板上那个按钮就是给那条路兜底的。
"""

import bpy

from . import linkage


def _pending(context):
    """这一下 Tab 会把哪些跟源的数据块带进编辑模式。

    多物体编辑时选中的物体一起进, 所以要一起摘 —— 只摘活动物体的话, 其余那几个进去之后
    改了也是白改。
    """
    objects = list(context.selected_objects) or []
    active = context.active_object
    if active is not None and active not in objects:
        objects.append(active)
    seen = []
    for obj in objects:
        datablock = obj.data
        if datablock is None or not linkage.is_attached(datablock):
            continue
        if datablock not in seen:
            seen.append(datablock)
    return seen


class SHIYUME_OT_EditTakeover(bpy.types.Operator):
    """进编辑模式; 数据块还跟着源就先把它摘下来, 摘完再进。"""

    bl_idname = "shiyume.edit_takeover"
    bl_label = "编辑 (必要时先摘下共用数据)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        detached = []
        if context.active_object.mode == 'OBJECT':
            for datablock in _pending(context):
                try:
                    linkage.detach(datablock)
                except Exception as error:      # noqa: BLE001 摘不动要说清楚, 别闷着
                    self.report({'ERROR'}, "%s 摘不下来: %s" % (datablock.name, error))
                    return {'CANCELLED'}
                detached.append(datablock.name)
        try:
            bpy.ops.object.editmode_toggle()
        except RuntimeError as error:
            self.report({'ERROR'}, "进编辑模式失败: %s" % error)
            return {'CANCELLED'}
        if detached:
            self.report({'INFO'}, "已摘下 %d 份共用数据, 改完记得推送: %s"
                        % (len(detached), ", ".join(detached[:4])))
        return {'FINISHED'}


class SHIYUME_OT_DetachActive(bpy.types.Operator):
    """把选中物体的数据块从源上摘下来 (不进编辑模式)。

    头部的模式下拉菜单拦不到, 用那条路进编辑模式之前先按这个。
    """

    bl_idname = "shiyume.detach_active"
    bl_label = "摘下共用数据以便编辑"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_pending(context))

    def execute(self, context):
        names = []
        for datablock in _pending(context):
            try:
                linkage.detach(datablock)
            except Exception as error:          # noqa: BLE001
                self.report({'ERROR'}, "%s 摘不下来: %s" % (datablock.name, error))
                return {'CANCELLED'}
            names.append(datablock.name)
        self.report({'INFO'}, "已摘下 %d 份: %s" % (len(names), ", ".join(names[:6])))
        return {'FINISHED'}


classes = (SHIYUME_OT_EditTakeover, SHIYUME_OT_DetachActive)

_keymap_items = []


def register_keymap():
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return
    keymap = keyconfig.keymaps.new(name='Object Non-modal')
    item = keymap.keymap_items.new(SHIYUME_OT_EditTakeover.bl_idname, 'TAB', 'PRESS')
    _keymap_items.append((keymap, item))


def unregister_keymap():
    for keymap, item in _keymap_items:
        keymap.keymap_items.remove(item)
    _keymap_items.clear()
