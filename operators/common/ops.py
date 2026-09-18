"""共用数据的算子。

操作的单位是**角色**: 选中骨架或它任意一个子网格, 绑定/摘下/解绑都对整副骨架加全部蒙皮
网格一次做完。推送是**整个文件**一次 —— "始终只有一个源"要成立, 文件里就不能留着一份摘开
的数据块不管它。

绑过一次的物体身上记着身份 (源文件 + 源数据块名), 之后一律照身份认; 还没身份的按物体名猜
一次, 对不上的跳过 (场景里本来就有主模型没有的东西)。落到数据块上的是物体的 `data`: 网格、
材质、骨架各自跟自己的源, 物体本身永远是本地的。

没有"拉取"。数据块跟着源走, 打开文件就是源的最新状态; 唯一需要动手的时刻是"我要改它",
那一下由 takeover 接管。
"""

import os

import bpy

from . import character
from . import linkage
from . import material_sync
from . import push


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


def bind_one(obj, path, source_name):
    """把一个物体的数据块挂到源里的某个数据块上, 并把身份、名字、材质归属一并落定。

    自动对号入座和手动指定走同一条路 —— 身份、名字对齐、材质开关的兑现只有这一份实现, 两边
    不可能各飘。

    身份先记, 名字后对: 名字**对不上也没关系**, 记下来的那一对字符串才是下一次认人的依据。
    """
    kept = material_sync.snapshot(obj)
    linkage.attach(obj.data, path, source_name)
    character.remember_binding(obj, path, source_name)
    character.align_name(obj, obj.data)
    material_sync.apply_to(obj)
    material_sync.restore(obj, kept)


_PICK_ITEMS = {}


def _pick_items(self, _context):
    """源文件里同类数据块的名录。

    枚举回调返回的列表**必须自己留引用**, 否则 Blender 会拿到已经被回收的字符串, 当场崩。
    这里也只读目录不加载任何东西: 回调是在画界面的时候跑的, 在那里动 bpy.data 是找死。
    """
    path = os.path.abspath(bpy.path.abspath(self.filepath)) if self.filepath else ""
    key = (path, self.kind)
    if key not in _PICK_ITEMS:
        names = []
        if path and self.kind:
            try:
                with bpy.data.libraries.load(path) as (source, _target):
                    names = sorted(getattr(source, self.kind))
            except Exception:               # noqa: BLE001 读不出就给空列表, 别让界面炸
                names = []
        _PICK_ITEMS[key] = ([(name, name, "") for name in names]
                            or [("", "（这个文件里没有同类数据块）", "")])
    return _PICK_ITEMS[key]


class SHIYUME_OT_BindPick(bpy.types.Operator):
    """手动指定这个物体该挂源里的哪一个数据块。

    没身份的物体按名字猜, 源改过名、老模型跟不上的时候就猜不中 —— 这时不该去改老模型迁就
    匹配规则, 直接指就是了。指完身份就记在这个物体身上, 以后无论谁改名都照身份认。
    """

    bl_idname = "shiyume.common_bind_pick"
    bl_label = "手动指定来源数据块"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(name="源文件", subtype='FILE_PATH')
    kind: bpy.props.StringProperty(options={'HIDDEN'})
    source_name: bpy.props.EnumProperty(name="来源数据块", items=_pick_items)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.data is not None
                and linkage.collection_of(obj.data) is not None)

    def invoke(self, context, event):
        _PICK_ITEMS.clear()                 # 换过文件就得重新读目录
        obj = context.active_object
        self.kind = linkage.collection_of(obj.data)
        if not self.filepath:
            reference = linkage.source_reference(obj.data)
            sources = [reference[0]] if reference else linkage.known_sources()
            if sources:
                self.filepath = sources[0]
        if not self.filepath:
            self.report({'ERROR'}, "这个文件还没有任何源; 先用「整个角色绑定到唯一源」选一次")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = self.layout
        layout.label(text=os.path.basename(self.filepath), icon='FILE_BLEND')
        layout.prop(self, "source_name")
        layout.label(text="指完身份就记在这个物体上, 之后改名也不会丢", icon='INFO')

    def execute(self, context):
        if not self.source_name:
            self.report({'ERROR'}, "没有可指定的数据块")
            return {'CANCELLED'}
        obj = context.active_object
        target = os.path.abspath(bpy.path.abspath(self.filepath))
        try:
            bind_one(obj, target, self.source_name)
        except Exception as error:          # noqa: BLE001
            self.report({'ERROR'}, "指不上去: %s" % error)
            return {'CANCELLED'}
        self.report({'INFO'}, "%s -> %s / %s"
                    % (obj.name, os.path.basename(target), self.source_name))
        return {'FINISHED'}


