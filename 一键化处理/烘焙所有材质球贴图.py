import bpy
import os

# 创建BakeTex文件夹
output_folder = os.path.join(bpy.path.abspath("//"), "BakeTex")
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# 创建平面
bpy.ops.mesh.primitive_plane_add(size=2, enter_editmode=False, align='WORLD', location=(0, 0, 0))
plane = bpy.context.active_object

# 准备烘焙设置
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.bake_type = 'COMBINED'
bpy.context.scene.render.bake.use_selected_to_active = False

# 遍历所有材质
for material in bpy.data.materials:
    # 获取材质中的第一个图像纹理节点
    texture_node = None
    for node in material.node_tree.nodes:
        if node.type == 'TEX_IMAGE':
            texture_node = node
            break
    
    # 如果没有找到纹理节点，跳过该材质
    if texture_node is None or texture_node.image is None:
        print(f"Skipping material '{material.name}': No texture found.")
        continue

    # 获取原贴图名称和分辨率
    original_image_name = texture_node.image.name
    width, height = texture_node.image.size

    # 定义输出文件路径
    output_file_path = os.path.join(output_folder, original_image_name + ".png")

    # 如果文件已存在，跳过烘焙
    if os.path.exists(output_file_path):
        print(f"Skipping bake for '{material.name}': '{output_file_path}' already exists.")
        continue

    # 创建新图像并初始化
    bake_image = bpy.data.images.new(name=original_image_name + "_Bake", width=width, height=height, alpha=False)
    bake_image.generated_type = 'BLANK'

    # 将图像分配给平面材质
    if not plane.data.materials:
        plane.data.materials.append(material)
    else:
        plane.data.materials[0] = material

    # 创建新的节点树以包含烘焙图像
    plane_material = plane.active_material
    nodes = plane_material.node_tree.nodes
    links = plane_material.node_tree.links

    # 删除现有的烘焙图像节点
    if "Bake Image" in nodes:
        nodes.remove(nodes["Bake Image"])

    texture_node = nodes.new(type='ShaderNodeTexImage')
    texture_node.name = "Bake Image"
    texture_node.image = bake_image
    nodes.active = texture_node

    # 开始烘焙
    bpy.ops.object.bake(type='COMBINED')

    # 保存烘焙图像
    bake_image.filepath_raw = output_file_path
    bake_image.file_format = 'PNG'
    bake_image.save()

    # 删除临时图像节点
    nodes.remove(texture_node)

print("All materials have been baked and saved in the BakeTex folder.")
