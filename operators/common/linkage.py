"""数据块与唯一源之间的三种状态, 以及它们之间的迁移。

物体永远是本地的 —— 变换、修改器、顶点组、材质槽都是每个文件自己的事。**只有数据块**
(mesh / material) 挂到源文件上, 所以这里从头到尾不碰集合: 集合管的是物体。

一个数据块只有三种状态:

  跟源 (attached)   本地的库覆盖, `override_library.reference` 指着源文件里那一份。
                    几何/拓扑/节点跟着源走, 开文件就是最新的, 不需要拉取。
                    而形态键的**值**是本文件自己的 —— 这是覆盖相对纯链接的全部意义。

  脱开 (detached)   本地的普通数据块, 因为要编辑而被 make_local 摘下来。
                    源路径与源名字记在数据块自己的自定义属性上 —— **必须在摘之前记**,
                    因为最后一个用户消失的那一刻库记录就没了, 事后问不出来。

  无关 (unbound)    本文件自己造的东西, 插件一个字都不动它。

实测钉死的三条 (Blender 5.3.0 Alpha, 本地物体 + 链接 mesh + override_create):

  · 覆盖态进编辑模式必失败: `RuntimeError: ... error changing modes`。接管就挂在这一刻。
  · 覆盖态**直接写顶点不报错**, 当场读得回来, 存盘重开被 resync 抹掉。所以任何几何改动
    都必须先脱开 —— 接管是正确性要求, 不是顺手的方便。
  · make_local 把形态键的值原样带走; 恢复覆盖会让它掉回源里的值, 所以恢复前后要自己接一手。
"""

import os

import bpy

SOURCE_FILE_KEY = "shiyume_source_file"
SOURCE_NAME_KEY = "shiyume_source_name"

KIND_BY_TYPE = (
    (bpy.types.Mesh, 'meshes'),
    (bpy.types.Material, 'materials'),
    (bpy.types.Armature, 'armatures'),
)
KINDS = tuple(name for _rna_type, name in KIND_BY_TYPE)


def collection_of(datablock):
    """这个数据块住在 bpy.data 的哪个集合里; 不是本插件管的类型就返回 None。

    按类型判, 不去 bpy.data 里逐个比对 —— 后者在大场景里是每次调用扫一遍全表。
    骨架和网格走同一套: 骨骼结构是数据块 (跟源), 姿势在物体上 (每文件自己的)。
    """
    for rna_type, name in KIND_BY_TYPE:
        if isinstance(datablock, rna_type):
            return name
    return None


def is_attached(datablock):
    """跟着源走的覆盖态。"""
    return bool(getattr(datablock, "override_library", None))


def is_detached(datablock):
    """为了编辑而摘下来的本地态 —— 身上记着它该回哪儿去。"""
    return (not is_attached(datablock)
            and datablock.library is None
            and SOURCE_FILE_KEY in datablock.keys())


def source_reference(datablock):
    """(源文件绝对路径, 源数据块名) 或 None。三种状态问同一个问题, 答案来源不同。"""
    override = getattr(datablock, "override_library", None)
    if override is not None and override.reference is not None:
        reference = override.reference
        if reference.library is not None:
            return absolute_path(reference.library.filepath), reference.name
    if datablock.library is not None:
        return absolute_path(datablock.library.filepath), datablock.name
    path = datablock.get(SOURCE_FILE_KEY)
    name = datablock.get(SOURCE_NAME_KEY)
    if path and name:
        return absolute_path(path), name
    return None


def absolute_path(path):
    return os.path.abspath(bpy.path.abspath(path))


def shape_values(datablock):
    """形态键的值: 恢复覆盖会把它冲回源里的值, 所以每次迁移前后都要自己接一手。"""
    keys = getattr(datablock, "shape_keys", None)
    return {block.name: block.value for block in keys.key_blocks} if keys else {}


def apply_shape_values(datablock, values):
    keys = getattr(datablock, "shape_keys", None)
    if keys is None:
        return 0
    applied = 0
    for name, value in values.items():
        block = keys.key_blocks.get(name)
        if block is not None and block.value != value:
            block.value = value
            applied += 1
    return applied


def linked_datablock(path, collection_name, source_name):
    """这个源的这个数据块是不是已经链在文件里了; 没有就 None。"""
    wanted = absolute_path(path)
    for datablock in getattr(bpy.data, collection_name):
        if (datablock.library is not None
                and datablock.name == source_name
                and absolute_path(datablock.library.filepath) == wanted):
            return datablock
    return None


