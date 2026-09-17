"""共用数据的面板。

放在 Item 页: 它回答的是"当前选中这东西的数据跟着谁、现在是不是摘开的", 和变换/尺寸一样
属于物体属性的即时查看, 用的时候不该再切标签页。

面板顶上那条"待推送"是文件级的 —— 摘开的数据块是这个文件私有的岔路, 不收回去就不叫单一源,
所以它必须在任何一个物体的面板上都看得见, 而不是只在摘开的那个物体上。
"""

import os

import bpy

from . import linkage

STATE_TEXT = {
    'attached': ("跟着源 (可直接用, 要改按 Tab)", 'LINKED'),
    'detached': ("已摘下, 待推送", 'UNLINKED'),
    'linked': ("纯链接, 只读", 'LIBRARY_DATA_DIRECT'),
    'free': ("本文件自己的", 'BLANK1'),
}


def state_of(datablock):
    if datablock is None or linkage.collection_of(datablock) is None:
        return None
    if linkage.is_attached(datablock):
        return 'attached'
    if linkage.is_detached(datablock):
        return 'detached'
    if datablock.library is not None:
        return 'linked'
    return 'free'


class SHIYUME_PT_CommonDatablocks(bpy.types.Panel):
    bl_label = "共用数据 (链接到唯一源)"
    bl_idname = "SHIYUME_PT_CommonDatablocks"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def draw(self, context):
        layout = self.layout
        self._draw_pending(layout)
        self._draw_active(context, layout)

    def _draw_pending(self, layout):
        groups = linkage.detached_datablocks()
        if not groups:
            layout.label(text="没有摘开的数据, 全部跟着源", icon='CHECKMARK')
            return
        count = sum(len(rows) for rows in groups.values())
        box = layout.box()
        box.alert = True
        box.label(text="%d 份数据摘开了, 还没推回源" % count, icon='UNLINKED')
        for path, rows in sorted(groups.items()):
            box.label(text="→ %s" % os.path.basename(path), icon='FILE_BLEND')
            for _kind, datablock, source_name in rows[:6]:
                box.label(text="    %s" % source_name, icon='DOT')
            if len(rows) > 6:
                box.label(text="    ...还有 %d 份" % (len(rows) - 6))
            if not os.path.isfile(path):
                box.label(text="    源文件不存在!", icon='ERROR')
        column = layout.column(align=True)
        column.operator("shiyume.common_push", icon='EXPORT')
        column.operator("shiyume.common_reattach_all", icon='LOOP_BACK')

    def _draw_active(self, context, layout):
        layout.separator()
        obj = context.active_object
        datablock = obj.data
        state = state_of(datablock)
        head = layout.row()
        head.label(text=obj.name, icon='OBJECT_DATA')
        if state is None:
            layout.label(text="这个物体的数据不归共用数据管", icon='INFO')
            return

        text, icon = STATE_TEXT[state]
        box = layout.box()
        box.label(text="%s: %s" % (datablock.name, text), icon=icon)
        reference = linkage.source_reference(datablock)
        if reference is not None:
            path, source_name = reference
            box.label(text="→ %s / %s" % (os.path.basename(path), source_name),
                      icon='FILE_BLEND')
            if not os.path.isfile(path):
                box.label(text="源文件不存在!", icon='ERROR')

        if state == 'attached':
            layout.operator("shiyume.detach_active", icon='UNLINKED')
        if state == 'free':
            layout.operator("shiyume.common_bind", icon='LINKED')
        if state in ('attached', 'detached'):
            layout.operator("shiyume.common_unbind", icon='X')


classes = (SHIYUME_PT_CommonDatablocks,)
