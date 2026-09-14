"""共用数据的指针: 一个本地物体记住"我的数据来自哪个文件的哪个物体"。

为什么不用 Blender 的库链接 (实测结论, 别再走回头路):
  形态键的**值**存在 Key 数据块上, Key 属于 mesh。mesh 一旦链接, Key 跟着是链接的,
  本地怎么改都不写盘 —— 重开就掉回库里的值。而角色体型正是靠这些值区分的。
  三条路都试过: 链接 mesh 数据 / 链接物体+库覆盖 / 对 Key 单独 override_create,
  前两条丢值, 第三条 Blender 直接返回 None。所以"共享几何"和"每个文件自己的体型值"
  在链接模型下不可兼得。

这里的做法: **不链接**。物体上记一个指针, 数据永远是本地的、随时可编辑; 要同步时
按按钮, 拉取就地做, 推送起一个后台 Blender 写回去。

指针记的是**源文件里的物体名**, 不是数据块名。实测: 把角色 append 进场景之后,
数据块必然被加 `.001/.002/.003` 后缀, 按数据块名回去找源文件, 17 个里只能命中 1 个;
按物体名命中 15 个。物体名是稳定的那一头。
"""

import os

import bpy

FILE_KEY = "shiyume_common_file"
NAME_KEY = "shiyume_common_object"
STAMP_KEY = "shiyume_common_stamp"      # 上次同步时, 共用文件的修改时间

KINDS = ('MESH', 'ARMATURE')


def get(obj):
    """物体上记的指针 -> (绝对路径, 源物体名) 或 None。"""
    if obj is None or obj.type not in KINDS:
        return None
    path = obj.get(FILE_KEY)
    name = obj.get(NAME_KEY)
    if not path or not name:
        return None
    return os.path.abspath(bpy.path.abspath(path)), name


def put(obj, path, source_name, relative=True):
    """记下指针, 并盖上"此刻与共用文件同步过"的时间戳。返回实际存进去的路径字符串。"""
    stored = path
    if relative and bpy.data.filepath:
        try:
            stored = bpy.path.relpath(path)
        except ValueError:
            stored = path                      # 跨盘符时 relpath 会失败, 退回绝对路径
    obj[FILE_KEY] = stored
    obj[NAME_KEY] = source_name
    stamp(obj, path)
    return stored


def stamp(obj, path=None):
    """盖上时间戳: 记下共用文件此刻的修改时间。同步成功之后必须调。"""
    if path is None:
        bound = get(obj)
        if bound is None:
            return None
        path = bound[0]
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    obj[STAMP_KEY] = mtime
    return mtime


def staleness(obj):
    """这份本地数据相对共用文件是不是过时了。

    返回 None(没绑) / ('ok', ...) / ('stale', ...) / ('unknown', ...) / ('missing', ...)

    判据是"共用文件的修改时间 vs 上次同步时盖的戳", 不是两个 .blend 的文件时间 ——
    本文件因为别的原因存过盘会把文件时间刷新, 那个判据会把真正的过时掩盖掉。
    """
    bound = get(obj)
    if bound is None:
        return None
    path, _name = bound
    try:
        source_mtime = os.path.getmtime(path)
    except OSError:
        return ('missing', path, None, None)
    marked = obj.get(STAMP_KEY)
    if marked is None:
        return ('unknown', path, source_mtime, None)
    if source_mtime > float(marked) + 1.0:      # 1 秒容差, 躲开文件系统的时间精度
        return ('stale', path, source_mtime, float(marked))
    return ('ok', path, source_mtime, float(marked))


def stale_objects(objects=None):
    """扫一遍, 返回 {状态: [物体]}, 只收 stale / unknown / missing。"""
    out = {}
    for obj in (objects if objects is not None else bpy.data.objects):
        state = staleness(obj)
        if state is None or state[0] == 'ok':
            continue
        out.setdefault(state[0], []).append(obj)
    return out


def clear(obj):
    """解除绑定, 只删指针, 不动数据。返回是否真的删掉了东西。"""
    hit = False
    for key in (FILE_KEY, NAME_KEY, STAMP_KEY):
        if key in obj:
            del obj[key]
            hit = True
    return hit


def bound_file_of(obj):
    """只看文件指针 (数据块名可能还没定), 给面板判"这物体属于哪个角色"用。"""
    path = obj.get(FILE_KEY) if obj is not None else None
    return os.path.abspath(bpy.path.abspath(path)) if path else None


def source_names(path):
    """源文件里有哪些物体 / 网格 / 骨架数据块 —— 只读目录, 不加载任何东西。"""
    with bpy.data.libraries.load(path) as (src, _dst):
        return sorted(src.objects), set(src.meshes), set(src.armatures)


def borrow_many(path, object_names):
    """把源文件里的若干物体临时 append 进来, 用完即弃。

    返回 (按请求顺序的物体列表, 收尾函数)。收尾函数会连它们带进来的东西一起清掉 ——
    调用方想留下其中某个数据块 (比如网格), 先把它挂到本地物体上, 引用数不为零就会被跳过。

    两个必须踩对的点:
      · 用 `dst.objects` 的有序返回, 不要去 diff bpy.data.objects。append 一个网格
        物体会**把它蒙皮的骨架一起拖进来**, 按 diff 取第一个会拿到骨架。
      · 一次 load 取全部, 不要循环 load: 每次都要重新把那副骨架拖一遍。
    """
    before_objects = {o.name_full for o in bpy.data.objects}
    before_libs = {lib.name_full for lib in bpy.data.libraries}
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        missing = [n for n in object_names if n not in src.objects]
        if missing:
            raise KeyError("%s 里没有物体 %s；现有: %s"
                           % (os.path.basename(path), missing, sorted(src.objects)[:20]))
        dst.objects = list(object_names)
    wanted = list(dst.objects)
    dragged = [o for o in bpy.data.objects if o.name_full not in before_objects]

    def done():
        for obj in dragged:
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj)
        # append 会留一条指向源文件的库记录; 数据已经是本地的, 那条记录没有用户,
        # 留着只会让文件里挂一个没人要的库指针
        for lib in list(bpy.data.libraries):
            if lib.name_full not in before_libs and not lib.users_id:
                bpy.data.libraries.remove(lib)
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0 and not mesh.use_fake_user:
                bpy.data.meshes.remove(mesh)
        for arm in list(bpy.data.armatures):
            if arm.users == 0 and not arm.use_fake_user:
                bpy.data.armatures.remove(arm)

    return wanted, done


def borrow(path, object_name):
    """借一个物体。见 borrow_many。"""
    objects, done = borrow_many(path, [object_name])
    return objects[0], done


def character_of(rig):
    """一个角色 = 骨架 + 蒙皮到它身上的网格物体。

    判据是"修改器指向谁", 不是父子关系也不是名字 —— 名字会被改, 父子关系可以没有,
    只有蒙皮修改器是这层关系的唯一真源。
    """
    if rig is None or rig.type != 'ARMATURE':
        return []
    return [o for o in bpy.data.objects
            if o.type == 'MESH'
            and any(m.type == 'ARMATURE' and m.object is rig for m in o.modifiers)]


def rig_of(mesh_obj):
    """网格物体蒙皮到哪个骨架上 (没有就 None)。"""
    if mesh_obj is None or mesh_obj.type != 'MESH':
        return None
    for mod in mesh_obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object is not None:
            return mod.object
    return None
