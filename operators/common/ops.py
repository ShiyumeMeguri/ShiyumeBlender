"""共用数据的算子。

操作的单位是**角色**: 选中骨架或它任意一个子网格, 绑定/摘下/解绑都对整副骨架加全部蒙皮
网格一次做完。推送是**整个文件**一次 —— "始终只有一个源"要成立, 文件里就不能留着一份摘开
的数据块不管它。

绑定按物体名对号入座, 对不上的跳过 (场景里本来就有主模型没有的东西)。落到数据块上的是
物体的 `data`: 网格、材质、骨架各自跟自己的源, 物体本身永远是本地的。

没有"拉取"。数据块跟着源走, 打开文件就是源的最新状态; 唯一需要动手的时刻是"我要改它",
那一下由 takeover 接管。
"""

import os

import bpy

from . import character
from . import linkage
from . import push


def _stem(name):
    """剥掉 Blender 撞名时加的 `.NNN` 后缀; 没有后缀就原样返回。"""
    head, dot, tail = name.rpartition('.')
    return head if head and dot and len(tail) == 3 and tail.isdigit() else name


def _match(name, available):
    """本地物体名 -> 源里那个物体的名字; 对不上返回 None。

    先精确匹配。对不上再按去后缀的词干比一次, 而且**只在源里恰好只有一个同词干的**时候才认 ——
    有歧义宁可算未命中, 也不瞎猜: 认错人会把改动推到别的资产上。
    """
    if name in available:
        return name
    stem = _stem(name)
    candidates = [candidate for candidate in available if _stem(candidate) == stem]
    return candidates[0] if len(candidates) == 1 else None


def bindable(objects):
    """这些物体里, 数据块还没绑过、可以绑的那些。"""
    found = []
    for obj in objects:
        datablock = obj.data
        if datablock is None or linkage.collection_of(datablock) is None:
            continue
        if datablock.library is not None or linkage.is_attached(datablock):
            continue
        found.append(obj)
    return found


def detachable(objects):
    """这些物体里, 数据块正跟着源、可以摘下来的那些。"""
    seen = []
    for obj in objects:
        datablock = obj.data
        if datablock is not None and linkage.is_attached(datablock) and datablock not in seen:
            seen.append(datablock)
    return seen


class SHIYUME_OT_CharBind(bpy.types.Operator):
    """选一个源文件, 把整个角色 (骨架 + 全部蒙皮网格) 的数据块一次挂上去。

    按**物体名**对号入座; 源里没有的物体直接跳过, 不算错误。挂上去之后几何/拓扑就跟着源走了,
    本地那份被源的版本取代; 形态键的值仍然是本文件自己的。
    """

    bl_idname = "shiyume.char_bind"
    bl_label = "整个角色绑定到唯一源"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return bool(bindable(character.members(context)))

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        target = os.path.abspath(bpy.path.abspath(self.filepath))
        if not os.path.isfile(target):
            self.report({'ERROR'}, "源文件不存在: %s" % target)
            return {'CANCELLED'}
        if bpy.data.filepath and os.path.samefile(target, bpy.data.filepath):
            self.report({'ERROR'}, "源不能是当前文件本身")
            return {'CANCELLED'}
        candidates = bindable(character.members(context))
        try:
            available = character.source_object_names(target)
            pairs = [(obj, _match(obj.name, available)) for obj in candidates]
            mapping = character.source_object_data_map(
                target, [name for _obj, name in pairs if name is not None])
        except Exception as error:          # noqa: BLE001
            self.report({'ERROR'}, "读不出 %s: %s" % (os.path.basename(target), error))
            return {'CANCELLED'}

        bound, skipped, failed = [], [], []
        for obj, source_object in pairs:
            source_name = mapping.get(source_object) if source_object else None
            if source_name is None:
                skipped.append(obj.name)
                continue
            try:
                linkage.attach(obj.data, target, source_name)
            except Exception as error:      # noqa: BLE001 逐个隔离, 一个失败别拖累其它
                failed.append("%s (%s)" % (obj.name, error))
                continue
            bound.append(obj.name)

        for row in failed:
            self.report({'WARNING'}, "绑不上: %s" % row)
        if skipped:
            self.report({'INFO'}, "源里没有, 已跳过 %d 个: %s"
                        % (len(skipped), ", ".join(skipped[:6])))
        if not bound:
            self.report({'ERROR'}, "一个都没绑上")
            return {'CANCELLED'}
        self.report({'INFO'}, "%s: 绑上 %d 个 (跳过 %d)"
                    % (os.path.basename(target), len(bound), len(skipped)))
        return {'FINISHED'}


