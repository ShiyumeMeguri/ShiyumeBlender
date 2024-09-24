import bpy

# 确保在执行此脚本之前已经选择了一个曲线对象
obj = bpy.context.object

if obj.type == 'CURVE':
    for spline in obj.data.splines:
        if spline.type == 'NURBS':
            spline.order_u = 5
            print(f"已将NURBS顺序修改为: {spline.order_u}")
else:
    print("选中的不是曲线对象！")
