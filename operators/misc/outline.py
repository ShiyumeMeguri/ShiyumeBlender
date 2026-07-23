import bpy


def _get_or_create_material(name, color):
    material = bpy.data.materials.get(name)
    if not material:
        material = bpy.data.materials.new(name=name)
        material.use_nodes = True
        bsdf = material.node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = color
            bsdf.inputs[2].default_value = 1
        material.use_backface_culling = True
    return material


def _add_outline_to_object(obj, material):
    outline_exists = any(mat_slot.material and mat_slot.material.name == material.name for mat_slot in obj.material_slots)
    solidify_exists = any(mod.type == 'SOLIDIFY' and mod.name == 'Solidify' for mod in obj.modifiers)

    if outline_exists and solidify_exists:
        _remove_outline_from_object(obj, material)
    else:
        if not outline_exists:
            obj.data.materials.append(material)

        if not solidify_exists:
            mod_solidify = obj.modifiers.new(name='Solidify', type='SOLIDIFY')
            mod_solidify.thickness = 0.001
            mod_solidify.use_flip_normals = True
            mod_solidify.use_quality_normals = True
            mod_solidify.vertex_group = "Alpha"
            mod_solidify.material_offset = len(obj.material_slots) - 1


def _remove_outline_from_object(obj, material):
    for mod in obj.modifiers:
        if mod.type == 'SOLIDIFY' and mod.name == 'Solidify':
            obj.modifiers.remove(mod)
            break

    for i, mat_slot in enumerate(obj.material_slots):
        if mat_slot.material and mat_slot.material.name == material.name:
            obj.data.materials.pop(index=i)
            break


def _is_in_collection(obj, collection):
    if obj.name in collection.objects:
        return True
    for child_collection in collection.children:
        if _is_in_collection(obj, child_collection):
            return True
    return False


class SHIYUME_OT_Outline(bpy.types.Operator):
    """一键为模型添加描边效果（使用Solidify修改器翻转法线）。
    常用于二次元/卡通风格渲染，自动设置材质和修改器参数。
    会跳过 'IgnoreExport' 集合下的对象。再次执行时会移除已有描边（切换）。"""
    bl_idname = "shiyume.outline"
    bl_label = "一键描边"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ignore_collection = bpy.data.collections.get('IgnoreExport')

        outline_material = _get_or_create_material('Outline', (0, 0, 0, 1))

        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                if not ignore_collection or not _is_in_collection(obj, ignore_collection):
                    _add_outline_to_object(obj, outline_material)

        return {'FINISHED'}
