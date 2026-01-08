import bpy
import re
import os

def clean_name(original_name):
    # 移除所有数字和下划线，并将首字母改为大写
    cleaned_name = re.sub(r'[0-9_]', '', original_name).capitalize()
    return cleaned_name

# 预定义的对象前缀
object_prefix = "Scene_KazaniwaApartment_"

# 预定义的材质前缀
material_prefix = "Mat_Scene_KazaniwaApartment_"

# 存储已处理对象的ID，确保不重复处理
processed_object_ids = set()

# 存储对象名字以检查重复，并用于计数
object_name_counts = {}

# 获取所有对象
for obj in bpy.data.objects:
    # 检查是否已处理过该对象
    if obj.name not in processed_object_ids:
        original_name = obj.name

        # 检查是否已有前缀并且符合命名规范
        if original_name.startswith(object_prefix):
            base_name_with_number = original_name[len(object_prefix):]  # 截取掉前缀部分
            match = re.match(r"(.+?)_(\d{2})$", base_name_with_number)  # 匹配类似 'name_01' 的模式
            if match:
                # 如果名字已经有编号，不做修改
                clean_base_name, count = match.groups()
                new_name = original_name  # 保持原名不变
            else:
                # 没有编号的情况下，提取名字并重新编号
                clean_base_name = clean_name(base_name_with_number)
                if clean_base_name not in object_name_counts:
                    object_name_counts[clean_base_name] = 1
                else:
                    object_name_counts[clean_base_name] += 1
                count = object_name_counts[clean_base_name]
                new_name = f"{object_prefix}{clean_base_name}_{count:02d}"
        else:
            # 原名不带前缀的情况，重新处理
            clean_base_name = clean_name(original_name)
            if clean_base_name not in object_name_counts:
                object_name_counts[clean_base_name] = 1
            else:
                object_name_counts[clean_base_name] += 1
            count = object_name_counts[clean_base_name]
            new_name = f"{object_prefix}{clean_base_name}_{count:02d}"

        # 更新对象名字
        obj.name = new_name
        processed_object_ids.add(new_name)  # 更新已处理集合

        print(f'Renamed "{original_name}" to "{new_name}"')

# 同样的过程应用于材质球
processed_material_ids = set()
material_name_counts = {}

for material in bpy.data.materials:
    if material.name not in processed_material_ids:
        original_name = material.name

        # 检查是否已有前缀并且符合命名规范
        if original_name.startswith(material_prefix):
            base_name_with_number = original_name[len(material_prefix):]
            match = re.match(r"(.+?)_(\d{2})$", base_name_with_number)
            if match:
                # 如果名字已经有编号，不做修改
                clean_base_name, count = match.groups()
                new_name = original_name  # 保持原名不变
            else:
                # 没有编号的情况下，提取名字并重新编号
                clean_base_name = clean_name(base_name_with_number)
                if clean_base_name not in material_name_counts:
                    material_name_counts[clean_base_name] = 1
                else:
                    material_name_counts[clean_base_name] += 1
                count = material_name_counts[clean_base_name]
                new_name = f"{material_prefix}{clean_base_name}_{count:02d}"
        else:
            # 原名不带前缀的情况，重新处理
            clean_base_name = clean_name(original_name)
            if clean_base_name not in material_name_counts:
                material_name_counts[clean_base_name] = 1
            else:
                material_name_counts[clean_base_name] += 1
            count = material_name_counts[clean_base_name]
            new_name = f"{material_prefix}{clean_base_name}_{count:02d}"

        # 更新材质名字
        material.name = new_name
        processed_material_ids.add(new_name)

        print(f'Renamed "{original_name}" to "{new_name}"')

# 重命名贴图为材质球的名字
def rep_material_name(name):
    return name.replace(" ", "_")

material_prefix = "Mat_"
texture_prefix = "Tex_"

for material in bpy.data.materials:
    original_name = material.name
    if original_name.startswith(material_prefix):
        base_name = original_name[len(material_prefix):]
        new_texture_name = texture_prefix + rep_material_name(base_name)
        
        if material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    old_path = bpy.path.abspath(node.image.filepath)
                    directory, old_filename = os.path.split(old_path)
                    new_filename = new_texture_name + os.path.splitext(old_filename)[1]
                    new_path = os.path.join(directory, new_filename)

                    node.image.name = new_texture_name

                    if os.path.exists(old_path):
                        try:
                            os.rename(old_path, new_path)
                            node.image.filepath = bpy.path.relpath(new_path)
                            print(f"Renamed texture '{old_filename}' to '{new_filename}' and updated path to '{new_path}'")
                        except Exception as e:
                            print(f"Error renaming '{old_path}' to '{new_path}': {str(e)}")
                    else:
                        print(f"File '{old_path}' not found, unable to rename to '{new_path}'")

print("All objects, materials, and textures have been renamed.")