class SHIYUME_OT_CharBind(bpy.types.Operator):
    """选一个源文件, 把整个角色 (骨架 + 全部蒙皮网格) 的数据块一次挂上去。

    绑过的照物体身上记着的身份走, 没绑过的按**物体名**猜一次; 源里没有的物体直接跳过, 不算
    错误。挂上去之后几何/拓扑就跟着源走了, 本地那份被源的版本取代; 形态键的值仍然是本文件
    自己的 —— 同一个文件里两个模型认领同一件身体也照样各是各的值。
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
            pairs = character.plan(candidates, target)
        except Exception as error:          # noqa: BLE001
            self.report({'ERROR'}, "读不出 %s: %s" % (os.path.basename(target), error))
            return {'CANCELLED'}

        bound, skipped, failed = [], [], []
        for obj, source_name in pairs:
            if source_name is None:
                skipped.append(obj.name)
                continue
            try:
                bind_one(obj, target, source_name)
            except Exception as error:      # noqa: BLE001 逐个隔离, 一个失败别拖累其它
                failed.append("%s (%s)" % (obj.name, error))
                continue
            bound.append(obj.name)

        for row in failed:
            self.report({'WARNING'}, "绑不上: %s" % row)
        if skipped:
            self.report({'WARNING'}, "对不上名字的 %d 个, 用「手动指定来源」逐个指: %s"
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
            character.forget_binding(obj)
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


SCOPE_ITEMS = (
    ('SELECTED', "选中的", "只动选中物体身上的那几份"),
    ('FILE', "整个文件", "这个文件里所有摘开的都算上"),
)


class _Scoped(_Reporting):
    """范围是一个属性而不是两个算子: 推送/还原各自只有一套逻辑, 面板上画两次就够了。

    poll 只问"文件里有没有摘开的" —— 它是类方法, 拿不到实例上那个 scope, 想按范围判就只能
    把属性读成别人那一次点击留下的值。范围对不上由 execute 说人话, 不在按钮灰不灰上耍心机。
    """

    scope: bpy.props.EnumProperty(name="范围", items=SCOPE_ITEMS, default='SELECTED')

    @classmethod
    def poll(cls, context):
        return bool(linkage.detached_datablocks())

    def _targets(self, context):
        if self.scope == 'FILE':
            return push.all_detached()
        return push.detached_of(context.selected_objects)


class SHIYUME_OT_Push(_Scoped, bpy.types.Operator):
    """把摘下来的共用数据推回唯一源, 并接回链接。

    范围选「选中的」就只推手上这几个网格, 选「整个文件」就一口气全推 —— 改完一件推一件,
    还是攒一批一起推, 都行。

    源被覆盖之前, 它的上一版先按 RuriAutoSave 的规则移进备份目录 —— 落点与命名走它那一套,
    同盘是一次 rename, 不拷贝。

    源写完之后本文件会**存盘并重新打开一次**: 库的内容变了而 Blender 不会自己去重读, 不重读
    就接不回正确的链接。撤销历史会因此清掉, 但那一步之前已经存过盘, 没有数据会丢。没推的那些
    照旧摘着, 不受影响。
    """

    bl_idname = "shiyume.common_push"
    bl_label = "推送回唯一源"
    bl_options = {'REGISTER'}

    def execute(self, context):
        return self._done(push.push(self._targets(context)))


class SHIYUME_OT_Discard(_Scoped, bpy.types.Operator):
    """丢掉本地改动, 把摘下来的数据块直接接回源 (改错了要放弃时用)。

    范围同推送: 可以只还原手上这一个网格, 不牵连别的。
    """

    bl_idname = "shiyume.common_discard"
    bl_label = "放弃本地改动并接回源"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return self._done(push.discard(self._targets(context)))


classes = (
    SHIYUME_OT_BindPick,
    SHIYUME_OT_CharBind,
    SHIYUME_OT_CharDetach,
    SHIYUME_OT_CharUnbind,
    SHIYUME_OT_Push,
    SHIYUME_OT_Discard,
)
