"""头发程序化生成的算子：开始预览、编辑模式选面做局部层、换随机种子、去掉局部层、刷新发片坐标、取消、烘焙。

预览层是带预览节点组的自发光材质，参数在节点组里程序实例的输入上（侧栏画出来），调整即时可见；基础层共用一个预览节点组，局部层各有自己的；
烘焙把所有层按各自的参数写进贴图落点，再把预览材质、网格上的预览属性、预览节点组与程序节点组全部删掉，槽与面还原。
"""

import random
from collections import Counter

import bmesh
import bpy

from ..endfield_target import importer
from ..endfield_target import shader_link
from ..endfield_target import targets
from . import generation
from . import layers
from . import palette
from . import preview_attributes
from . import preview_material
from . import procedural

SEED_MAXIMUM = 16777215
LOCAL_SUFFIX = "_局部"
PREVIEW_SUFFIX = "_预览"


def _random_seed():
    return random.randrange(SEED_MAXIMUM + 1)


def _selected_meshes(context):
    return [obj for obj in context.selected_objects if obj.type == 'MESH']


def _discard_layers():
    """把所有带预览层的物体还原，删掉预览材质、网格上的预览属性与程序节点组。"""
    for obj in layers.objects_with_layers():
        layers.restore(obj)
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            preview_attributes.remove(obj)
    for material in layers.all_layers():
        bpy.data.materials.remove(material)
    preview_material.remove_unused_groups()


class SHIYUME_OT_HairPreviewStart(bpy.types.Operator):
    """给选中的头发物体的每个材质槽换上程序预览材质（自发光，所见即烘焙的内容），参数在侧栏随时调。
    头发、羽毛这些不同材质的基础层共用同一套参数，发色与纹路一致；要换发色就编辑模式选面做局部层。
    要求发片是「修复头发展开」那种规则的四边形长条 UV 孤岛；原材质不丢，取消或烘焙时还原"""
    bl_idname = "shiyume.hair_preview_start"
    bl_label = "开始预览"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        options = context.scene.shiyume_hair_preview
        shared = layers.shared_group()
        if shared is None:
            parameters = procedural.default_parameters()
            parameters["seed"] = _random_seed()
            parameters["showNormal"] = options.show_normal
            try:
                shared = preview_material.create_group(parameters)
            except ValueError as error:
                self.report({'ERROR'}, str(error))
                return {'CANCELLED'}
        made = {}
        objects = 0
        for obj in _selected_meshes(context):
            candidates = []
            for slot in obj.material_slots:
                part = importer.other_part(slot.material) if slot.material is not None else None
                if part is not None:
                    self.report({'WARNING'}, "材质 '%s' 是导入器的 %s 部件，不是头发，没有动它" % (slot.material.name, part or "未命名"))
                elif slot.material is not None and not layers.is_layer(slot.material):
                    candidates.append(slot)
            if not candidates and not any(layers.is_layer(slot.material) for slot in obj.material_slots):
                self.report({'WARNING'}, "物体 '%s' 没有可预览的材质，跳过" % obj.name)
                continue
            try:
                preview_attributes.write(obj, context.scene, options.uv_layer)
            except ValueError as error:
                self.report({'WARNING'}, str(error))
                continue
            for slot in candidates:
                original = slot.material
                if original not in made:
                    made[original] = preview_material.create(original.name + PREVIEW_SUFFIX, original, None, shared)
                slot.material = made[original]
            objects += 1
        if not objects:
            preview_material.remove_unused_groups()
            self.report({'ERROR'}, "没有可预览的头发物体")
            return {'CANCELLED'}
        if options.switch_viewport:
            shader_link.show_material_preview(context)
        self.report({'INFO'}, "%d 个物体、%d 张材质开始预览；在侧栏调参数，编辑模式选面可以做局部层" % (objects, len(made)))
        return {'FINISHED'}


class SHIYUME_OT_HairPreviewLocal(bpy.types.Operator):
    """编辑模式里选中一批面，给它们单独做一层预览材质（参数先拷当前层的，换个种子），用来挑染或局部换纹路。
    选中的面要来自同一个预览层；烘焙时这些面按自己这一层的参数写，其余面不受影响"""
    bl_idname = "shiyume.hair_preview_local"
    bl_label = "选中的面做局部层"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and layers.active_layer(context) is not None

    def execute(self, context):
        obj = context.active_object
        slots = layers.selected_face_slots(obj)
        if not slots:
            self.report({'ERROR'}, "先选中要单独做一层的面")
            return {'CANCELLED'}
        sources = {obj.material_slots[index].material for index in slots if index < len(obj.material_slots)}
        if len(sources) != 1 or not layers.is_layer(next(iter(sources))):
            self.report({'ERROR'}, "选中的面要全部来自同一个预览层")
            return {'CANCELLED'}
        source = next(iter(sources))
        parameters = procedural.parameters_of(layers.generator_of(source))
        parameters["seed"] = _random_seed()
        parameters["bake"] = True
        created = preview_material.create(layers.original_of(source).name + LOCAL_SUFFIX, layers.original_of(source), obj, preview_material.create_group(parameters))
        obj.data.materials.append(created)
        index = len(obj.material_slots) - 1
        bm = bmesh.from_edit_mesh(obj.data)
        for face in bm.faces:
            if face.select and not face.hide:
                face.material_index = index
        bmesh.update_edit_mesh(obj.data)
        obj.active_material_index = index
        self.report({'INFO'}, "已做局部层 '%s'，在侧栏调它的参数" % created.name)
        return {'FINISHED'}


