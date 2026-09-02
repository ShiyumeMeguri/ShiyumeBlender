"""清理顶点组: 一切判据都取自实际证据, 不猜命名约定。

核心是一句话: **一个顶点组该不该留, 问求值后的结果, 不问基础网格。**

基础网格上"空"不等于没用。最典型的是镜像修改器: 开了 `顶点组` 选项时, 镜像
出来的顶点会去找名字翻转后的那个组, **那个组存在(哪怕完全是空的)才会进去,
不存在就留在原来的组里** —— 于是镜像那半边被对侧骨骼驱动, 而且没有任何报错。
所以对侧那个空组是必需的接收槽。

早先的写法是自己用 `bpy.utils.flip_name` 推一遍 `_L/_R` 去保护它。那是局部最优:
它只认镜像这一种情况, 而且把"翻转规则"这件本属于修改器的知识抄了一份。
求值后的网格已经把答案摆在那了 —— 那个空组在求值结果里是**带权重的**。
于是判据退化成一句与修改器种类无关的话, 顺带自动覆盖几何节点写组、
数据传递、顶点权重编辑等所有会往组里写东西的情形。

同理, "哪些组不能删"也不该是一张写死的名字表: 被 Mask / Displace / 形态键 /
粒子 / 物理 引用的组即使一个权重都没有也不能删, 这件事扫一遍引用就知道。
名字表只保留为**逃生口**, 因为确实存在 blend 文件之外的消费者
(导出器、着色管线), 那种引用任何扫描都看不见。
"""

import bpy

_REFERENCE_OWNER_ATTRS = ('settings', 'collision_settings', 'domain_settings',
                          'flow_settings', 'effector_settings', 'canvas_settings',
                          'brush_settings')


def _string_group_refs(owner, out):
    """收集 owner 上所有形如 vertex_group* 的字符串属性值。"""
    if owner is None:
        return
    try:
        properties = owner.bl_rna.properties
    except AttributeError:
        return
    for prop in properties:
        if prop.type != 'STRING' or 'vertex_group' not in prop.identifier:
            continue
        value = getattr(owner, prop.identifier, '')
        if value:
            out.add(value)


def _geometry_nodes_attribute_refs(modifier, out):
    """几何节点修改器上"按属性输入"里填的名字 —— 顶点组就是一种属性。

    这块 API 在版本间搬过家 (旧版是修改器上的 ID 属性 `Input_N_attribute_name`,
    5.x 换成了 `modifier.properties.inputs`, 旧写法在 5.2 直接抛 TypeError),
    所以两条路都试, 都取不到就安静跳过 —— 这是一条"多保护一点"的证据来源,
    读不到最多是少保护, 不该让整个扫描崩掉。
    """
    try:
        for item in modifier.properties.inputs:
            if getattr(item, 'use_attribute', False):
                name = getattr(item, 'attribute_name', '')
                if name:
                    out.add(name)
        return
    except (AttributeError, TypeError):
        pass
    try:
        for key in modifier.keys():
            if key.endswith('_attribute_name'):
                value = modifier[key]
                if isinstance(value, str) and value:
                    out.add(value)
    except (AttributeError, TypeError):
        pass


def referenced_group_names(obj):
    """对象上有东西明确引用着的顶点组名 —— 这些组即使一个权重都没有也不能删。

    覆盖: 修改器 (Mask/Displace/Shrinkwrap/VertexWeight*/Cloth/SoftBody/...
    及其 settings 子结构)、几何节点修改器的属性输入、形态键的限制组、
    粒子系统、物体级软体/碰撞/力场。
    """
    out = set()
    for modifier in obj.modifiers:
        _string_group_refs(modifier, out)
        for attr in _REFERENCE_OWNER_ATTRS:
            _string_group_refs(getattr(modifier, attr, None), out)
        if modifier.type == 'NODES':
            _geometry_nodes_attribute_refs(modifier, out)
    if obj.data.shape_keys:
        for block in obj.data.shape_keys.key_blocks:
            if block.vertex_group:
                out.add(block.vertex_group)
    for system in obj.particle_systems:
        _string_group_refs(system, out)
    _string_group_refs(obj.soft_body, out)
    _string_group_refs(obj.collision, out)
    _string_group_refs(obj.field, out)
    return out


def weighted_group_names(obj, depsgraph=None):
    """带非零权重的顶点组名 = 基础网格 ∪ 求值结果。

    取并集而不是只看求值结果: 某些修改器会把组吃掉 (Mask 删几何、几何节点换
    数据块), 那种情况下基础网格上的权重同样是"在用"的证据。
    """
    names = set()

    def collect(source):
        lookup = {g.index: g.name for g in source.vertex_groups}
        mesh = source.data
        if not hasattr(mesh, 'vertices'):
            return
        for vertex in mesh.vertices:
            for element in vertex.groups:
                if element.weight > 0.0:
                    name = lookup.get(element.group)
                    if name:
                        names.add(name)

    collect(obj)
    if depsgraph is not None:
        collect(obj.evaluated_get(depsgraph))
    return names


class _RenderModifiersForced:
    """临时把"渲染开、视口关"的修改器在视口里也打开。

    求值走的是视口 depsgraph; 一个镜像修改器如果被关了视口显示, 求值结果里
    就看不到接收槽, 清理会把它删掉 —— 而渲染时它仍然生效, 于是渲染出来的
    镜像半边挂到错误的骨骼上。判据必须按"最终会渲染成什么"来取。
    """

    def __init__(self, obj):
        self.obj = obj
        self.restore = []

    def __enter__(self):
        for modifier in self.obj.modifiers:
            if modifier.show_render and not modifier.show_viewport:
                self.restore.append(modifier)
                modifier.show_viewport = True
        if self.restore:
            bpy.context.view_layer.update()
        return self

    def __exit__(self, *exc):
        for modifier in self.restore:
            modifier.show_viewport = False
        if self.restore:
            bpy.context.view_layer.update()
        return False


