"""角色单位: 一副骨架 + 蒙皮到它身上的全部网格。

判据是**修改器指向谁**, 不是父子关系也不是名字 —— 名字会被改, 父子关系可以没有, 只有蒙皮
修改器是这层关系的唯一真源。选中任意一个子网格都能推出整个角色, 于是绑定/摘下/解绑都按
角色一次做完, 不用一个一个点。

认人分两层, **记着的身份优先, 名字只是没身份时的初次猜测**:

  绑过一次的, 身份就写在物体的自定义数据里 (remember_binding), 之后一律照它认 —— 名字随便
  怎么变都不影响。这是必须的: 一个文件里放两个模型时, 两个物体必然都想叫同一个名字, 而
  Blender 不许重名, 于是至少有一个的名字对不上源。靠名字认人这条路在那一刻就断了。

  还没有身份的, 按**物体名**猜一次, 不按数据块名: append/链接进场景之后数据块名必然被加
  `.001` 后缀, 按数据块名回源文件找, 实测 17 个里只能命中 1 个; 按物体名命中 15 个。猜中就
  当场把身份记下来, 这一步只走一次。猜不中的直接跳过 —— 场景里本来就有主模型没有的东西
  (机械骨、锚点、临时切出来的部件), 那不是错误, 手动指定一次它也就有身份了。
"""

import os

import bpy


def character_of(rig):
    """骨架 -> 蒙皮到它身上的网格物体。"""
    if rig is None or rig.type != 'ARMATURE':
        return []
    return [obj for obj in bpy.data.objects
            if obj.type == 'MESH'
            and any(modifier.type == 'ARMATURE' and modifier.object is rig
                    for modifier in obj.modifiers)]


def rig_of(mesh_object):
    """网格物体蒙皮到哪副骨架上 (没有就 None)。"""
    if mesh_object is None or mesh_object.type != 'MESH':
        return None
    for modifier in mesh_object.modifiers:
        if modifier.type == 'ARMATURE' and modifier.object is not None:
            return modifier.object
    return None


def active_character(context):
    """从当前选中推出角色: 选骨架就是它本身, 选网格就是它蒙皮的那副骨架。

    返回 (骨架, 网格列表); 推不出角色时返回 (None, [])。
    """
    obj = context.active_object
    if obj is None:
        return None, []
    if obj.type == 'ARMATURE':
        return obj, character_of(obj)
    if obj.type == 'MESH':
        rig = rig_of(obj)
        if rig is not None:
            return rig, character_of(rig)
    return None, []


def members(context):
    """角色的全部成员物体 (骨架在前); 推不出角色就退回当前选中。

    退回选中而不是报错: 单个物体也该能绑, 没蒙皮的道具、还没接骨架的部件都是常态。
    """
    rig, meshes = active_character(context)
    if rig is not None:
        return [rig] + meshes
    return [obj for obj in context.selected_objects if obj.data is not None]


BOUND_SOURCE_KEY = "shiyume_bound_source"
BOUND_NAME_KEY = "shiyume_bound_name"


def remember_binding(obj, path, source_name):
    """身份写在物体自己身上, 不靠名字。

    名字不是身份。一个文件里放两个模型时, 两个物体必然都想叫 `Mesh_Body_01` —— 那是正常用法
    不是错误, 而 Blender 不允许重名, 于是至少有一个名字对不上源。靠名字认人这条路在那一刻就
    断了, 所以认人的依据必须是这里记下的这一对字符串。

    源改名 / 物体改名 / 撞名让位, 它都不动; 只有重新指定来源才会改写它。
    """
    obj[BOUND_SOURCE_KEY] = path
    obj[BOUND_NAME_KEY] = source_name


def binding_of(obj):
    """物体记着的身份 -> (源文件绝对路径, 源里的数据块名) 或 None。"""
    if obj is None:
        return None
    path = obj.get(BOUND_SOURCE_KEY)
    name = obj.get(BOUND_NAME_KEY)
    if not path or not name:
        return None
    return os.path.abspath(bpy.path.abspath(path)), name


def forget_binding(obj):
    hit = False
    for key in (BOUND_SOURCE_KEY, BOUND_NAME_KEY):
        if key in obj.keys():
            del obj[key]
            hit = True
    return hit


def align_name(obj, datablock):
    """名字空着就跟数据块对齐, 被别的物体占着就保持原样。

    对齐只是让人看着顺眼, **不是身份** —— 身份在 remember_binding 记的那一对字符串上。所以
    撞名不是错误, 也不去动占着名字的那个物体: 一个文件里两个模型共用同一件身体, 本来就只能
    有一个叫得上那个名字。
    """
    if obj.name == datablock.name:
        return False
    squatter = bpy.data.objects.get(datablock.name)
    if squatter is not None and squatter is not obj:
        return False
    obj.name = datablock.name
    return True


def source_object_names(path):
    """源文件里有哪些物体 —— 只读目录, 一个字节的数据都不加载。"""
    with bpy.data.libraries.load(path) as (source, _target):
        return list(source.objects)


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


def plan(objects, path):
    """这些物体各自该挂源里的哪一个数据块 -> [(物体, 源数据块名 或 None)]。

    记着身份的照身份走, 源文件的目录一个字节都不用读 —— 名字对不上、被别人占了、干脆改成了
    别的, 一律不影响。没身份的才按物体名猜一次, 猜中之后 bind_one 会把身份记下来, 这条路对
    同一个物体只走一次。

    身份里记的源文件跟这次要绑的不是同一个, 就退回猜 —— 那是在改挂别的源, 旧身份里那个名字
    换个文件未必还是同一件东西。
    """
    remembered = []
    guessing = []
    for obj in objects:
        binding = binding_of(obj)
        if binding is not None and binding[0] == path:
            remembered.append((obj, binding[1]))
        else:
            guessing.append(obj)
    if not guessing:
        return remembered

    available = source_object_names(path)
    guesses = [(obj, _match(obj.name, available)) for obj in guessing]
    mapping = source_object_data_map(path, [name for _obj, name in guesses if name is not None])
    return remembered + [(obj, mapping.get(name) if name is not None else None)
                         for obj, name in guesses]


def source_object_data_map(path, names):
    """源文件里点名的这几个物体 -> 它们各自的数据块名。

    这层关系只有把物体真的链进来才看得见: 上面那个名录只给各类数据块的名字, 给不出"哪个物体
    用哪个数据块"。所以**先按名字定下要哪几个, 只链那几个** —— 源文件里有几百个物体时, 全链
    一遍再删掉是白跑一趟。

    链接不拷贝数据; 读完把临时链进来的**物体**删掉就行, 数据块留着正好, 紧接着绑定就要用。
    """
    before = {obj.name_full for obj in bpy.data.objects}
    with bpy.data.libraries.load(path, link=True) as (source, target):
        available = set(source.objects)
        target.objects = [name for name in names if name in available]
    dragged = [obj for obj in bpy.data.objects if obj.name_full not in before]
    mapping = {obj.name: obj.data.name for obj in dragged if obj.data is not None}
    for obj in dragged:
        bpy.data.objects.remove(obj)
    return mapping
