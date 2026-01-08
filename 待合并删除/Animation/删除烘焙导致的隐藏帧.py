import bpy

for action in bpy.data.actions:
    print(f"处理动作: {action.name}")
    
    # 反向遍历 fcurves 列表，安全删除 fcurve
    for i in range(len(action.fcurves)-1, -1, -1):
        fcurve = action.fcurves[i]
        if '"]["' in fcurve.data_path:
            print(f"  删除自定义属性 fcurve: {fcurve.data_path}")
            action.fcurves.remove(fcurve)
    
    print(f"动作 {action.name} 处理完成。\n")
