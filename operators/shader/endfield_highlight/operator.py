"""高光椭球的算子：创建、开始与停止实时预览、烘焙。设置在 Scene 的 shiyume_endfield_highlight 上，侧栏 EndField 标签里点。

椭球是头发高光法线的高模：头发每个点的高光法线取椭球上离它最近的点的平滑法线。烘焙把它写进分离法线贴图的 B、A 通道，R、G 不动。
"""

from collections import namedtuple

import bpy
import numpy as np

from ...uv.uv_transfer import mesh_bind
from ..endfield_target import importer
from ..endfield_target import occupancy
from ..endfield_target import shader_link
from ..endfield_target import targets
from . import bake
from . import ellipsoid
from . import estimate
from . import session

Batch = namedtuple("Batch", ("target", "sources", "bindings"))

NEEDS_IMPORTER = "高光椭球只服务 RuriRipperImporter 导入的头发材质，先装好并载入头发"
NEEDS_HAIR = "先选中带导入器头发材质的物体（或之前预览过的头发物体）"
NEEDS_ELLIPSOID = "还没有高光椭球，先点创建"


def _selected_hair(context):
    return [obj for obj in context.selected_objects if obj.type == 'MESH' and session.hair_materials(obj)]


def _chosen_hair(context, options):
    return _selected_hair(context) or session.hair_objects(options)


def _store_hair(options, objects):
    options.hair.clear()
    for obj in objects:
        options.hair.add().obj = obj


def _world_points(objects, depsgraph):
    points = []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        local = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", local)
        evaluated.to_mesh_clear()
        matrix = np.array(obj.matrix_world, dtype=np.float64)
        points.append(local.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3])
    return np.concatenate(points)


def _start_preview(operator, context, options):
    options.previewing = True
    unwired = session.reconcile()
    for name in unwired:
        operator.report({'WARNING'}, "材质 '%s' 里找不到接着的分离法线贴图节点，没能接上预览" % name)
    if options.previewing and options.switch_viewport:
        shader_link.show_material_preview(context)
    return options.previewing


class SHIYUME_OT_EndfieldHighlightCreate(bpy.types.Operator):
    """按选中头发的形状估一个合适的高光椭球并开始实时预览；已经有椭球时把它重置到估算的位置。
    椭球是低模加细分修改器、只显示网格线，进物体模式移动、旋转、缩放它（或进编辑模式改外壳）来调高光，头发上的高光实时跟着变"""
    bl_idname = "shiyume.endfield_highlight_create"
    bl_label = "创建高光椭球并预览"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        if not importer.available():
            self.report({'ERROR'}, NEEDS_IMPORTER)
            return {'CANCELLED'}
        options = context.scene.shiyume_endfield_highlight
        hair = _selected_hair(context)
        if not hair:
            self.report({'ERROR'}, NEEDS_HAIR)
            return {'CANCELLED'}
        placement = estimate.place(_world_points(hair, context.evaluated_depsgraph_get()))
        if ellipsoid.usable(context.scene, options.ellipsoid):
            ellipsoid.fit(context, options.ellipsoid, placement)
        else:
            collection = hair[0].users_collection[0] if hair[0].users_collection else context.scene.collection
            options.ellipsoid = ellipsoid.create(context, placement, collection)
        _store_hair(options, hair)
        if not _start_preview(self, context, options):
            self.report({'ERROR'}, "椭球已摆好，但实时预览没能开始")
            return {'CANCELLED'}
        self.report({'INFO'}, "高光椭球 '%s' 已摆好，头发 %d 个物体在实时预览" % (options.ellipsoid.name, len(hair)))
        return {'FINISHED'}


class SHIYUME_OT_EndfieldHighlightPreview(bpy.types.Operator):
    """开始实时预览：选中的头发（没选就用上次预览的）的高光法线实时取椭球的法线，不动贴图"""
    bl_idname = "shiyume.endfield_highlight_preview"
    bl_label = "开始预览"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and ellipsoid.usable(context.scene, context.scene.shiyume_endfield_highlight.ellipsoid)

    def execute(self, context):
        options = context.scene.shiyume_endfield_highlight
        hair = _chosen_hair(context, options)
        if not hair:
            self.report({'ERROR'}, NEEDS_HAIR)
            return {'CANCELLED'}
        _store_hair(options, hair)
        if not _start_preview(self, context, options):
            self.report({'ERROR'}, "实时预览没能开始")
            return {'CANCELLED'}
        return {'FINISHED'}


