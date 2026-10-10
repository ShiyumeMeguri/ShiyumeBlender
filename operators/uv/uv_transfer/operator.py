"""UV 重定向算子：把源 UV 层上的颜色，按目标排布重新出图。

算子只负责校验、分派、写盘与排布落地；目标排布从哪来由 layout 决定，
颜色从哪来由 providers 里的 descriptor 决定。
"""

import bpy
import numpy as np

from . import graph_bind
from . import image_bind
from . import layout
from . import mesh_bind
from . import providers
from .layout import SOURCE_OBJECT_PROP


class Entry:
    """一个参与重定向的物体、它解析好的目标排布，以及排布最终落在哪份网格上。"""

    def __init__(self, obj, resolved, landing):
        self.obj = obj
        self.mesh = obj.data
        self.layout = resolved
        self.base_loop_uv = resolved.base_loop_uv
        self.render_uv = mesh_bind.render_uv_name(obj.data)
        self.landing = landing

    def slot_materials(self):
        """有面落在上面的材质槽 (槽号, 材质)；槽号超出槽数的面渲染时用最后一个槽。"""
        slots = self.obj.material_slots
        for index in sorted(self.layout.slots):
            material = slots[min(index, len(slots) - 1)].material if len(slots) else None
            yield index, material


class TransferJob:
    """一次重定向的全部输入，以及给 provider 用的汇报通道与节点图查询。"""

    def __init__(self, operator, context, entries):
        self.operator = operator
        self.context = context
        self.settings = context.scene.shiyume_uv_transfer
        self.entries = entries
        self.source_uv = self.settings.source_uv
        self.target_uv = self.settings.target_uv
        # 要写盘时命名还得避开磁盘上已有的文件，不写盘就只避开数据块
        self.output_directory = (self.settings.output_dir
                                 if self.settings.save_to_disk else None)
        self.writes_existing = (self.settings.color_source == 'IMAGE'
                                and self.settings.write_mode == 'EXISTING')
        self.normal_labels = frozenset(label.strip() for label in self.settings.normal_labels.split(",")
                                       if label.strip())
        self.failed = False
        self.turned_data_images = set()
        self.normals_declared = False
        self.unprotected = set()
        self._graphs = {}

    def warn(self, message):
        self.operator.report({'WARNING'}, message)

    def error(self, message):
        self.failed = True
        self.operator.report({'ERROR'}, message)

    def _graph(self, material, mesh):
        render_uv = mesh_bind.render_uv_name(mesh)
        uv_names = frozenset(layer.name for layer in mesh.uv_layers)
        key = (material.as_pointer(), render_uv, uv_names)
        cached = self._graphs.get(key)
        if cached is None:
            cached = graph_bind.samplings(material, render_uv, uv_names,
                                         self.normal_labels, self.settings.normal_convention)
            self._graphs[key] = cached
        return cached

    def samplings(self, material, mesh):
        return self._graph(material, mesh)[0] if material is not None else []

    def unresolved(self, material, mesh):
        return self._graph(material, mesh)[1] if material is not None else []

    def unresolved_images(self):
        """参与材质里经回溯不了、却确实依赖 UV 的坐标采样的贴图（有内容的）名。"""
        names = set()
        for entry in self.entries:
            for _slot, material in entry.slot_materials():
                for item in self.unresolved(material, entry.mesh):
                    if item.uv_dependent and image_bind.has_content(item.image):
                        names.add(item.image.name)
        return sorted(names)

    def relaid_meshes(self):
        """这次排布会变的网格（指针）：参与的网格与排布落地的网格。"""
        meshes = {entry.mesh.as_pointer() for entry in self.entries}
        meshes.update(entry.landing.as_pointer() for entry in self.entries if entry.landing is not None)
        return meshes

    def foreign_users(self, material):
        """用这张材质、但排布不随这次变的物体名。"""
        relaid = self.relaid_meshes()
        return [obj.name for obj in bpy.data.objects
                if getattr(obj, "material_slots", None)
                and (obj.data is None or obj.data.as_pointer() not in relaid)
                and any(slot.material == material for slot in obj.material_slots)]

    def materials_owning(self, tree):
        """节点所在的树归哪些材质：材质自己的树就是那一张，节点组则是所有（逐层）用到它的材质。"""
        materials = []
        for material in bpy.data.materials:
            if material.node_tree is None:
                continue
            if material.node_tree == tree or _uses_group(material.node_tree, tree, set()):
                materials.append(material)
        return materials


