"""描边平滑法线的算子：烘焙、核对、清除。设置在 Scene 的 shiyume_endfield_outline 上，侧栏 EndField 标签里点。

游戏的反壳描边把 UV2 当切线空间平滑法线（XY，Z 现算）来外扩。游戏网格里的 UV2 是工具烘焙进去的，不是手做的；自己的网格没有它，
描边只能沿表面法线外扩，硬边处会裂开。烘焙把平滑法线按每个角自己的切线框写进 UV2，导入器的描边读到的就和游戏的网格一样。
"""

import bpy

from . import bake

DEGREES = "%.1f°"


def _targets(context, options):
    return [obj for obj in context.selected_objects if obj.type == 'MESH' and obj is not options.proxy]


def _store(options, lines):
    options.report.clear()
    for line in lines:
        options.report.add().text = line


def _outcome_line(obj, outcome):
    text = "%s：%d 个角，平滑法线偏离角法线平均 %s、九成在 %s 内" % (
        obj.name, outcome.corners, DEGREES % outcome.tilt_mean, DEGREES % outcome.tilt_p90)
    if outcome.behind:
        text += "，%d 个角翻到面背后已收缩" % outcome.behind
    if outcome.unsmoothed:
        text += "，%d 个角没法平均、用了角法线" % outcome.unsmoothed
    if outcome.created:
        text += "，新建了 UV 层"
    return text


class SHIYUME_OT_EndfieldOutlineBake(bpy.types.Operator):
    """把平滑法线按每个角自己的切线框烘焙进 UV 层（默认 UV2）：XY 存进去，Z 由着色器现算。选中的网格物体都烘，已有这一层就覆盖；
    渲染用的 UV 层、网格形状、法线都不动"""
    bl_idname = "shiyume.endfield_outline_bake"
    bl_label = "烘焙描边平滑法线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        options = context.scene.shiyume_endfield_outline
        depsgraph = context.evaluated_depsgraph_get()
        lines = []
        problems = []
        for obj in _targets(context, options):
            try:
                outcome = bake.bake_object(obj, options, depsgraph)
            except bake.BakeError as error:
                problems.append("物体 '%s'：%s" % (obj.name, error))
                continue
            lines.append(_outcome_line(obj, outcome))
        _store(options, lines + problems)
        for problem in problems:
            self.report({'WARNING'}, problem)
        if not lines:
            self.report({'ERROR'}, "没有烘焙任何物体")
            return {'CANCELLED'}
        self.report({'INFO'}, "烘焙了 %d 个物体的描边平滑法线，写进 UV 层 '%s'" % (len(lines), options.layer))
        return {'FINISHED'}


class SHIYUME_OT_EndfieldOutlineVerify(bpy.types.Operator):
    """核对选中物体 UV 层里烘焙的值：按着色器的解码还原，和现在的平滑法线来源重新算的结果比。烘焙之后动过网格或来源就会露出差，重新烘焙"""
    bl_idname = "shiyume.endfield_outline_verify"
    bl_label = "核对"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        options = context.scene.shiyume_endfield_outline
        depsgraph = context.evaluated_depsgraph_get()
        lines = []
        problems = []
        for obj in _targets(context, options):
            try:
                result = bake.verify_object(obj, options, depsgraph)
            except bake.BakeError as error:
                problems.append("物体 '%s'：%s" % (obj.name, error))
                continue
            lines.append("%s：%d 个角，解码后与来源相差中位 %s、最大 %s" % (
                obj.name, result.corners, DEGREES % result.error_median, DEGREES % result.error_max))
        _store(options, lines + problems)
        for problem in problems:
            self.report({'WARNING'}, problem)
        if not lines:
            self.report({'ERROR'}, "没有核对任何物体")
            return {'CANCELLED'}
        return {'FINISHED'}


class SHIYUME_OT_EndfieldOutlineClear(bpy.types.Operator):
    """删掉选中物体上写入的 UV 层（描边会退回沿表面法线外扩）"""
    bl_idname = "shiyume.endfield_outline_clear"
    bl_label = "清除"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        options = context.scene.shiyume_endfield_outline
        removed = []
        problems = []
        for obj in _targets(context, options):
            try:
                if bake.clear_object(obj, options):
                    removed.append(obj.name)
            except bake.BakeError as error:
                problems.append("物体 '%s'：%s" % (obj.name, error))
        _store(options, ["%s：删掉了 UV 层 '%s'" % (name, options.layer) for name in removed] + problems)
        for problem in problems:
            self.report({'WARNING'}, problem)
        self.report({'INFO'}, "删掉了 %d 个物体的 UV 层 '%s'" % (len(removed), options.layer))
        return {'FINISHED'}
