import bpy
import math

# 遍历场景中所有已选中的对象
selected_objects = [obj for obj in bpy.data.objects if obj.select_get()]

# 计算每个对象的维度向量长度，并存储在列表中
lengths = [(obj, math.sqrt(obj.dimensions.x**2 + obj.dimensions.y**2 + obj.dimensions.z**2)) for obj in selected_objects]

# 根据长度对这个列表进行排序
lengths.sort(key=lambda x: x[1])

# 分割列表，只取消选择一半的对象
mid_index = len(lengths) // 2
to_deselect = set()

# 找到共享网格数据的所有对象
mesh_links = {}
for obj, _ in lengths:
    mesh_name = obj.data.name if obj.data else None
    if mesh_name:
        if mesh_name not in mesh_links:
            mesh_links[mesh_name] = []
        mesh_links[mesh_name].append(obj)

# 将要取消选择的对象以及所有共享相同网格数据的对象加入到集合中
for obj, _ in lengths[:mid_index]:
    if obj.data.name in mesh_links:
        to_deselect.update(mesh_links[obj.data.name])

# 取消选择集合中的所有对象
for obj in to_deselect:
    obj.select_set(False)

print("Selected half of the objects based on dimension vector length and deselected any linked by shared mesh data.")
