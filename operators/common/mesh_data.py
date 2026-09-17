"""网格与它带来的着色数据的合并语义: 谁盖谁、什么必须保留。只有这一份实现, 拉取和推送共用。

共享的是几何 / 拓扑 / 权重 / 形态键的**形状**, 以及材质槽和材质本身。
每个文件自己的形态键**值**不共享 —— 那是本文件的体型设定, 是视图状态不是内容。

顶点权重存的是"组下标 -> 权重", 组**名**存在物体上。所以换网格数据块的同时必须把
顶点组名表一起换成来源那一份, 否则权重会静默错位到别的骨头上。名表作为参数传进来,
是因为推送时中转文件里只有网格数据块 —— 连物体一起写会把骨架和那条几百万关键帧的
动作一并拖进去。

材质 (以及材质用的贴图、节点组) 永远是 append 带进来的**另一份**数据块: 目标文件里
已经有 `M_Skin`, 带进来的那份必然叫 `M_Skin.001`。不接管身份就是三个后果 —— 换过去的
网格指着新的那份, 文件里别的东西还指着旧的那份 (人看到的就是"材质没更新"); 名字一路
`.001/.002` 往下漂, 而导出到引擎那头是按材质名对表的, 名字一漂就对不上; 旧的那份每推
一次留一个孤儿。所以带进来的那份必须**接管**旧的身份: 旧的全部用户改指新的 -> 删掉旧的
-> 新的改回原名。文件里一个名字永远只有一份数据。

"我是谁的副本"不靠剥 `.001` 后缀猜: Blender 给每个 append 进来的数据块记了
library_weak_reference, 里面的 id_name 就是它在源文件里的名字 (前两位是数据块类型码)。
"""

import bpy

# append 一律另造一份, 所以这些族都要按名接管身份 (网格自己在 swap_mesh 里接管)
ADOPTED_COLLECTIONS = ('materials', 'images', 'node_groups', 'textures')

# library_weak_reference.id_name 的前两位是数据块类型码, 后面才是名字
ID_NAME_TYPE_PREFIX = 2


def known_names(collections=ADOPTED_COLLECTIONS):
    """append 之前的名录。adopt_appended 靠它认出哪些数据块是刚带进来的。

    记的是 name_full 不是 name: 库链接进来的数据块和本地的**可以同名** (名字只在各自的库里
    唯一), 按 name 记会把刚带进来的那份当成本来就有的, 于是一份都不接管。
    """
    return {name: {item.name_full for item in getattr(bpy.data, name)} for name in collections}


def take_over(incoming, old, collection):
    """incoming 接管 old 的身份, 返回 old 原有的用户数。

    顺序是硬的, 两步都不能反:
      · 先改指再删 —— remove() 默认 do_unlink, 还在用 old 的东西会被指向空。
      · 先删再改名 —— 反过来 old 还占着那个名字, 改名只会拿到一个 `.001`, 名字就此漂掉。
    """
    if old.library is not None:
        raise RuntimeError("%s 来自库链接, 覆盖不了; 先按「本地化全部链接数据」" % old.name)
    name = old.name
    users = old.users
    old.user_remap(incoming)
    incoming.use_fake_user = incoming.use_fake_user or old.use_fake_user
    collection.remove(old)
    incoming.name = name
    return users


def _source_name(item):
    """这个 append 进来的数据块在源文件里叫什么 —— Blender 自己记的, 不靠剥后缀猜。"""
    reference = item.library_weak_reference
    return None if reference is None else reference.id_name[ID_NAME_TYPE_PREFIX:]


def appended_since(known):
    """append 之后新冒出来的数据块, 按集合分。"""
    return {name: [item for item in getattr(bpy.data, name) if item.name_full not in before]
            for name, before in known.items()}


