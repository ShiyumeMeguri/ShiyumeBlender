import bpy
import math

def arrange_objects_by_size_similarity():
    # 获取选中的对象
    selected_objects = bpy.context.selected_objects
    
    if not selected_objects:
        print("没有选中任何对象")
        return
    
    # 定义排序函数，基于 x, y, z 维度的总和
    def size_key(obj):
        dimensions = obj.dimensions
        return math.sqrt(dimensions.x**2 + dimensions.y**2 + dimensions.z**2)
    
    # 对对象列表进行排序
    sorted_objects = sorted(selected_objects, key=size_key)
    
    # 最小间距，可以根据需要调整
    min_margin = 0.1
    
    # 计算行列数（尽量接近正方形）
    num_objects = len(sorted_objects)
    grid_size = math.ceil(math.sqrt(num_objects))
    
    # 初始化当前行列的X和Y坐标
    current_x = 0.0
    current_y = 0.0
    current_row_max_height = 0.0
    
    for index, obj in enumerate(sorted_objects):
        # 获取对象的最大维度
        max_dimension = max(obj.dimensions.x, obj.dimensions.y)
        
        # 如果在当前行放不下，换行
        if index % grid_size == 0 and index != 0:
            current_x = 0.0
            current_y += current_row_max_height + min_margin
            current_row_max_height = 0.0
        
        # 设置对象的位置（Z 方向不变）
        obj.location.x = current_x + max_dimension / 2.0
        obj.location.y = current_y + max_dimension / 2.0
        
        # 更新当前行的最大高度
        if max_dimension > current_row_max_height:
            current_row_max_height = max_dimension
        
        # 更新下一个对象的X位置
        current_x += max_dimension + min_margin

# 执行排列函数
arrange_objects_by_size_similarity()
