"""进编辑模式那一刻的接管。

跟源的数据块是库覆盖, Blender 不让进编辑模式 —— 报的是
`RuntimeError: Error: Unable to execute 'Edit Mode', error changing modes`。
更要命的是**直接写顶点不报错**: 当场读得回来, 存盘重开被 resync 静默抹掉。所以接管不是
图方便, 是正确性要求: 任何几何改动之前必须先把数据块摘下来。

Blender 没有"算子失败"钩子, 所以只能抢在前面。抢的方式是**跟着用户自己的键位表走, 不认
死 Tab**: 扫一遍用户键位配置里所有"按下去会进编辑模式"的键位项, 每条在插件键位配置里照
原样复制一份指向本算子。插件键位项被并到合并表最前面, 于是这一下先落到本算子手里。

摘完**原样交还**: 返回 `{'PASS_THROUGH'}`, 事件接着往下走, 真正切模式的还是被复制的那条
原生键位项。所以本算子不代替任何东西, 也就吃不掉任何按键 —— 用户把 Tab 换成模式饼菜单
(偏好设置 → 键位映射 → Tab 切换饼菜单) 时, 复制出来的是 Ctrl+Tab 那条, Tab 照常开饼菜单;
换成拖拽出饼菜单时复制的是 Tab 单击那条, 拖拽照常。唯一吃掉按键的情况是**摘不下来**: 那
时候返回 `{'CANCELLED'}` 把这一下按住, 宁可进不去编辑模式, 也不能让改动落在覆盖态数据块
上被 resync 抹掉。

没活干就不插手: 选中的物体没有一个跟着源, `poll` 就不通过, 这一下连本算子都调不起来。

摘下来了不在这里报: Blender 只在 `FINISHED` / `CANCELLED` 那两种返回上收报告, `PASS_THROUGH`
的报告会被当场丢掉 (对照实验: 同样由键位调起、只改返回值的算子, FINISHED 那条进得了信息栏,
PASS_THROUGH 那条进不了)。摘开了几份看面板顶上那条文件级的「N 份数据摘开了」—— 它本来就是
常驻的, 比一闪而过的提示还强。摘不下来那条走 `CANCELLED`, 照常弹得出来。

键位表是活的 —— 改一下偏好, Blender 会把默认键位表整个重建, 而插件键位表不动。Blender
不发"键位表变了"的通知, 所以有个低频计时器盯着: 签名变了才重建复制项, 没变一个字不动。

头部那个模式下拉菜单走的是 RNA 属性不是算子, 拦不到; 面板上「摘下整个角色的共用数据」
就是给那条路兜底的。

这里只摘这一下真会带进编辑模式的那几个 (选中的物体), 不摘整个角色 —— 编辑一条
裙子不该把整副骨架和别的部件都变成待推送。整角色一次摘是面板上那个按钮的事。
"""

import bpy

from . import linkage

EDIT_MODE_ENTRY_OPERATORS = (
    "object.mode_set",
    "object.mode_set_with_submode",
    "object.editmode_toggle",
)

SYNC_INTERVAL_SECONDS = 2.0


def _pending(context):
    """这一下会把哪些跟源的数据块带进编辑模式。

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
    """进编辑模式之前, 先把还跟着源的数据块摘下来, 再把这一下交还给原来的键位。"""

    bl_idname = "shiyume.edit_takeover"
    bl_label = "进编辑模式前摘下共用数据"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        active = context.active_object
        if active is None or active.mode != 'OBJECT':
            return False
        return bool(_pending(context))

    def invoke(self, context, event):
        for datablock in _pending(context):
            try:
                linkage.detach(datablock)
            except Exception as error:      # noqa: BLE001 摘不动要说清楚, 别闷着
                self.report({'ERROR'}, "%s 摘不下来, 这一下不放进编辑模式: %s"
                            % (datablock.name, error))
                return {'CANCELLED'}
        return {'PASS_THROUGH'}


classes = (SHIYUME_OT_EditTakeover,)

_followed_signature = None


def _enters_edit_mode(item):
    """这条键位项按下去会进编辑模式。"""
    if not item.active or item.idname not in EDIT_MODE_ENTRY_OPERATORS:
        return False
    return getattr(item.properties, "mode", 'EDIT') == 'EDIT'


def _edit_mode_entries():
    """用户键位配置里所有进编辑模式的键位项; 本算子自己那几条不在其中 (算子名不同)。"""
    keyconfig = bpy.context.window_manager.keyconfigs.user
    if keyconfig is None:
        return []
    return [(keymap, item)
            for keymap in keyconfig.keymaps
            for item in keymap.keymap_items
            if _enters_edit_mode(item)]


def _signature(entries):
    return tuple(
        (keymap.name, keymap.space_type, keymap.region_type,
         item.map_type, item.type, item.value, item.direction, item.repeat,
         item.any, item.ctrl, item.shift, item.alt, item.oskey, item.key_modifier)
        for keymap, item in entries
    )


def _clear():
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return
    for keymap in keyconfig.keymaps:
        mine = [item for item in keymap.keymap_items
                if item.idname == SHIYUME_OT_EditTakeover.bl_idname]
        for item in mine:
            keymap.keymap_items.remove(item)


def follow_keymap():
    """把复制项对齐到用户当前的键位表; 签名没变就一个字不动。

    先 `update()`: 合并表是惰性重建的, 改完偏好当场读到的还是上一份, 不推一下会慢一拍。
    """
    global _followed_signature
    keyconfigs = bpy.context.window_manager.keyconfigs
    keyconfigs.update()
    if keyconfigs.addon is None:
        return
    entries = _edit_mode_entries()
    signature = _signature(entries)
    if signature == _followed_signature:
        return
    _clear()
    for keymap, item in entries:
        target = keyconfigs.addon.keymaps.new(name=keymap.name,
                                              space_type=keymap.space_type,
                                              region_type=keymap.region_type)
        mirrored = target.keymap_items.new_from_item(item)
        mirrored.idname = SHIYUME_OT_EditTakeover.bl_idname
    _followed_signature = signature


def _keep_following():
    follow_keymap()
    return SYNC_INTERVAL_SECONDS


def register_keymap():
    follow_keymap()
    if not bpy.app.timers.is_registered(_keep_following):
        bpy.app.timers.register(_keep_following, first_interval=0.0, persistent=True)


def unregister_keymap():
    global _followed_signature
    if bpy.app.timers.is_registered(_keep_following):
        bpy.app.timers.unregister(_keep_following)
    _clear()
    _followed_signature = None
