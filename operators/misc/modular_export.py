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

        # Get Env Var with Registry Fallback for Windows
        fractal_path = os.environ.get("FractalPath")
        
        if not fractal_path and os.name == 'nt':
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    fractal_path, _ = winreg.QueryValueEx(key, "FractalPath")
            except Exception as e:
                print(f"Registry lookup failed: {e}")

        if not fractal_path:
             self.report({'ERROR'}, "Environment variable 'FractalPath' is not set.")
             return {'CANCELLED'}
             
        file_name = os.path.splitext(os.path.basename(blend_path))[0]
        
        # Paths
        # Models: %FractalPath%\Assets\RuriAssets\Art\Stage\[SceneName]\Models
        model_root = os.path.join(fractal_path, "Assets", "RuriAssets", "Art", "Stage", file_name, "Models")
        
        # Scene Data: %FractalPath%\Assets\RuriAssets\Art\Scene\[SceneName]
        scene_root = os.path.join(fractal_path, "Assets", "RuriAssets", "Art", "Scene", file_name)
        
        if not os.path.exists(model_root):
            os.makedirs(model_root)
        if not os.path.exists(scene_root):
            os.makedirs(scene_root)

        self.report({'INFO'}, f"Exporting Models to {model_root}")
        self.report({'INFO'}, f"Exporting Scene to {scene_root}")
        
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
            # We want path starting with "Assets/"
            # Since we construct export_root using fractal_path + Assets..., 
            # we can just take relative path from fractal_path
            rel = os.path.relpath(p, fractal_path)
            return rel.replace("\\", "/")

        # Helper to strip .001 suffix
        def get_base_name(name):
            # Check for .### pattern
            if len(name) > 4 and name[-4] == '.' and name[-3:].isdigit():
                return name[:-4]
            return name

        # Sort objects to ensure we process base names before suffixes if possible (optional but helpful)
        # Simply processing them in order is fine, but we need to track what we've exported by NAME, not just by data pointer.
        
        # New Map: BaseName -> { path, mesh_name }
        exported_base_names_map = {}
        
        for obj, col_category in valid_objects:
            mesh_data = obj.data
            
            # Smart Deduplication Strategy:
            # 1. Check if mesh_data is already mapped (Exact same data block).
            # 2. Check if mesh_data.name has a suffix (e.g. "Poster.001") AND the base name ("Poster") was already exported.
            
            base_name = get_base_name(mesh_data.name)
            
            # Check strict data identity first
            if mesh_data in unique_mesh_map:
                export_info = unique_mesh_map[mesh_data]
            
            # Check name-based identity (User requirement: treat .001 as duplicated link)
            elif base_name in exported_base_names_map:
                # Reuse the base export
                export_info = exported_base_names_map[base_name]
                # Map this mesh_data to the existing info so future lookups are fast
                unique_mesh_map[mesh_data] = export_info
            
            else:
                # Must export new
                
                # 1. Save state
                saved_matrix = obj.matrix_world.copy()
                
                # 2. Reset Transform
                obj.matrix_world = mathutils.Matrix.Identity(4)
                
                # 3. Export
                # sub_folder = os.path.join(model_root, col_category) <-- REMOVED SUBFOLDER
                sub_folder = model_root # Flattened structure
                if not os.path.exists(sub_folder):
                    os.makedirs(sub_folder)
                    
                # Clean mesh name
                # If this is "Poster.001" and we haven't seen "Poster", we might want to export it AS "Poster.001" 
                # OR user implies that "Poster" exists elsewhere? 
                # Assuming if we are here, we are the 'first' instance of this 'type'. 
                # Let's use the object's mesh name as the filename.
                
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
                export_info = {
                    'path': get_unity_rel_path(full_fbx_path),
                    'mesh_name': obj.name # Unity often imports the mesh using the Object name if single object
                }
                
                unique_mesh_map[mesh_data] = export_info
                exported_base_names_map[base_name] = export_info
            
            # Prepare JSON data for this instance
            # export_info is set above
            
            # Coordinate Conversion to Unity
            mat = obj.matrix_world
            loc = mat.to_translation()
            rot = mat.to_quaternion()
            scale = mat.to_scale()
            
            # Version 2: Try -90 on X or other combinations.
            # "Upside down" (180 error) implies my previous +90 was wrong direction or added to an existing 90.
            # Standard Unity mapping from Blender: X-90.
            q_correction = mathutils.Euler((math.radians(-90), 0, 0)).to_quaternion()
            rot = rot @ q_correction 
            
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
        
        json_path = os.path.join(scene_root, f"{file_name}.ruriscene")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(scene_data, f, indent=4)
            
        self.report({'INFO'}, f"Modular Export Complete. Saved {len(scene_json_items)} items.")
        return {'FINISHED'}
