"""共用数据的算子: 绑定到唯一源、推送回去、放弃本地改动。

绑定是**逐数据块**的: 网格、材质、骨架各自跟自己的源, 所以任何一份都可以单独解绑。物体
不参与 —— 变换、修改器、顶点组、材质槽本来就该是每个文件自己的。

没有"拉取"。数据块跟着源走, 打开文件就是源的最新状态; 唯一需要动手的时刻是"我要改它",
那一下由 takeover 接管。
"""

import os

import bpy

from . import linkage
from . import push


def source_datablock_names(path):
    """源文件里各类数据块的名录 —— 只读目录, 不加载任何东西。"""
    with bpy.data.libraries.load(path) as (source, _target):
        return {kind: set(getattr(source, kind)) for kind in linkage.KINDS}


def _stem(name):
    """剥掉 Blender 撞名时加的 `.NNN` 后缀; 没有后缀就原样返回。"""
    head, dot, tail = name.rpartition('.')
    return head if head and dot and len(tail) == 3 and tail.isdigit() else name


def _match(name, pool):
    """本地数据块名 -> 源文件里的名字。

    先精确匹配。对不上再按去后缀的词干比一次, 而且**只在源里恰好只有一个同词干的**时候才
    认 —— 有歧义宁可报未命中让人手选, 也不瞎猜: 认错人会把改动推到别的资产上。
    """
    if name in pool:
        return name
    stem = _stem(name)
    candidates = [candidate for candidate in pool if _stem(candidate) == stem]
    return candidates[0] if len(candidates) == 1 else None


def bindable_datablocks(context):
    """选中的物体身上, 还没绑过、可以绑的数据块。"""
    found = []
    for obj in context.selected_objects:
        datablock = obj.data
        if datablock is None or linkage.collection_of(datablock) is None:
            continue
        if datablock.library is not None or linkage.is_attached(datablock):
            continue
        if datablock not in found:
            found.append(datablock)
    return found


class SHIYUME_OT_Bind(bpy.types.Operator):
    """选一个源文件, 把选中物体的数据块挂上去 (按数据块名对号入座)。

    挂上去之后几何/拓扑就跟着源走了, 本地那份被源的版本取代; 形态键的值仍然是本文件自己的。
    """

    bl_idname = "shiyume.common_bind"
    bl_label = "绑定到唯一源"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return bool(bindable_datablocks(context))

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
        try:
            pools = source_datablock_names(target)
        except Exception as error:          # noqa: BLE001
            self.report({'ERROR'}, "读不出 %s: %s" % (os.path.basename(target), error))
            return {'CANCELLED'}

        bound, missed = [], []
        for datablock in bindable_datablocks(context):
            kind = linkage.collection_of(datablock)
            source_name = _match(datablock.name, pools[kind])
            if source_name is None:
                missed.append("%s/%s" % (kind, datablock.name))
                continue
            try:
                linkage.attach(datablock, target, source_name)
            except Exception as error:      # noqa: BLE001 逐个隔离, 一个失败别拖累其它
                missed.append("%s/%s (%s)" % (kind, datablock.name, error))
                continue
            bound.append(source_name)

        if missed:
            self.report({'WARNING'}, "对不上的 %d 个: %s" % (len(missed), ", ".join(missed[:6])))
        if not bound:
            self.report({'ERROR'}, "一个都没绑上")
            return {'CANCELLED'}
        self.report({'INFO'}, "%s: 绑上 %d 个数据块 %s"
                    % (os.path.basename(target), len(bound), ", ".join(bound[:6])))
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
    """把整个文件里摘下来的共用数据推回唯一源, 并把链接接回去。

    源被覆盖之前, 它的上一版先按 RuriAutoSave 的规则移进备份目录 —— 落点与命名走它那一套,
    同盘是一次 rename, 不拷贝。

    源写完之后本文件会**存盘并重新打开一次**: 库的内容变了而 Blender 不会自己去重读, 不重读
    就接不回正确的链接。撤销历史会因此清掉, 但那一步之前已经存过盘, 没有数据会丢。
    """

    bl_idname = "shiyume.common_push"
    bl_label = "推送回唯一源"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(linkage.detached_datablocks())

    def execute(self, context):
        return self._done(push.push_all())


class SHIYUME_OT_ReattachAll(_Reporting, bpy.types.Operator):
    """丢掉本地改动, 把摘下来的数据块直接接回源 (改错了要放弃时用)。"""

    bl_idname = "shiyume.common_reattach_all"
    bl_label = "放弃本地改动并接回源"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(linkage.detached_datablocks())

    def execute(self, context):
        return self._done(push.discard_local())


class SHIYUME_OT_Unbind(bpy.types.Operator):
    """把选中物体的数据块彻底从源上摘下来, 以后不再同步 (数据留在本地, 一点不动)。"""

    bl_idname = "shiyume.common_unbind"
    bl_label = "解除绑定 (数据留在本地)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(linkage.is_attached(obj.data) or linkage.is_detached(obj.data)
                   for obj in context.selected_objects if obj.data is not None)

    def execute(self, context):
        freed = []
        for obj in context.selected_objects:
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
            self.report({'ERROR'}, "选中的东西没有绑着源的数据块")
            return {'CANCELLED'}
        self.report({'INFO'}, "已解除 %d 个数据块的绑定: %s" % (len(freed), ", ".join(freed[:6])))
        return {'FINISHED'}


classes = (
    SHIYUME_OT_Bind,
    SHIYUME_OT_Push,
    SHIYUME_OT_ReattachAll,
    SHIYUME_OT_Unbind,
)