def adopt_appended(known):
    """把 append 带进来的着色数据块按名接管同名旧数据块。返回 (接管了什么, 提示列表)。

    分两轮, 因为源文件里本来就可能有 `X` 和 `X.001` 这种同词干的两份: 它们进来之后叫
    `X.001` 和 `X.002`, 而 `X.001` 这个名字此刻正被前者顶着 —— 第一轮谁的原名被**本来就在**
    的数据块占着, 谁就接管那一份; 第二轮原名已经腾空的直接归位。一轮做完会张冠李戴。
    """
    lines, notes = [], []
    for collection_name, newcomers in appended_since(known).items():
        collection = getattr(bpy.data, collection_name)
        pending = []
        for item in newcomers:
            source_name = _source_name(item)
            if source_name is None:
                notes.append("%s 没记下自己是谁的副本, 名字留着不动" % item.name)
                continue
            if item.name == source_name:
                continue            # 没撞名: 这个名字本来就是空的, 直接落地就是对的
            # 点名要本地那一份: 同名的库链接数据块也在这个集合里, 而它写不进去
            old = collection.get((source_name, None))
            if old is None or old in newcomers:
                pending.append((item, source_name))
                continue
            lines.append("%s (原有 %d 个用户)"
                         % (source_name, take_over(item, old, collection)))
        for item, source_name in pending:
            if collection.get((source_name, None)) is not None:
                notes.append("%s 的原名 %s 还被别的数据块占着, 它只能留着叫 %s"
                             % (item.name, source_name, item.name))
                continue
            item.name = source_name
            lines.append("%s (原本地没有同名的)" % source_name)
    return lines, notes


def image_paths(names):
    """{图片数据块名: 它的路径字符串}。`//` 开头的是相对**本文件**的。"""
    rows = {}
    for name in names:
        image = bpy.data.images.get((name, None))
        if image is not None:
            rows[name] = image.filepath
    return rows


def apply_image_paths(rows):
    """把路径字符串按名写回图片数据块。返回 (改了几张, 提示列表)。

    必须显式写回, 不能指望 append: append 会把相对路径**按来源文件所在的位置重算**一遍。
    推送的来源是临时目录里的中转文件, 于是 `//textures/skin.png` 被重算成
    `//../../../../../AppData/Local/Temp/textures/skin.png` —— 指向一个根本不存在的地方,
    材质在共用文件里就是紫的。两个文件的目录结构一样, 原样的相对写法才是对的那个。
    """
    changed, notes = 0, []
    for name, path in rows.items():
        image = bpy.data.images.get((name, None))
        if image is None:
            notes.append("图片 %s 不在这个文件里, 路径没写回" % name)
            continue
        if image.filepath != path:
            image.filepath = path
            changed += 1
    return changed, notes


def slot_rows(obj):
    """材质槽读成纯数据, 好隔着进程搬。

    槽位有两种来路: 'DATA' 的材质存在网格数据块上, 跟着网格一起走; 'OBJECT' 的存在物体上,
    换网格数据块动不到它, 必须单独搬。
    """
    return [{'link': slot.link, 'material': slot.material.name if slot.material else None}
            for slot in obj.material_slots]


def _slot_materials(obj):
    """物体上实际生效的槽位材质名 —— 'DATA' 和 'OBJECT' 两种来路的最终结果。"""
    return [slot.material.name if slot.material else None for slot in obj.material_slots]


def _apply_slots(target_obj, rows):
    """把来源的材质槽写到 target_obj 上。

    'DATA' 的那份跟着网格数据块已经到位; 'OBJECT' 的必须逐个按名指回去 —— 名字能查到,
    是因为材质数据块已经在 adopt_appended 里接管过身份了, 一个名字只有一份数据。
    """
    if len(target_obj.material_slots) != len(rows):
        raise RuntimeError("%s 换完之后 %d 个材质槽, 来源是 %d 个"
                           % (target_obj.name, len(target_obj.material_slots), len(rows)))
    for slot, row in zip(target_obj.material_slots, rows):
        slot.link = row['link']
        if row['link'] == 'OBJECT':
            # 只认本地那一份: 搬过来的材质一定是本地的, 拿一个同名的库链接材质顶上去
            # 等于悄悄换了张脸 —— 查不到就让槽位空着, 下面的闸门会当场报出来
            slot.material = (bpy.data.materials.get((row['material'], None))
                             if row['material'] else None)


