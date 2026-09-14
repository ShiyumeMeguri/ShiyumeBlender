"""共用角色数据的面板。

放在 Item 页: 它回答的是"当前选中的这个东西绑到哪儿、推一下拉一下", 和变换/尺寸
一样属于物体属性的即时查看, 用的时候不该再切标签页。
"""

import os

import bpy

from . import binding
from . import warn
from .ops import active_character


class SHIYUME_PT_CommonCharacter(bpy.types.Panel):
    bl_label = "共用角色数据 (按需同步)"
    bl_idname = "SHIYUME_PT_CommonCharacter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in binding.KINDS

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        rig, meshes = active_character(context)

        found = warn.scan()
        if found:
            alert = layout.box()
            alert.alert = True
            alert.label(text="共用数据过时, 别在这份上改了再推", icon='ERROR')
            for line in warn.summarize(found):
                alert.label(text=line)
            alert.label(text="先拉取, 再改", icon='IMPORT')

        if rig is None:
            layout.label(text="%s 没蒙皮到任何骨架" % obj.name, icon='INFO')
            layout.label(text="单个物体也能绑, 用下面的按钮", icon='BLANK1')
        else:
            members = [rig] + meshes
            bound = [o for o in members if binding.get(o) is not None]
            files = {binding.get(o)[0] for o in bound}
            box = layout.box()
            box.label(text="角色 %s" % rig.name, icon='OUTLINER_OB_ARMATURE')
            box.label(text="骨架 1 + 子网格 %d, 已绑 %d/%d"
                      % (len(meshes), len(bound), len(members)), icon='MESH_DATA')
            for path in sorted(files):
                box.label(text="→ %s" % os.path.basename(path), icon='FILE_BLEND')
                if not os.path.isfile(path):
                    box.label(text="   来源文件不存在！", icon='ERROR')
            if len(files) > 1:
                box.label(text="子网格绑到了不同的文件", icon='INFO')

            col = layout.column(align=True)
            col.enabled = bool(bound) and all(os.path.isfile(p) for p in files)
            col.operator("shiyume.char_pull", icon='IMPORT')
            col.operator("shiyume.char_pull_meshes", icon='MESH_DATA')
            col.operator("shiyume.char_push", icon='EXPORT')
            layout.operator("shiyume.char_bind", icon='FILE_BLEND')
            if bound:
                layout.operator("shiyume.char_unbind", icon='X')

        layout.separator()
        head = layout.row()
        head.label(text="单个: %s" % obj.name,
                   icon='OUTLINER_OB_MESH' if obj.type == 'MESH' else 'OUTLINER_OB_ARMATURE')

        bound = binding.get(obj)
        if bound is None:
            layout.label(text="未绑定共用来源", icon='UNLINKED')
        else:
            path, source_name = bound
            info = layout.box()
            info.label(text="→ %s" % os.path.basename(path), icon='FILE_BLEND')
            info.label(text="   来源物体: %s" % source_name, icon='OBJECT_DATA')
            if not os.path.isfile(path):
                info.label(text="来源文件不存在！", icon='ERROR')
            row = layout.row(align=True)
            row.enabled = os.path.isfile(path)
            row.operator("shiyume.common_pull", icon='IMPORT')
            row.operator("shiyume.common_push", icon='EXPORT')
            row = layout.row(align=True)
            pick = row.operator("shiyume.common_bind_pick", text="换来源物体",
                                icon='OBJECT_DATA')
            pick.filepath = path
            pick.kind = obj.type
            row.operator("shiyume.common_unbind", text="单独解除", icon='X')

        if bpy.data.libraries:
            layout.separator()
            libbox = layout.box()      # 别叫 warn: 会把模块级的 warn 遮成局部变量
            libbox.label(text="文件里还有 %d 个库链接" % len(bpy.data.libraries),
                         icon='LIBRARY_DATA_DIRECT')
            libbox.operator("shiyume.common_make_local", icon='UNLINKED')
        layout.label(text="数据始终是本地的，随时可编辑", icon='CHECKMARK')


classes = (SHIYUME_PT_CommonCharacter,)
