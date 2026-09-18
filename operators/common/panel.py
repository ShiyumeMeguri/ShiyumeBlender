"""共用数据的面板。

放在 Item 页: 它回答的是"当前这个角色跟着谁、现在有没有摘开的", 和变换/尺寸一样属于物体
属性的即时查看, 用的时候不该再切标签页。

顶上那条"待推送"是**文件级**的 —— 摘开的数据块是这个文件私有的岔路, 不收回去就不叫单一源,
所以它必须在任何一个物体的面板上都看得见, 而不是只在摘开的那个物体上。推送与还原各给两档:
手上选中的那几份, 和整个文件 —— 改完一件推一件和攒一批一起推都行, 没推的照旧摘着。

下面那段是**角色级**的: 选中骨架或它任意一个子网格都一样, 绑定/摘下/解绑一次做完整副骨架
加全部蒙皮网格。
"""

import os

import bpy

from . import character
from . import linkage
from . import material_sync
from . import push

STATE_TEXT = {
    'attached': ("跟着源", 'LINKED'),
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


def tally(objects):
    counts = {}
    for obj in objects:
        state = state_of(obj.data)
        if state is not None:
            counts[state] = counts.get(state, 0) + 1
    return counts


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
        self._draw_pending(context, layout)
        self._draw_character(context, layout)
        self._draw_active(context, layout)

    def _draw_active(self, context, layout):
        """当前这一个物体: 它记着的身份、挂着谁、材质跟不跟。

        这一段是**逐物体**的, 和上面按角色一次做完那一段分开 —— 源改过名、老模型对不上的时候
        要的正是逐个指, 而材质跟不跟源本来就是每个物体自己的事。

        身份单独画一行而不是只画源: 名字可以跟数据块不一样 (两个模型认领同一件身体时必然如此),
        那一行回答的是"下次自动绑定会把它认成谁", 光看名字答不出来。
        """
        obj = context.active_object
        if obj is None or obj.data is None or linkage.collection_of(obj.data) is None:
            return
        layout.separator()
        box = layout.box()
        state = state_of(obj.data)
        text, icon = STATE_TEXT[state]
        box.label(text="%s: %s" % (obj.name, text), icon=icon)
        reference = linkage.source_reference(obj.data)
        if reference is not None:
            box.label(text="→ %s / %s" % (os.path.basename(reference[0]), reference[1]),
                      icon='FILE_BLEND')
        binding = character.binding_of(obj)
        if binding is None:
            box.label(text="没记身份, 自动绑定时按名字猜", icon='QUESTION')
        else:
            box.label(text="身份: %s / %s" % (os.path.basename(binding[0]), binding[1]),
                      icon='FUND')
        box.operator("shiyume.common_bind_pick", icon='EYEDROPPER')
        if obj.type == 'MESH':
            row = box.row()
            row.prop(obj, material_sync.SYNC_PROPERTY)
            if not material_sync.is_syncing(obj):
                box.label(text="材质挂在物体上, 换源不跟着变", icon='INFO')

    def _draw_pending(self, context, layout):
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
            for _kind, _datablock, source_name in rows[:6]:
                box.label(text="    %s" % source_name, icon='DOT')
            if len(rows) > 6:
                box.label(text="    ...还有 %d 份" % (len(rows) - 6))
            if not os.path.isfile(path):
                box.label(text="    源文件不存在!", icon='ERROR')
        for row in push.conflicts(groups):
            box.label(text=row, icon='ERROR')

        selected = push.detached_of(context.selected_objects)
        if selected:
            column = layout.column(align=True)
            column.label(text="选中的 %d 份" % len(selected), icon='RESTRICT_SELECT_OFF')
            column.operator("shiyume.common_push", text="推送选中的",
                            icon='EXPORT').scope = 'SELECTED'
            column.operator("shiyume.common_discard", text="还原选中的",
                            icon='LOOP_BACK').scope = 'SELECTED'

        column = layout.column(align=True)
        column.label(text="整个文件 %d 份" % count, icon='FILE_BLEND')
        column.operator("shiyume.common_push", text="推送全部",
                        icon='EXPORT').scope = 'FILE'
        column.operator("shiyume.common_discard", text="还原全部",
                        icon='LOOP_BACK').scope = 'FILE'

    def _draw_character(self, context, layout):
        layout.separator()
        rig, meshes = character.active_character(context)
        if rig is None:
            layout.label(text="%s 推不出角色 (没蒙皮到骨架)" % context.active_object.name,
                         icon='INFO')
            layout.label(text="按选中的这些单独操作", icon='BLANK1')
        else:
            box = layout.box()
            box.label(text="角色 %s" % rig.name, icon='OUTLINER_OB_ARMATURE')
            box.label(text="骨架 1 + 子网格 %d" % len(meshes), icon='MESH_DATA')
            counts = tally([rig] + meshes)
            for state in ('attached', 'detached', 'linked', 'free'):
                if state in counts:
                    text, icon = STATE_TEXT[state]
                    box.label(text="%s: %d" % (text, counts[state]), icon=icon)
            self._draw_sources(box, [rig] + meshes)

        column = layout.column(align=True)
        column.operator("shiyume.pose_sync", icon='CON_TRANSFORM')
        column.operator("shiyume.char_bind", icon='LINKED')
        column.operator("shiyume.char_detach", icon='UNLINKED')
        column.operator("shiyume.char_unbind", icon='X')

    def _draw_sources(self, layout, objects):
        paths = set()
        for obj in objects:
            if obj.data is None or linkage.collection_of(obj.data) is None:
                continue
            reference = linkage.source_reference(obj.data)
            if reference is not None:
                paths.add(reference[0])
        for path in sorted(paths):
            layout.label(text="→ %s" % os.path.basename(path), icon='FILE_BLEND')
            if not os.path.isfile(path):
                layout.label(text="   源文件不存在!", icon='ERROR')
        if len(paths) > 1:
            layout.label(text="这个角色的数据块绑到了不同的源文件", icon='INFO')


classes = (SHIYUME_PT_CommonDatablocks,)
