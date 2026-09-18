"""材质跟不跟源, 是每个物体自己的事。

材质槽有两种归属, 这是 Blender 本来就有的语义:

  link='DATA'     槽位挂在**网格数据块**上。网格是从源链来的, 材质自然就是源的那一套 ——
                  源换了材质这边跟着换。默认。
  link='OBJECT'   槽位挂在**物体**上。同一个网格被两个物体用, 两边可以各挂各的材质, 换源
                  也不动它。

所以"取消材质同步"不需要自己造一套记账表: 把槽位改成挂物体就是了。per-object 天然成立,
存盘自带, 也不会和链接那套打架 —— 网格照旧跟着源, 只有材质不跟。

开关是物体上的一个属性, 拧一下当场兑现。关掉的那一刻把当前显示的材质种进物体槽位, 否则
一拧就变空, 人会以为坏了。
"""

import bpy

SYNC_PROPERTY = "shiyume_sync_materials"


def is_syncing(obj):
    return bool(getattr(obj, SYNC_PROPERTY, True))


def apply_to(obj):
    """把开关的状态兑现到材质槽的归属上。返回改了几个槽。"""
    if obj is None or obj.type != 'MESH' or obj.data is None:
        return 0
    wanted = 'DATA' if is_syncing(obj) else 'OBJECT'
    changed = 0
    for slot in obj.material_slots:
        if slot.link == wanted:
            continue
        showing = slot.material          # 先记下现在显示的那一份
        slot.link = wanted
        if wanted == 'OBJECT' and slot.material is None:
            slot.material = showing      # 挂到物体上时种回去, 免得一拧就空
        changed += 1
    return changed


def snapshot(obj):
    """物体自己那一套材质; 换网格之前记下来, 换完再种回去。"""
    return [slot.material for slot in obj.material_slots]


def restore(obj, materials):
    """把记下来的材质种回物体槽位。槽位数变了就按位置对齐, 多出来的不管。"""
    if is_syncing(obj):
        return 0
    restored = 0
    for slot, material in zip(obj.material_slots, materials):
        if material is None or slot.material is material:
            continue
        slot.material = material
        restored += 1
    return restored


def _on_toggle(self, _context):
    apply_to(self)


def register():
    setattr(bpy.types.Object, SYNC_PROPERTY, bpy.props.BoolProperty(
        name="材质跟源",
        description="关掉之后这个物体的材质挂在物体自己身上, 换源也不跟着变; "
                    "网格照旧跟着源走",
        default=True,
        update=_on_toggle,
    ))


def unregister():
    if hasattr(bpy.types.Object, SYNC_PROPERTY):
        delattr(bpy.types.Object, SYNC_PROPERTY)
