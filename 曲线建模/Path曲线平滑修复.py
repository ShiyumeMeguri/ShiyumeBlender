import bpy

# 确保在执行此脚本之前已经选择了一个曲线对象
obj = bpy.context.object

if obj and obj.type == 'CURVE':
    for spline in obj.data.splines:
        # 1. 强制转为 NURBS
        if spline.type != 'NURBS':
            spline.type = 'NURBS'
        
        # 2. 【核心修复】开启端点 U，让曲线延伸到首尾顶点
        spline.use_endpoint_u = True 
        
        # 3. 设置平滑阶数
        # 阶数越高越平滑，但如果点太少会报错，所以要做个判断
        target_order = 5
        if len(spline.points) >= target_order:
            spline.order_u = target_order
        else:
            # 如果点不够5个，就按点的数量来设，防止消失
            spline.order_u = len(spline.points)
            
    print(f"已处理: {obj.name}，NURBS 阶数已设为 5，且已开启端点吸附。")
    # 强制更新视图
    obj.data.update()
else:
    print("选中的不是曲线对象！")