class SHIYUME_OT_HairPreviewDropLocal(bpy.types.Operator):
    """去掉当前的局部层：它的面回到所属的预览层，局部层的材质与槽删掉"""
    bl_idname = "shiyume.hair_preview_drop_local"
    bl_label = "去掉局部层"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        layer = layers.active_layer(context)
        return context.mode == 'OBJECT' and layer is not None and layers.is_local(layer)

    def execute(self, context):
        obj = context.active_object
        layer = layers.active_layer(context)
        layers.release_local(obj, layers.slot_of(obj, layer))
        bpy.data.materials.remove(layer)
        return {'FINISHED'}


class SHIYUME_OT_HairPreviewRandomSeed(bpy.types.Operator):
    """给当前层换一个随机种子，纹路与颜色的细微变化都跟着换；开着「随机配色」时发色（开了渐变发梢色就连发梢色）也从参考头发的配色里换一套，同一个种子给同一套"""
    bl_idname = "shiyume.hair_preview_random_seed"
    bl_label = "随机种子"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        layer = layers.active_layer(context)
        return layer is not None and layers.generator_of(layer) is not None

    def execute(self, context):
        generator = layers.generator_of(layers.active_layer(context))
        seed = _random_seed()
        values = {"seed": seed}
        if context.scene.shiyume_hair_preview.random_color:
            values.update(palette.random_scheme(random.Random(seed), procedural.parameters_of(generator)["useTip"] > 0.5))
        procedural.apply_parameters(generator, values)
        return {'FINISHED'}


class SHIYUME_OT_HairPreviewRefresh(bpy.types.Operator):
    """重新量发片并刷新预览用的网格属性：改了网格、UV 或「UV 层」之后用"""
    bl_idname = "shiyume.hair_preview_refresh"
    bl_label = "刷新发片坐标"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(layers.all_layers())

    def execute(self, context):
        options = context.scene.shiyume_hair_preview
        for obj in layers.objects_with_layers():
            preview_attributes.write(obj, context.scene, options.uv_layer)
        return {'FINISHED'}


class SHIYUME_OT_HairPreviewCancel(bpy.types.Operator):
    """取消预览：材质槽与面还原成预览之前的样子，预览材质、网格属性、程序节点组全部删掉，不写任何贴图"""
    bl_idname = "shiyume.hair_preview_cancel"
    bl_label = "取消预览"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(layers.all_layers())

    def execute(self, context):
        _discard_layers()
        return {'FINISHED'}


class SHIYUME_OT_HairPreviewBake(bpy.types.Operator):
    """把所有预览层按各自的参数烘焙进贴图：法线写分离法线贴图的 R、G（B、A 不动），颜色写 BaseMap，别的像素原样保留；
    然后删掉全部预览材质、网格属性与程序节点组。装了 RuriRipperImporter 就按它的头发着色栈新建（或更新）材质球挂上去，原材质保留；
    没装就写「材质名_Normal.png」「材质名_BaseColor.png」并接到 Principled BSDF"""
    bl_idname = "shiyume.hair_preview_bake"
    bl_label = "烘焙并清理"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(layers.all_layers())

    def execute(self, context):
        scene = context.scene
        options = scene.shiyume_hair_preview
        target_options = scene.shiyume_endfield_target
        settings = targets.Settings(target_options.output_dir, int(target_options.resolution), target_options.variant.strip(),
                                               options.generate_color)
        problems = []
        batches, generations, rejected = generation.collect(layers.objects_with_layers(), scene, options.uv_layer, settings, problems)
        if rejected:
            reasons = Counter()
            for reason, face_count in rejected:
                reasons[reason] += face_count
            self.report({'WARNING'}, "有 %d 个不是规则四边形长条的孤岛，颜色按 UV 包围盒近似生成，法线不生成：%s" % (
                len(rejected), "；".join("%s（共 %d 个面）" % item for item in reasons.most_common(3))))
        written = [generation.write(batch, target_options.margin, generations, settings, problems) for batch in batches.values() if batch is not None]
        written = [item for item in written if item.texels]
        if not written:
            for problem in problems:
                self.report({'WARNING'}, problem)
            self.report({'ERROR'}, "没有写出任何贴图，预览还留着")
            return {'CANCELLED'}
        _discard_layers()
        messages = []
        flat_shown = False
        for item in written:
            problems.extend(item.batch.target.notes())
            finished, preview = item.batch.target.finish(item.batch.bindings)
            messages.extend(finished)
            if preview is not None and preview[1] is not None:
                shader_link.activate(*preview)
                if item.mean_color is not None:
                    shader_link.tint(preview[0], item.mean_color)
                if options.switch_viewport and not flat_shown:
                    flat_shown = shader_link.show_flat(context)
        for problem in problems:
            self.report({'WARNING'}, problem)
        self.report({'INFO'}, "烘焙了 %d 个像素，预览材质已清理；%s" % (sum(item.texels for item in written), "；".join(messages)))
        return {'FINISHED'}
