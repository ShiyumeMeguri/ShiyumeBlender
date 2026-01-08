import bpy

def get_or_create_material(name, color):
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

def add_outline_to_object(obj, material):
    # Check if the outline material and solidify modifier already exist
    outline_exists = any(mat_slot.material and mat_slot.material.name == material.name for mat_slot in obj.material_slots)
    solidify_exists = any(mod.type == 'SOLIDIFY' and mod.name == 'Solidify' for mod in obj.modifiers)

    if outline_exists and solidify_exists:
        # Remove outline and modifier if they exist
        remove_outline_from_object(obj, material)
    else:
        # Add the Outline material to the end of the material slots if it doesn't exist
        if not outline_exists:
            obj.data.materials.append(material)
        
        # Add Solidify Modifier if it doesn't exist
        if not solidify_exists:
            mod_solidify = obj.modifiers.new(name='Solidify', type='SOLIDIFY')
            mod_solidify.thickness = 0.001
            mod_solidify.use_flip_normals = True
            mod_solidify.use_quality_normals = True
            mod_solidify.vertex_group = "Alpha"
            mod_solidify.material_offset = len(obj.material_slots) - 1

def remove_outline_from_object(obj, material):
    # Remove the solidify modifier named 'Solidify'
    for mod in obj.modifiers:
        if mod.type == 'SOLIDIFY' and mod.name == 'Solidify':
            obj.modifiers.remove(mod)
            break

    # Remove the outline material
    for i, mat_slot in enumerate(obj.material_slots):
        if mat_slot.material and mat_slot.material.name == material.name:
            obj.data.materials.pop(index=i)
            break

def is_in_collection(obj, collection):
    """Check if an object is in a collection or its child collections recursively."""
    if obj.name in collection.objects:
        return True
    for child_collection in collection.children:
        if is_in_collection(obj, child_collection):
            return True
    return False

def main():
    # Get the IgnoreExport collection
    ignore_collection = bpy.data.collections.get('IgnoreExport')
    
    # Create or get the Outline material
    outline_material = get_or_create_material('Outline', (0, 0, 0, 1))  # Black color
    
    # Iterate through all mesh objects in the scene
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            # Check if the object is not in the IgnoreExport collection or its child collections
            if not ignore_collection or not is_in_collection(obj, ignore_collection):
                add_outline_to_object(obj, outline_material)

if __name__ == "__main__":
    main()
