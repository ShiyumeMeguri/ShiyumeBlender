import bpy
import os

def clear_scene():
    # 切换到 Object 模式，防止对象在编辑模式下无法删除
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    # 尝试用 operator 删除
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    # 直接遍历所有对象并删除
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
        
    # 删除所有没有用户的 Mesh 数据块
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    
    # 可选：删除未使用的材质数据块
    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)

# ---------------------------
# 参数设置
# ---------------------------
source_blend = r"D:\Ruri\00.Model\Project\OC_World\KazaniwaApartment\KazaniwaApartment.blend"
export_dir = r"D:\Ruri\02.Unity\Project\FractalProject\Assets\RuriAssets\Art\Stages\Area\Aojakushi\KazaniwaApartment\Modular"
if not os.path.exists(export_dir):
    os.makedirs(export_dir)

# 使用空白工厂设置初始化场景
bpy.ops.wm.read_factory_settings(use_empty=True)

# 获取源文件中所有 Mesh 数据块的名称
with bpy.data.libraries.load(source_blend, link=False) as (data_from, data_to):
    mesh_names = data_from.meshes
print("找到的 Mesh 数量：", len(mesh_names))

# 遍历每个 Mesh
for mesh_name in mesh_names:
    print("处理 Mesh:", mesh_name)
    
    # 清空当前场景，确保上一次的对象被完全移除
    clear_scene()
    
    # 从源文件中加载当前 Mesh 数据块
    with bpy.data.libraries.load(source_blend, link=False) as (data_from, data_to):
        data_to.meshes = [mesh_name]
    
    mesh_data = bpy.data.meshes.get(mesh_name)
    if not mesh_data:
        print("无法加载 Mesh 数据：", mesh_name)
        continue
    
    # 根据 Mesh 数据创建新的对象并加入当前场景
    obj = bpy.data.objects.new(mesh_name, mesh_data)
    bpy.context.collection.objects.link(obj)
    
    # 重置对象变换：位置归零，旋转清零，缩放为 1
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    
    # 设置当前对象为活动对象并应用变换
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    
    # 构建导出路径，以 Mesh 名称命名文件
    export_path = os.path.join(export_dir, f"{mesh_name}.blend")
    
    # 导出当前场景为新的 blend 文件（场景中仅包含当前对象）
    bpy.ops.wm.save_as_mainfile(filepath=export_path)
    print(f"已导出 {mesh_name} 到 {export_path}")