def swap_mesh(target_obj, incoming, source_groups, source_weighted=None, source_slots=None):
    """把 incoming 这份网格装到 target_obj 上, 保留 target 自己的形态键值。

    incoming:        来源的网格数据块 (已经在本文件里)
    source_groups:   来源物体的顶点组名表
    source_weighted: 来源网格里带权重的顶点数, 用来当闸门 (None 就跳过检查)
    source_slots:    来源物体的材质槽 (slot_rows 的结果; None 就不动材质槽)
    返回 (总结, 提示列表)。
    """
    old = target_obj.data
    if incoming is old:
        return "%s: 来源和本地是同一份数据, 没动" % target_obj.name, []
    notes = []

    kept_values = ({k.name: (k.value, k.mute) for k in old.shape_keys.key_blocks}
                   if old.shape_keys else {})
    old_groups = [g.name for g in target_obj.vertex_groups]
    old_materials = _slot_materials(target_obj)
    before_verts = len(old.vertices)

    # 顶点组必须在**换数据之前**重建。
    # vertex_groups.remove() 删的是"当前挂着的那份网格"里的权重 —— 先换数据再删组,
    # 删掉的就是刚装上的新网格的权重。实测三个网格 809/1106/29 个组全删完,
    # 带权重的顶点变成 0, 网格纹丝不动, 看上去就是"动画没了"。
    regrouped = list(source_groups) != old_groups
    if regrouped:
        for group in list(target_obj.vertex_groups):
            target_obj.vertex_groups.remove(group)
        for name in source_groups:
            target_obj.vertex_groups.new(name=name)

    target_obj.data = incoming

    restored = 0
    if incoming.shape_keys:
        for block in incoming.shape_keys.key_blocks:
            if block.name in kept_values:
                block.value, block.mute = kept_values[block.name]
                restored += 1
            else:
                notes.append("新形态键 %s (本地原本没有, 用来源的值)" % block.name)
        for name in kept_values:
            if name not in incoming.shape_keys.key_blocks:
                notes.append("形态键 %s 在来源里已不存在, 本地也随之消失" % name)
    elif kept_values:
        notes.append("来源没有形态键, 本地原有的 %d 个随之消失" % len(kept_values))

    if regrouped:
        notes.append("顶点组名表已按来源重建 (%d -> %d); 权重存的是组下标, 不换名表会错位"
                     % (len(old_groups), len(source_groups)))

    # 硬闸门: 换完之后带权重的顶点数必须和来源一致, 一个都不能少
    weighted = sum(1 for v in incoming.vertices if v.groups)
    if source_weighted is not None and weighted != source_weighted:
        raise RuntimeError("%s 换完之后带权重的顶点 %d, 来源是 %d —— 权重丢了"
                           % (target_obj.name, weighted, source_weighted))

    materials = old_materials
    if source_slots is not None:
        _apply_slots(target_obj, source_slots)
        materials = _slot_materials(target_obj)
        expected = [row['material'] for row in source_slots]
        # 硬闸门: 每个槽位都必须落在来源那份材质上。对不上就是有一份没接管成 (比如撞上了
        # 库链接的同名材质), 这时候宁可整个推送不落盘, 也不要留一份"材质没更新"的文件
        if materials != expected:
            raise RuntimeError("%s 的材质槽落地成 %s, 来源是 %s"
                               % (target_obj.name, materials, expected))
        if materials != old_materials:
            notes.append("材质槽已按来源重排 (%s -> %s)" % (old_materials, materials))

    take_over(incoming, old, bpy.data.meshes)

    summary = ("%s 顶点 %d -> %d, 带权重 %d, 保留 %d 个形态键值, 材质 %s"
               % (target_obj.name, before_verts, len(incoming.vertices),
                  weighted, restored, materials))
    return summary, notes