class SHIYUME_OT_CharDetach(bpy.types.Operator):
    """把整个角色的共用数据一次摘下来准备编辑。

    按 Tab 进编辑模式时会自动摘, 这个按钮是给别的路子用的 —— 头部那个模式下拉菜单走的是
    RNA 属性不是算子, 拦不到。
    """

    bl_idname = "shiyume.char_detach"
    bl_label = "摘下整个角色的共用数据"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(detachable(character.members(context)))

    def execute(self, context):
        names = []
        for datablock in detachable(character.members(context)):
            name = datablock.name
            try:
                linkage.detach(datablock)
            except Exception as error:      # noqa: BLE001
                self.report({'ERROR'}, "%s 摘不下来: %s" % (name, error))
                return {'CANCELLED'}
            names.append(name)
        self.report({'INFO'}, "已摘下 %d 份: %s" % (len(names), ", ".join(names[:6])))
        return {'FINISHED'}


class SHIYUME_OT_CharUnbind(bpy.types.Operator):
    """整个角色彻底不再跟源同步 (数据留在本地, 一点不动)。"""

    bl_idname = "shiyume.char_unbind"
    bl_label = "解除整个角色的绑定"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(linkage.is_attached(obj.data) or linkage.is_detached(obj.data)
                   for obj in character.members(context) if obj.data is not None)

    def execute(self, context):
        freed = []
        for obj in character.members(context):
            datablock = obj.data
            if datablock is None:
                continue
            if linkage.is_attached(datablock):
                datablock = linkage.detach(datablock)
            elif not linkage.is_detached(datablock):
                continue
            for key in (linkage.SOURCE_FILE_KEY, linkage.SOURCE_NAME_KEY):
                if key in datablock.keys():
                    del datablock[key]
            freed.append(datablock.name)
        if not freed:
            self.report({'ERROR'}, "这个角色没有绑着源的数据块")
            return {'CANCELLED'}
        self.report({'INFO'}, "已解除 %d 个数据块的绑定: %s" % (len(freed), ", ".join(freed[:6])))
        return {'FINISHED'}


class _Reporting:
    def _done(self, result):
        if not result.get('ok'):
            self.report({'ERROR'}, result.get('error', '未知错误'))
            return {'CANCELLED'}
        for note in result.get('notes', ())[:12]:
            self.report({'WARNING'}, note)
        self.report({'INFO'}, result.get('summary', '完成'))
        return {'FINISHED'}


class SHIYUME_OT_Push(_Reporting, bpy.types.Operator):
    """把这个文件里摘下来的共用数据**全部**推回各自的源, 并接回链接。

    一次推整个文件, 不用挨个选网格: 骨架、全部子网格、材质, 谁摘开了就推谁。

    源被覆盖之前, 它的上一版先按 RuriAutoSave 的规则移进备份目录 —— 落点与命名走它那一套,
    同盘是一次 rename, 不拷贝。

    源写完之后本文件会**存盘并重新打开一次**: 库的内容变了而 Blender 不会自己去重读, 不重读
    就接不回正确的链接。撤销历史会因此清掉, 但那一步之前已经存过盘, 没有数据会丢。
    """

    bl_idname = "shiyume.common_push"
    bl_label = "一键推送全部改动"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(linkage.detached_datablocks())

    def execute(self, context):
        return self._done(push.push_all())


class SHIYUME_OT_DiscardLocal(_Reporting, bpy.types.Operator):
    """丢掉本地改动, 把摘下来的数据块直接接回源 (改错了要放弃时用)。"""

    bl_idname = "shiyume.common_discard"
    bl_label = "放弃本地改动并接回源"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(linkage.detached_datablocks())

    def execute(self, context):
        return self._done(push.discard_local())


classes = (
    SHIYUME_OT_CharBind,
    SHIYUME_OT_CharDetach,
    SHIYUME_OT_CharUnbind,
    SHIYUME_OT_Push,
    SHIYUME_OT_DiscardLocal,
)
