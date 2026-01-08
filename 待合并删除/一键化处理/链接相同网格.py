import bpy

def cache_selected_objects():
    """缓存选中对象的顶点数、局部尺寸和材质"""
    selected_objects = bpy.context.selected_objects
    cache = {}

    for obj in selected_objects:
        if obj.type == 'MESH':
            # 获取顶点数和局部尺寸
            vertex_count = len(obj.data.vertices)
            # 计算局部尺寸时考虑缩放的绝对值
            dimensions = tuple(d / abs(s) for d, s in zip(obj.dimensions, obj.scale))  
            # 获取材质
            material = obj.active_material

            cache[obj] = {
                'vertex_count': vertex_count,
                'dimensions': dimensions,
                'material': material
            }
            print(f"Cached: {obj.name}, Vertex Count: {vertex_count}, Local Dimensions: {dimensions}, Material: {material.name if material else 'None'}")

    if not cache:
        print("No mesh objects selected.")
    
    return cache

def dimensions_match(dim1, dim2, tolerance=0.001):
    """检查两个维度是否在误差范围内匹配"""
    return all(abs(a - b) <= tolerance for a, b in zip(dim1, dim2))

def replace_data_blocks_with_cached(cache):
    """遍历所有对象，匹配顶点数、局部尺寸和材质，相同则替换数据块"""
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
        # 不包含选中?
        #if obj not in cache and obj.type == 'MESH':
            # 获取顶点数和局部尺寸
            vertex_count = len(obj.data.vertices)
            # 计算局部尺寸时考虑缩放的绝对值
            dimensions = tuple(d / abs(s) for d, s in zip(obj.dimensions, obj.scale))  
            # 获取材质
            material = obj.active_material

            for cached_obj, cached_data in cache.items():
                if (vertex_count == cached_data['vertex_count'] and
                    dimensions_match(dimensions, cached_data['dimensions']) and
                    material == cached_data['material']):
                    # 替换数据块
                    obj.data = cached_obj.data
                    print(f"Replaced: {obj.name} with {cached_obj.name}")
                    break
            else:
                print(f"No match found for: {obj.name}")

# 运行脚本
cached_objects = cache_selected_objects()
if cached_objects:
    replace_data_blocks_with_cached(cached_objects)
else:
    print("No objects were cached for replacement.")