def link_datablock(path, collection_name, source_name):
    """从源文件里链接一个数据块进来。返回链接到的那一份。

    已经链过就直接用现成的: 再 load 一次不会出第二份, 只会让 Blender 打一行
    `WARNING ... is already linked`, 外加白开一次文件。绑定整个角色时映射那一步已经把这些
    数据块拖进来了, 所以这条命中是常态而不是例外。
    """
    existing = linked_datablock(path, collection_name, source_name)
    if existing is not None:
        return existing
    with bpy.data.libraries.load(path, link=True) as (source, target):
        available = getattr(source, collection_name)
        if source_name not in available:
            raise KeyError("%s 里没有 %s %r; 现有 %s"
                           % (os.path.basename(path), collection_name, source_name,
                              sorted(available)[:20]))
        setattr(target, collection_name, [source_name])
    return getattr(target, collection_name)[0]


def attach(datablock, path, source_name):
    """把一个本地数据块换成"跟着源走"的覆盖态, 并把它原来的用户全部接过去。

    返回覆盖出来的那一份。形态键的值按调用前的原样接回去 —— 覆盖是从源上重建的, 不接
    就会掉回源里的值。
    """
    collection_name = collection_of(datablock)
    if collection_name is None:
        raise TypeError("%r 不是本插件管的数据块类型" % datablock)

    kept = shape_values(datablock)
    linked = link_datablock(path, collection_name, source_name)
    if linked is datablock:
        raise RuntimeError("链接回来的就是它自己, 说明 %r 本来就是链接态" % datablock)

    datablock.user_remap(linked)
    if datablock.users == 0 and not datablock.use_fake_user:
        getattr(bpy.data, collection_name).remove(datablock)

    override = linked.override_create(remap_local_usages=True)
    if override is None:
        raise RuntimeError("%s / %s 建不出库覆盖" % (os.path.basename(path), source_name))
    apply_shape_values(override, kept)
    return override


def detach(datablock):
    """摘下来准备编辑: 先把源指针刻到数据块上, 再 make_local。

    顺序不能反。最后一个用户从链接数据块上挪走的那一刻, 库记录就被回收了, 事后再问
    `library.filepath` 只会拿到 None —— 实测本地化之后 `len(bpy.data.libraries)` 直接归零。
    """
    reference = source_reference(datablock)
    if reference is None:
        raise RuntimeError("%r 问不出源文件, 不能脱开" % datablock)
    path, source_name = reference

    local = datablock.make_local()
    local[SOURCE_FILE_KEY] = path
    local[SOURCE_NAME_KEY] = source_name
    return local


def reattach(datablock):
    """编辑完、推送完之后回到跟源走的状态。"""
    reference = source_reference(datablock)
    if reference is None:
        raise RuntimeError("%r 问不出源文件, 不能恢复" % datablock)
    path, source_name = reference
    if not os.path.isfile(path):
        raise OSError("源文件不存在: %s" % path)
    return attach(datablock, path, source_name)


def known_sources():
    """这个文件已经在用的源文件路径, 按用的份数从多到少。

    手动指定来源时拿它当默认值: 一个角色的零件几乎总是来自同一个源, 让人再翻一次文件选择器
    是白费事。
    """
    counts = {}
    for groups in (attached_datablocks(), detached_datablocks()):
        for path, rows in groups.items():
            counts[path] = counts.get(path, 0) + len(rows)
    return [path for path, _count in sorted(counts.items(), key=lambda row: -row[1])]


def detached_datablocks():
    """整个文件里所有摘下来待推送的数据块, 按源文件分组。"""
    groups = {}
    for collection_name in KINDS:
        for datablock in getattr(bpy.data, collection_name):
            if not is_detached(datablock):
                continue
            path, source_name = source_reference(datablock)
            groups.setdefault(path, []).append((collection_name, datablock, source_name))
    return groups


def attached_datablocks():
    """整个文件里所有跟着源走的数据块, 按源文件分组。"""
    groups = {}
    for collection_name in KINDS:
        for datablock in getattr(bpy.data, collection_name):
            if not is_attached(datablock):
                continue
            reference = source_reference(datablock)
            if reference is None:
                continue
            groups.setdefault(reference[0], []).append(
                (collection_name, datablock, reference[1]))
    return groups
