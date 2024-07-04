import bpy
import math

# 设定的长度阈值（平方根长度小于1米）
length_threshold = 1.0

# 遍历场景中的所有对象
for obj in bpy.data.objects:
    # 计算对象的维度向量长度
    dimensions = obj.dimensions  # 获取对象的尺寸（宽，高，深）
    length = math.sqrt(dimensions.x**2 + dimensions.y**2 + dimensions.z**2)
    
    # 检查长度是否小于阈值
    if length < length_threshold:
        obj.select_set(True)  # 选择该对象
    else:
        obj.select_set(False)  # 不选择该对象

print("Selection updated for objects with dimension vector length less than 1m.")
