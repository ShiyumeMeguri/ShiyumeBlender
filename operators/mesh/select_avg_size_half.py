import bpy
import math


class SHIYUME_OT_SelectAvgSizeHalf(bpy.types.Operator):
    """按尺寸均值减选：计算所有选中物体的对角线长度并排序，
    取消选择较小的那一半，同时连带取消选择所有共享相同网格数据的对象。
    用于在大量分散物体中快速保留较大者用于检查。"""
    bl_idname = "shiyume.select_avg_size_half"
    bl_label = "按平均大小减选"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = [obj for obj in bpy.data.objects if obj.select_get()]

        lengths = [
            (obj, math.sqrt(obj.dimensions.x ** 2 + obj.dimensions.y ** 2 + obj.dimensions.z ** 2))
            for obj in selected_objects
        ]

        lengths.sort(key=lambda x: x[1])

        mid_index = len(lengths) // 2
        to_deselect = set()

        mesh_links = {}
        for obj, _ in lengths:
            mesh_name = obj.data.name if obj.data else None
            if mesh_name:
                if mesh_name not in mesh_links:
                    mesh_links[mesh_name] = []
                mesh_links[mesh_name].append(obj)

        for obj, _ in lengths[:mid_index]:
            if obj.data and obj.data.name in mesh_links:
                to_deselect.update(mesh_links[obj.data.name])

        for obj in to_deselect:
            obj.select_set(False)

        return {'FINISHED'}
