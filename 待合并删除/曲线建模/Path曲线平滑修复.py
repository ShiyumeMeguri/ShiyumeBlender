import bpy

# 确保在执行此脚本之前已经选择了一个曲线对象
obj = bpy.context.object

if obj and obj.type == 'CURVE':
    for spline in obj.data.splines:
        # 1. 强制转为 NURBS
        if spline.type != 'NURBS':
            spline.type = 'NURBS'
        
        # 2. 开启端点 U (解决截断问题)
        spline.use_endpoint_u = True 
        
        # 3. 设置平滑阶数
        target_order = 5
        if len(spline.points) >= target_order:
            spline.order_u = target_order
        else:
            # 点数不足时适配点数
            spline.order_u = len(spline.points)
            
    print(f"已处理: {obj.name}，NURBS 阶数: 5，端点吸附: 开启。")
    
    # 【修复部分】
    # 曲线数据没有 update() 方法，通常修改属性后会自动更新。
    # 如果视图没有刷新，我们标记该对象需要更新：
    obj.update_tag()
    
else:
    print("选中的不是曲线对象！")