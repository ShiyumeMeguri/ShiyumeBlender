import bpy
import bmesh


class SHIYUME_OT_VGSmoothMerge(bpy.types.Operator):
    """按顶点组平滑伪合并顶点：
    对名为 'Edge' 顶点组中权重大于 0.1 的两两顶点，若距离小于阈值（默认 0.001m），
    则把两个顶点都移动到它们的中点位置（伪合并，不真正连接）。
    用于让两条边'看起来合并'但仍保持两个顶点。"""
    bl_idname = "shiyume.vg_smooth_merge"
    bl_label = "按顶点组平滑伪合并"
    bl_options = {'REGISTER', 'UNDO'}

    distance_threshold: bpy.props.FloatProperty(name="距离阈值", default=0.001, min=0.0, precision=5)
    vertex_group_name: bpy.props.StringProperty(name="顶点组名", default="Edge")
    min_weight: bpy.props.FloatProperty(name="最小权重", default=0.1, min=0.0, max=1.0)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        bpy.ops.object.mode_set(mode='EDIT')

        obj = context.edit_object
        me = obj.data

        bm = bmesh.from_edit_mesh(me)

        vertex_group_index = obj.vertex_groups.find(self.vertex_group_name)
        if vertex_group_index == -1:
            self.report({'WARNING'}, f"未找到名为'{self.vertex_group_name}'的顶点组。")
            bpy.ops.object.mode_set(mode='OBJECT')
            return {'CANCELLED'}

        vg = obj.vertex_groups[vertex_group_index]

        vertex_move_targets = {}

        def get_vertex_weight(vertex, group_index):
            for g in vertex.groups:
                if g.group == group_index:
                    return g.weight
            return 0.0

        for vert1 in bm.verts:
            for vert2 in bm.verts:
                if vert1 != vert2:
                    weight1 = get_vertex_weight(obj.data.vertices[vert1.index], vertex_group_index)
                    weight2 = get_vertex_weight(obj.data.vertices[vert2.index], vertex_group_index)
                    if weight1 > self.min_weight and weight2 > self.min_weight:
                        distance = (vert1.co - vert2.co).length
                        if distance < self.distance_threshold:
                            target_position = (vert1.co + vert2.co) * 0.5
                            vertex_move_targets[vert1] = target_position
                            vertex_move_targets[vert2] = target_position

        for vert, target in vertex_move_targets.items():
            vert.co = target

        bmesh.update_edit_mesh(me)
        bpy.ops.object.mode_set(mode='OBJECT')

        return {'FINISHED'}
