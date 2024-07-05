import bpy

# 确保在运行脚本之前选择了网格对象和骨骼
obj = bpy.context.object
if not obj or obj.type != 'MESH':
    raise ValueError("Selected object is not a mesh")

# 获取骨骼名称集合
armature = obj.find_armature()
if not armature:
    raise ValueError("No armature associated with the mesh")
bone_names = set(bone.name for bone in armature.data.bones)

# 收集所有不与骨骼名称匹配的顶点组
groups_to_remove = [group.index for group in obj.vertex_groups if group.name not in bone_names]

# 逆向遍历确保在删除过程中不会打乱顶点组索引
for idx in reversed(groups_to_remove):
    obj.vertex_groups.remove(obj.vertex_groups[idx])

print(f"Removed {len(groups_to_remove)} vertex groups not matching any bone")