def _uses_group(tree, group, visited):
    for node in tree.nodes:
        if node.type != 'GROUP' or node.node_tree is None:
            continue
        if node.node_tree == group:
            return True
        if node.node_tree.as_pointer() not in visited:
            visited.add(node.node_tree.as_pointer())
            if _uses_group(node.node_tree, group, visited):
                return True
    return False


class SHIYUME_OT_UVTransfer(bpy.types.Operator):
    """把源 UV 上的颜色按目标排布重新出图（重采样已有贴图 或 烘焙最终颜色）"""

    bl_idname = "shiyume.uv_transfer"
    bl_label = "生成重定向贴图"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (context.mode == 'OBJECT'
                and obj is not None
                and obj.type == 'MESH')

    def execute(self, context):
        settings = context.scene.shiyume_uv_transfer

        if not settings.source_uv:
            self.report({'ERROR'}, "请先指定源 UV")
            return {'CANCELLED'}
        if settings.target_space == 'UV_LAYER':
            if not settings.target_uv:
                self.report({'ERROR'}, "请先指定目标 UV")
                return {'CANCELLED'}
            if settings.source_uv == settings.target_uv:
                self.report({'ERROR'}, "源 UV 与目标 UV 不能是同一层")
                return {'CANCELLED'}
        elif settings.apply_to_object and not settings.target_uv:
            self.report({'ERROR'}, "「应用到物体」需要一个目标 UV 名，用来接住投影结果")
            return {'CANCELLED'}
        if (settings.save_to_disk and settings.output_dir.startswith("//")
                and not bpy.data.filepath):
            self.report({'ERROR'}, "输出目录是相对路径，请先保存 .blend 或改用绝对路径")
            return {'CANCELLED'}

        entries, notes = self._collect(context, settings)
        if not entries:
            self.report({'ERROR'}, "选中物体里没有可用的网格 — " + (
                "; ".join(notes) if notes else "请选中网格物体"))
            return {'CANCELLED'}

        job = TransferJob(self, context, entries)
        source = providers.get(settings.color_source)

        selection = list(context.selected_objects)
        active = context.view_layer.objects.active
        try:
            result = source.run(job)
        finally:
            self._restore_selection(context, selection, active)

        if result is None or job.failed:
            return {'CANCELLED'}

        saved = self._save(result, settings)
        if settings.apply_to_object:
            source.apply(job, result)
            if settings.merge_material is not None:
                self._assign(job, settings.merge_material)
            self._land_layout(job, settings)

        message = f"{source.label}完成 — {len(result['created'])} 张新图，{len(result['updated'])} 张就地写入"
        if saved:
            message += "，已写盘"
        self.report({'INFO'}, message)
        for note in notes:
            self.report({'WARNING'}, note)
        return {'FINISHED'}

    def _collect(self, context, settings):
        """逐个选中网格解析目标排布与落地网格；解析不了的显式说明原因。"""
        entries = []
        notes = []
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            if settings.source_uv not in obj.data.uv_layers:
                notes.append(f"'{obj.name}' 没有源 UV 层 '{settings.source_uv}'，已跳过")
                continue

            resolved = layout.resolve(context, obj, settings)
            if resolved is None:
                notes.append(f"'{obj.name}' 没有目标 UV 层 '{settings.target_uv}'，已跳过")
                continue
            if (settings.target_space == 'MESH_XY'
                    and SOURCE_OBJECT_PROP not in obj):
                notes.append(
                    f"'{obj.name}' 不是「网格转UV」生成的展平物体，"
                    f"世界投影拿到的是模型本身的俯视轮廓；"
                    f"要按 UV 层重定向请把「目标排布」切成「目标 UV 层」")
            entries.append(Entry(obj, resolved, self._landing_mesh(obj, resolved, settings, notes)))
        return entries, notes

    def _landing_mesh(self, obj, resolved, settings, notes):
        """UV 层模式落在自己身上；世界投影模式落回展平物体的来源物体。落不了返回 None 并说明原因。"""
        if settings.target_space == 'UV_LAYER':
            return obj.data

        origin_name = obj.get(SOURCE_OBJECT_PROP)
        if not origin_name:
            notes.append(f"'{obj.name}' 没有记录来源物体，排布无处可落（它得由「网格转UV」生成）")
            return None
        origin = bpy.data.objects.get(origin_name)
        if origin is None or origin.type != 'MESH':
            notes.append(f"'{obj.name}' 的来源物体 '{origin_name}' 已不存在")
            return None
        if resolved.base_loop_uv is None or len(origin.data.loops) != resolved.base_loop_uv.shape[0]:
            notes.append(f"'{obj.name}' 与来源 '{origin_name}' 的循环数不符")
            return None
        return origin.data

    def _restore_selection(self, context, selection, active):
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selection:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        if active is not None and active.name in context.view_layer.objects:
            context.view_layer.objects.active = active

    def _save(self, result, settings):
        if not settings.save_to_disk:
            return []
        saved = [image_bind.save(image, settings.output_dir) for _output, image in result['created']]
        saved.extend(image_bind.store_in_place(image) for image in result['updated'])
        return saved

    # -- 排布落地 -----------------------------------------------------------

    def _landing_meshes(self, job):
        meshes = []
        for entry in job.entries:
            if entry.landing is not None and all(entry.landing != mesh for mesh in meshes):
                meshes.append(entry.landing)
        return meshes

    def _assign(self, job, material):
        """合并：落地网格的全部面改用这一张材质，其余槽位清掉。"""
        for mesh in self._landing_meshes(job):
            users = [obj for obj in bpy.data.objects if obj.data == mesh]
            if any(slot.link == 'OBJECT' for obj in users for slot in obj.material_slots):
                job.warn(f"'{mesh.name}' 有物体级材质槽，材质分配没动，请手动改成 '{material.name}'")
                continue
            mesh.materials.clear()
            mesh.materials.append(material)
            mesh.polygons.foreach_set("material_index", np.zeros(len(mesh.polygons), dtype=np.int32))
            mesh.update()

    def _land_layout(self, job, settings):
        """把这次用的排布写成目标 UV 层，再与源层对调，让模型直接用上新排布。"""
        landed = set()
        for entry in job.entries:
            if entry.base_loop_uv is None:
                job.warn(f"'{entry.obj.name}' 的修改器改变了拓扑，"
                         f"排布无法落回 UV 层；贴图已出，UV 请手动处理")
                continue
            mesh = entry.landing
            if mesh is None or mesh.name in landed:
                continue
            landed.add(mesh.name)

            if not layout.write_uv_layer(mesh, settings.target_uv, entry.base_loop_uv):
                job.warn(f"'{mesh.name}' 的循环数与投影结果不符，排布未落地")
                continue
            self._swap_uv_layers(mesh, settings.source_uv, settings.target_uv)

    def _swap_uv_layers(self, mesh, source_uv, target_uv):
        """对调两层的 UV 数据：源层拿到新排布，目标层接住旧排布。

        两个层、两个名字都原样保留——按名绑定的节点继续生效，槽位顺序不变，
        旧排布也还在，再执行一次就换回去。
        """
        source_attribute = mesh.attributes.get(source_uv)
        target_attribute = mesh.attributes.get(target_uv)
        if source_attribute is None or target_attribute is None:
            return

        count = len(source_attribute.data) * 2
        source_values = np.empty(count, dtype=np.float32)
        target_values = np.empty(count, dtype=np.float32)
        source_attribute.data.foreach_get("vector", source_values)
        target_attribute.data.foreach_get("vector", target_values)
        source_attribute.data.foreach_set("vector", target_values)
        target_attribute.data.foreach_set("vector", source_values)
        mesh.update()
