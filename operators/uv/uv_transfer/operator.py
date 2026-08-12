"""UV 重定向算子：把源 UV 层上的颜色，按目标 UV 层的排布重新出图。

算子只负责校验、分派、写盘与 UV 层收尾；颜色从哪来由 providers 里的 descriptor 决定。
"""

import bpy
import numpy as np

from . import image_bind
from . import providers


class TransferJob:
    """一次重定向的全部输入，以及给 provider 用的汇报通道。"""

    def __init__(self, operator, context, meshes, objects):
        self.operator = operator
        self.context = context
        self.settings = context.scene.shiyume_uv_transfer
        self.meshes = meshes
        self.objects = objects
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
    """把源 UV 层上的颜色按目标 UV 层的排布重新出图（重采样已有贴图 或 烘焙最终颜色）"""

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

        if not settings.source_uv or not settings.target_uv:
            self.report({'ERROR'}, "请先指定源 UV 与目标 UV")
            return {'CANCELLED'}
        if settings.source_uv == settings.target_uv:
            self.report({'ERROR'}, "源 UV 与目标 UV 不能是同一层")
            return {'CANCELLED'}
        if (settings.save_to_disk and settings.output_dir.startswith("//")
                and not bpy.data.filepath):
            self.report({'ERROR'}, "输出目录是相对路径，请先保存 .blend 或改用绝对路径")
            return {'CANCELLED'}

        meshes, objects, skipped = self._collect(context, settings)
        if not objects:
            self.report({'ERROR'},
                        f"选中物体里没有同时具备 '{settings.source_uv}' "
                        f"与 '{settings.target_uv}' 的网格")
            return {'CANCELLED'}

        job = TransferJob(self, context, meshes, objects)
        source = providers.get(settings.color_source)

        selection = [obj for obj in context.selected_objects]
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
            self._swap_uv_layers(meshes, settings.source_uv, settings.target_uv)

        message = f"{source.label}完成 — {len(result['outputs'])} 张贴图"
        if saved:
            message += f"，已写入 {settings.output_dir}"
        self.report({'INFO'}, message)
        if skipped:
            self.report({'WARNING'}, f"缺少指定 UV 层，已跳过: {', '.join(skipped)}")
        return {'FINISHED'}

    def _collect(self, context, settings):
        """收集同时具备两个 UV 层的选中网格；网格数据去重，物体单独留着给烘焙用。"""
        meshes = {}
        objects = []
        skipped = []
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            mesh = obj.data
            if (settings.source_uv not in mesh.uv_layers
                    or settings.target_uv not in mesh.uv_layers):
                skipped.append(obj.name)
                continue
            meshes[mesh.name] = mesh
            objects.append(obj)
        return meshes, objects, skipped

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

    def _swap_uv_layers(self, meshes, source_uv, target_uv):
        """对调两层的 UV 数据：源层拿到新布局，目标层接住旧布局。

        两个层、两个名字都原样保留——按名绑定的节点继续生效，槽位顺序不变，
        旧布局也还在，再执行一次就换回去。
        """
        for mesh in meshes.values():
            source_attribute = mesh.attributes.get(source_uv)
            target_attribute = mesh.attributes.get(target_uv)
            if source_attribute is None or target_attribute is None:
                continue

            count = len(source_attribute.data) * 2
            source_values = np.empty(count, dtype=np.float32)
            target_values = np.empty(count, dtype=np.float32)
            source_attribute.data.foreach_get("vector", source_values)
            target_attribute.data.foreach_get("vector", target_values)
            source_attribute.data.foreach_set("vector", target_values)
            target_attribute.data.foreach_set("vector", source_values)
            mesh.update()