def plan_removals(obj, context, remove_no_bone=True, remove_no_weight=True,
                  effective_weight=True, keep_names=()):
    """算出该删哪些顶点组, 不做任何修改 (操作符与自检共用这一个判据)。

    返回 (待删名字列表, 诊断 dict)。
    """
    armature = obj.find_armature()
    deform_bones = ({b.name for b in armature.data.bones if b.use_deform}
                    if armature else set())

    with _RenderModifiersForced(obj):
        depsgraph = context.evaluated_depsgraph_get()
        weighted = weighted_group_names(obj, depsgraph)

    effective = (weighted & deform_bones) if (effective_weight and armature) else weighted
    referenced = referenced_group_names(obj)
    protected = referenced | set(keep_names)

    doomed = []
    for group in obj.vertex_groups:
        name = group.name
        if name in protected:
            continue
        if remove_no_bone and armature and name not in deform_bones:
            doomed.append(name)
        elif remove_no_weight and name not in effective:
            doomed.append(name)

    return doomed, {
        'armature': armature.name if armature else None,
        'weighted': len(weighted),
        'effective': len(effective),
        'referenced': len(referenced),
        'kept_by_reference': len(referenced & {g.name for g in obj.vertex_groups} - effective),
    }


class SHIYUME_OT_CleanupVertexGroups(bpy.types.Operator):
    """清理顶点组：按"骨架上没有同名形变骨骼"和"没有有效权重"两个判据清，
    最后用 Blender 内置功能归一化。

    判据全部取自实际证据，不猜命名约定：
    · 是否"空"看求值后的结果（镜像/几何节点等修改器写进去的权重都算数），
      所以镜像对侧那些基础网格上是空的接收槽不会被误删；
    · 被 Mask/Displace/形态键/粒子/物理 引用的组即使没权重也不删；
    · 有效权重不是单纯的 权重>0：叫 aaa 的组即使写着 1，骨架上没有 aaa 这根
      形变骨，它就驱动不了任何东西，等同于 0。"""
    bl_idname = "shiyume.cleanup_vgs"
    bl_label = "清理顶点组"
    bl_options = {'REGISTER', 'UNDO'}

    remove_no_bone: bpy.props.BoolProperty(
        name="删除骨架上不存在的组", default=True,
        description="组名在骨架里找不到同名形变骨骼就删。对象没有骨架时此项不生效")
    remove_no_weight: bpy.props.BoolProperty(
        name="删除没有有效权重的组", default=True,
        description="没有任何顶点带有效权重的组就删")
    effective_weight: bpy.props.BoolProperty(
        name="按骨架判定有效权重", default=True,
        description="判定权重时只有对应到形变骨骼的组才算数：\n"
                    "叫 aaa 的组权重写着 1，但骨架上没有 aaa 这根骨，它实际驱动不了\n"
                    "任何东西，视为 0。关掉则只看权重数值是否 > 0")
    normalize: bpy.props.BoolProperty(
        name="归一化权重", default=True,
        description="清理完用 Blender 内置的『全部归一化』收尾。\n"
                    "有骨架时按形变骨骼归一化，不会把遮罩类组算进分母")
    keep_names: bpy.props.StringProperty(
        name="保留名单", default="Alpha,Red,Green,Blue",
        description="逗号分隔，永不删除。仅用于 blend 文件之外的消费者\n"
                    "（导出器、着色管线）——文件内部的引用已经自动扫描，不必写在这里")

    @classmethod
    def poll(cls, context):
        return bool(cls._targets(context))

    @staticmethod
    def _targets(context):
        out = [o for o in (context.selected_objects or ()) if o.type == 'MESH']
        active = context.active_object
        if active is not None and active.type == 'MESH' and active not in out:
            out.append(active)
        return out

    def execute(self, context):
        keep = tuple(n.strip() for n in self.keep_names.split(',') if n.strip())
        targets = self._targets(context)
        removed_total = 0
        saved_total = 0
        lines = []

        for obj in targets:
            doomed, info = plan_removals(
                obj, context,
                remove_no_bone=self.remove_no_bone,
                remove_no_weight=self.remove_no_weight,
                effective_weight=self.effective_weight,
                keep_names=keep)
            for name in doomed:
                obj.vertex_groups.remove(obj.vertex_groups[name])
            if self.normalize and len(obj.vertex_groups):
                self._normalize(context, obj, info['armature'] is not None)
            removed_total += len(doomed)
            saved_total += info['kept_by_reference']
            if doomed:
                lines.append("%s -%d" % (obj.name, len(doomed)))

        self.report({'INFO'},
                    "清理 %d 个顶点组，跨 %d 个网格；因被引用而保住 %d 个%s"
                    % (removed_total, len(targets), saved_total,
                       ("；" + ", ".join(lines)) if lines else ""))
        return {'FINISHED'}

    @staticmethod
    def _normalize(context, obj, has_armature):
        """用引擎内置的归一化，不自己算。

        有骨架就按 BONE_DEFORM：只归一化对应形变骨骼的那些组。实测 ALL 模式会
        把遮罩类组一起算进分母，把它们的数值改掉。
        """
        view_layer = context.view_layer
        previous_active = view_layer.objects.active
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        view_layer.objects.active = obj
        try:
            bpy.ops.object.vertex_group_normalize_all(
                group_select_mode='BONE_DEFORM' if has_armature else 'ALL',
                lock_active=False)
        except RuntimeError:
            pass
        finally:
            view_layer.objects.active = previous_active
