"""UV 重定向算子：把源 UV 层上的颜色，按目标排布重新出图。

算子只负责校验、分派、写盘与排布落地；目标排布从哪来由 layout 决定，
颜色从哪来由 providers 里的 descriptor 决定。
"""

import bpy
import numpy as np

from . import image_bind
from . import layout
from . import providers
from .layout import SOURCE_OBJECT_PROP


class Entry:
    """一个参与重定向的物体，以及它解析好的每 loop 目标坐标。"""

    def __init__(self, obj, loop_uv):
        self.obj = obj
        self.mesh = obj.data
        self.loop_uv = loop_uv


class TransferJob:
    """一次重定向的全部输入，以及给 provider 用的汇报通道。"""

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
        self.failed = False

    def warn(self, message):
        self.operator.report({'WARNING'}, message)

    def error(self, message):
        self.failed = True
        self.operator.report({'ERROR'}, message)


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

        entries, skipped = self._collect(context, settings)
        if not entries:
            self.report({'ERROR'}, "选中物体里没有可用的网格 — " + (
                "; ".join(skipped) if skipped else "请选中网格物体"))
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

        saved = self._save(result['outputs'], settings)
        if settings.apply_to_object:
            source.apply(job, result)
            self._land_layout(job, settings)

        message = f"{source.label}完成 — {len(result['outputs'])} 张贴图"
        if saved:
            message += f"，已写入 {settings.output_dir}"
        self.report({'INFO'}, message)
        for note in skipped:
            self.report({'WARNING'}, note)
        return {'FINISHED'}

    def _collect(self, context, settings):
        """逐个选中网格解析目标排布；解析不了的显式说明原因。"""
        entries = []
        skipped = []
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            if settings.source_uv not in obj.data.uv_layers:
                skipped.append(f"'{obj.name}' 没有源 UV 层 '{settings.source_uv}'，已跳过")
                continue

            loop_uv = layout.resolve_loop_uv(context, obj, settings)
            if loop_uv is None:
                if settings.target_space == 'UV_LAYER':
                    skipped.append(
                        f"'{obj.name}' 没有目标 UV 层 '{settings.target_uv}'，已跳过")
                else:
                    skipped.append(
                        f"'{obj.name}' 的修改器改变了拓扑，无法逐 loop 对应，已跳过")
                continue
            entries.append(Entry(obj, loop_uv))
        return entries, skipped

    def _restore_selection(self, context, selection, active):
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selection:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        if active is not None and active.name in context.view_layer.objects:
            context.view_layer.objects.active = active

    def _save(self, outputs, settings):
        if not settings.save_to_disk:
            return []
        return [image_bind.save(image, settings.output_dir) for image in outputs]

    # -- 排布落地 -----------------------------------------------------------

    def _land_layout(self, job, settings):
        """把这次用的排布写成目标 UV 层，再与源层对调，让模型直接用上新排布。"""
        landed = set()
        for entry in job.entries:
            mesh = self._destination_mesh(job, entry, settings)
            if mesh is None or mesh.name in landed:
                continue
            landed.add(mesh.name)

            if not layout.write_uv_layer(mesh, settings.target_uv, entry.loop_uv):
                job.warn(f"'{mesh.name}' 的循环数与投影结果不符，排布未落地")
                continue
            self._swap_uv_layers(mesh, settings.source_uv, settings.target_uv)

    def _destination_mesh(self, job, entry, settings):
        """UV 层模式就落在自己身上；世界投影模式落回展平物体的来源物体。"""
        if settings.target_space == 'UV_LAYER':
            return entry.mesh

        origin_name = entry.obj.get(SOURCE_OBJECT_PROP)
        if not origin_name:
            job.warn(f"'{entry.obj.name}' 没有记录来源物体，排布无处可落"
                     f"（它得由「网格转UV」生成）")
            return None
        origin = bpy.data.objects.get(origin_name)
        if origin is None or origin.type != 'MESH':
            job.warn(f"'{entry.obj.name}' 的来源物体 '{origin_name}' 已不存在")
            return None
        if len(origin.data.loops) != entry.loop_uv.shape[0]:
            job.warn(f"'{entry.obj.name}' 与来源 '{origin_name}' 的循环数不符")
            return None
        return origin.data

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
