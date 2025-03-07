import bpy

# 记录已经处理过的网格数据，避免重复烘焙
processed_meshes = set()

# 定义因子：对象 scale 放大 100 倍，顶点坐标缩放 0.01
scale_factor = 100
bake_factor = 0.01

# 遍历场景中所有对象
for obj in bpy.context.scene.objects:
    # 如果对象有 scale 属性，则更新它
    if hasattr(obj, 'scale'):
        obj.scale = obj.scale * scale_factor
        
    # 如果对象是 Mesh 类型，则烘焙网格顶点数据
    if obj.type == 'MESH':
        # 如果该网格还未被处理过，则进行顶点坐标缩放
        if obj.data not in processed_meshes:
            for v in obj.data.vertices:
                v.co *= bake_factor
            # 记录已经处理的网格数据
            processed_meshes.add(obj.data)

print("已将全局0.01缩放烘焙到网格数据中，对象自身的缩放更新为原来的100倍，视觉上保持不变。")
