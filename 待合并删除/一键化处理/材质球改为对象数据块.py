# 比如同一个网格有多个材质变体的时候(换颜色等) 就不能用link了 需要把材质球的数据块改为object单位才行

import bpy

# 遍历场景中的所有网格对象
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        # 遍历对象的所有材质槽
        for i in range(len(obj.material_slots)):
            # 获取当前材质槽
            slot = obj.material_slots[i]
            
            # 记录当前材质
            original_material = slot.material
            
            # 将材质槽的链接方式设置为 'OBJECT'
            slot.link = 'OBJECT'
            
            # 确保材质重新分配成功
            if original_material:
                obj.material_slots[i].material = original_material

print("所有网格对象的材质槽链接方式已设置为 'OBJECT'，并重新指定材质。")
