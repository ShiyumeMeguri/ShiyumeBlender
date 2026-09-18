"""角色单位: 一副骨架 + 蒙皮到它身上的全部网格。

判据是**修改器指向谁**, 不是父子关系也不是名字 —— 名字会被改, 父子关系可以没有, 只有蒙皮
修改器是这层关系的唯一真源。选中任意一个子网格都能推出整个角色, 于是绑定/摘下/解绑都按
角色一次做完, 不用一个一个点。

绑定按**物体名**对号入座, 不按数据块名: append/链接进场景之后数据块名必然被加 `.001` 后缀,
按数据块名回源文件找, 实测 17 个里只能命中 1 个; 按物体名命中 15 个。物体名是稳定的那一头。
对不上的直接跳过 —— 场景里本来就有主模型没有的东西 (机械骨、锚点、临时切出来的部件),
那不是错误。
"""

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


def align_name(obj, datablock):
    """物体名跟着它的数据块走。

    手动指定之后两边必须一模一样, 否则下一次自动对号入座又对不上 —— 那正是当初断链的成因:
    源改了名, 老模型的物体名还留在原地, 按名字就再也认不出它该挂谁。

    名字被别的物体占着时**报错**, 不替人改名: 那说明场景里有两个物体都认领同一件共用体, 该
    先把重复处理掉。偷偷把别人改成 `X_旧` 看着像帮忙, 实际是在用户场景里动了他没让动的东西,
    而且下次他找不到那个物体。
    """
    if obj.name == datablock.name:
        return False
    squatter = bpy.data.objects.get(datablock.name)
    if squatter is not None and squatter is not obj:
        raise RuntimeError("已经有一个物体叫 %r 了; 两个物体认领同一件共用数据, 先处理掉重复"
                           % datablock.name)
    obj.name = datablock.name
    return True


def source_object_names(path):
    """源文件里有哪些物体 —— 只读目录, 一个字节的数据都不加载。"""
    with bpy.data.libraries.load(path) as (source, _target):
        return list(source.objects)


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