class SHIYUME_OT_EndfieldHighlightStop(bpy.types.Operator):
    """停止实时预览：摘掉头发上的预览修改器和材质里的预览节点，高光回到贴图里的样子；椭球留着"""
    bl_idname = "shiyume.endfield_highlight_stop"
    bl_label = "停止预览"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.shiyume_endfield_highlight.previewing

    def execute(self, context):
        session.stop(context.scene)
        return {'FINISHED'}


class SHIYUME_OT_EndfieldHighlightBake(bpy.types.Operator):
    """把椭球的高光法线烘焙进头发的分离法线贴图的 B、A 通道（R、G 不动，贴图里别的像素原样保留），停止实时预览。
    装了 RuriRipperImporter 就和头发程序化生成一样新建（或更新）一张按它的头发着色栈编出来的材质球挂上去，原材质保留"""
    bl_idname = "shiyume.endfield_highlight_bake"
    bl_label = "烘焙高光法线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and ellipsoid.usable(context.scene, context.scene.shiyume_endfield_highlight.ellipsoid)

    @staticmethod
    def _assign(obj, uv_name, triangles, surface, settings, batches, problems):
        slots = obj.material_slots
        for slot in np.unique(triangles.slot):
            index = min(int(slot), len(slots) - 1) if len(slots) else -1
            material = slots[index].material if index >= 0 else None
            if material is None:
                continue
            key = targets.key_of(material, settings)
            if key not in batches:
                try:
                    batches[key] = Batch(targets.resolve(material, settings), [], [])
                except targets.TargetError as error:
                    problems.append(str(error))
                    batches[key] = None
            batch = batches[key]
            if batch is None:
                continue
            batch.sources.append(bake.Source(bake.select(triangles, triangles.slot == slot), surface))
            batch.bindings.append(targets.Binding(obj, index, material, uv_name, uv_name))

    def execute(self, context):
        if not importer.available():
            self.report({'ERROR'}, NEEDS_IMPORTER)
            return {'CANCELLED'}
        scene = context.scene
        options = scene.shiyume_endfield_highlight
        target_options = scene.shiyume_endfield_target
        hair = _chosen_hair(context, options)
        if not hair:
            self.report({'ERROR'}, NEEDS_HAIR)
            return {'CANCELLED'}
        settings = targets.Settings(target_options.output_dir, int(target_options.resolution), target_options.variant.strip(), False)
        depsgraph = context.evaluated_depsgraph_get()
        batches = {}
        generations = {}
        problems = []
        for obj in hair:
            uv_name = mesh_bind.render_uv_name(obj.data)
            if not uv_name:
                problems.append("物体 '%s' 没有 UV 层，跳过" % obj.name)
                continue
            faces = np.ones(len(obj.data.polygons), dtype=bool)
            generations[obj.name] = occupancy.Generation(uv_name, faces, faces)
            self._assign(obj, uv_name, bake.triangles_of(obj, depsgraph, uv_name), bake.surface_of(options.ellipsoid, obj, depsgraph),
                         settings, batches, problems)

        fields = []
        for batch in batches.values():
            if batch is None:
                continue
            width, height = batch.target.normal.size
            field = bake.field_of(batch.sources, width, height)
            if not field.covered.any():
                problems.append("'%s' 上没有面落进贴图范围" % batch.target.normal.name)
                continue
            fields.append((batch, field, occupancy.protected(batch.target.key, width, height, generations, settings, False)))

        session.stop(scene)
        messages = []
        texel_total = 0
        for batch, field, blocked in fields:
            target = batch.target
            target.normal.paint(field.values, field.covered, target.highlight_channels, None, target_options.margin, blocked)
            texel_total += int(field.covered.sum())
            problems.extend(target.notes())
            finished, _preview = target.finish(batch.bindings)
            messages.extend(finished)
        for problem in problems:
            self.report({'WARNING'}, problem)
        if not messages:
            self.report({'ERROR'}, "没有写出任何贴图")
            return {'CANCELLED'}
        self.report({'INFO'}, "烘焙了 %d 个像素的高光法线，预览已停止；%s" % (texel_total, "；".join(messages)))
        return {'FINISHED'}
