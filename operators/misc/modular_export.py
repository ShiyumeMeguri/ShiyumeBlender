import bpy
import os
import json
import math
import mathutils

def to_json_compatible(value):
    """Recursively convert Blender types to JSON-compatible Python types."""
    import idprop
    if isinstance(value, (int, float, str, bool, type(None))):
        return value
    if hasattr(value, "to_list"): # mathutils types (Vector, Color, etc.)
        return value.to_list()
    if isinstance(value, (list, tuple)):
        return [to_json_compatible(v) for v in value]
    if isinstance(value, (idprop.types.IDPropertyGroup, dict)):
        return {k: to_json_compatible(value[k]) for k in value.keys()}
    if hasattr(value, "__iter__"):
        return [to_json_compatible(v) for v in value]
    return str(value) # Fallback for unknown types

class SHIYUME_OT_ModularExport(bpy.types.Operator):
    """Export scene as modular FBX parts and a RuriScene JSON map.
    Exports each unique mesh once to 'Models/[CollectionName]/'
    Generates a .ruriscene file describing the layout."""
    
    bl_idname = "shiyume.modular_export"
    bl_label = "Modular Export (RuriScene)"
    bl_options = {'REGISTER'}

    # Used to override auto-detection if needed, though we primarily use blend file location
    target_dir: bpy.props.StringProperty(name="Target Directory", default="")

    def execute(self, context):
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({'ERROR'}, "Save blend file first")
            return {'CANCELLED'}

        # Calculate base output folder
        file_name = os.path.splitext(os.path.basename(blend_path))[0]
        base_dir = os.path.dirname(blend_path)
        export_root = os.path.join(base_dir, "Models")
        
        if not os.path.exists(export_root):
            os.makedirs(export_root)

        self.report({'INFO'}, f"Exporting to {export_root}")
        
        # Data structures
        unique_mesh_map = {}
        
        # Collections to process
        target_collections = ["Entity", "Scene"]
        valid_objects = []
        
        # Gather objects
        for col_name in target_collections:
            if col_name in bpy.data.collections:
                for obj in bpy.data.collections[col_name].objects:
                    if obj.type == 'MESH':
                        valid_objects.append((obj, col_name))

        if not valid_objects:
            # Fallback: Export selection if no specific collections found
            for obj in context.selected_objects:
                if obj.type == 'MESH':
                    # Try to guess collection or default to 'Misc'
                    col = "Misc"
                    if obj.users_collection:
                        col = obj.users_collection[0].name
                    valid_objects.append((obj, col))

        # 1. Export Unique Meshes
        # For safety, deselect all first
        bpy.ops.object.select_all(action='DESELECT')
        
        scene_json_items = []
        
        # Helper for unity path
        def get_unity_rel_path(p):
            p = os.path.normpath(p)
            parts = p.split(os.sep)
            if "Assets" in parts:
                return "/".join(parts[parts.index("Assets"):])
            return os.path.basename(p)

        for obj, col_category in valid_objects:
            mesh_data = obj.data
            
            # Use mesh name for deduplication
            if mesh_data not in unique_mesh_map:
                # 1. Save state
                saved_matrix = obj.matrix_world.copy()
                
                # 2. Reset Transform
                obj.matrix_world = mathutils.Matrix.Identity(4)
                
                # 3. Export
                sub_folder = os.path.join(export_root, col_category)
                if not os.path.exists(sub_folder):
                    os.makedirs(sub_folder)
                    
                # Clean mesh name
                safe_name = mesh_data.name.replace(".", "_").replace(":", "_")
                fbx_filename = f"{safe_name}.fbx"
                full_fbx_path = os.path.join(sub_folder, fbx_filename)
                
                obj.select_set(True)
                
                # FBX Export
                bpy.ops.export_scene.fbx(
                    filepath=full_fbx_path,
                    use_selection=True,
                    global_scale=1.0,
                    apply_scale_options='FBX_SCALE_ALL',
                    object_types={'MESH'},
                    use_mesh_modifiers=True,
                    mesh_smooth_type='OFF',
                    use_custom_props=True,
                    bake_anim=False,
                    axis_forward='-Z',
                    axis_up='Y'
                )
                
                obj.select_set(False)
                
                # 4. Restore
                obj.matrix_world = saved_matrix
                
                # 5. Record
                unique_mesh_map[mesh_data] = {
                    'path': get_unity_rel_path(full_fbx_path),
                    'mesh_name': obj.name # Unity often imports the mesh using the Object name if single object
                }
            
            # Prepare JSON data for this instance
            export_info = unique_mesh_map[mesh_data]
            
            # Coordinate Conversion to Unity
            mat = obj.matrix_world
            loc = mat.to_translation()
            rot = mat.to_quaternion()
            scale = mat.to_scale()
            
            u_pos = {"x": -loc.x, "y": loc.z, "z": loc.y}
            u_rot = {"x": -rot.x, "y": rot.z, "z": rot.y, "w": -rot.w}
            u_scale = {"x": scale.x, "y": scale.z, "z": scale.y}
            
            scene_json_items.append({
                "name": obj.name,
                "type": col_category,
                "mesh_source_path": export_info['path'],
                "mesh_sub_asset": export_info['mesh_name'],
                "position": u_pos,
                "rotation": u_rot,
                "scale": u_scale,
                "properties": {k: to_json_compatible(obj[k]) for k in obj.keys() if not k.startswith('_')}
            })

        # Generate JSON
        scene_data = {
            "format_version": 1,
            "scene_name": file_name,
            "items": scene_json_items
        }
        
        json_path = os.path.join(base_dir, f"{file_name}.ruriscene")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(scene_data, f, indent=4)
            
        self.report({'INFO'}, f"Modular Export Complete. Saved {len(scene_json_items)} items.")
        return {'FINISHED'}
