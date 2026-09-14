"""过时警告: 打开文件就告诉你"你手上这份比主模型旧"。

为什么必须弹窗而不是只在面板上写一行: 覆盖是不可逆的。人在别的文件里改完主模型,
回到这个场景一按"推送", 就把别人的改动盖掉了 —— 而且盖掉之前没有任何提示。
所以判据要在**打开文件的那一刻**就摆到脸上。

判据是"共用文件的修改时间 vs 本物体上次同步时盖的戳", 不是比两个 .blend 的文件时间:
本文件因为别的原因存过盘会刷新文件时间, 那个判据会把真正的过时掩盖掉。
"""

import os

import bpy
from bpy.app.handlers import persistent

from . import binding

STATE_TEXT = {
    'stale': "比主模型旧",
    'unknown': "没有同步记录",
    'missing': "主模型文件找不到",
}


def scan():
    """{状态: [物体]} —— 面板和弹窗共用这一份判据。"""
    return binding.stale_objects()


def summarize(found):
    """把扫描结果说成人话, 每行一条。"""
    lines = []
    for state in ('stale', 'missing', 'unknown'):
        objects = found.get(state)
        if not objects:
            continue
        files = sorted({os.path.basename(binding.get(o)[0]) for o in objects})
        lines.append("%s: %d 个物体 (%s)"
                     % (STATE_TEXT[state], len(objects), ", ".join(files[:3])))
    return lines


class SHIYUME_OT_CommonStaleReport(bpy.types.Operator):
    """打开文件时弹出来的过时警告。"""
    bl_idname = "shiyume.common_stale_report"
    bl_label = "共用数据过时警告"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        found = scan()
        layout.label(text="这个文件里有共用数据比主模型旧", icon='ERROR')
        layout.separator()
        for state in ('stale', 'missing', 'unknown'):
            objects = found.get(state)
            if not objects:
                continue
            box = layout.box()
            box.label(text=STATE_TEXT[state], icon='ERROR' if state != 'unknown' else 'QUESTION')
            for obj in objects[:12]:
                path, source_name = binding.get(obj)
                box.label(text="   %s  →  %s / %s"
                          % (obj.name, os.path.basename(path), source_name))
            if len(objects) > 12:
                box.label(text="   ...还有 %d 个" % (len(objects) - 12))
        layout.separator()
        layout.label(text="在这份上继续改并推送, 会把主模型里更新的内容覆盖掉。",
                     icon='INFO')
        layout.label(text="先按 Item 面板里的「一键拉取整个角色」把新的拿下来。",
                     icon='IMPORT')

    def execute(self, context):
        return {'FINISHED'}


def _popup():
    """定时器里跑: load_post 当时还没有可用的窗口上下文, 弹不出对话框。"""
    if not bpy.context.window_manager.windows:
        return 0.5
    found = scan()
    if found:
        bpy.ops.shiyume.common_stale_report('INVOKE_DEFAULT')
    return None


@persistent
def on_load(_dummy):
    found = scan()
    if not found:
        return
    for line in summarize(found):
        print("[Shiyume 共用数据] %s" % line)
    if bpy.app.background:
        return
    bpy.app.timers.register(_popup, first_interval=0.8)


classes = (SHIYUME_OT_CommonStaleReport,)


def register_handlers():
    if on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load)


def unregister_handlers():
    if on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load)
