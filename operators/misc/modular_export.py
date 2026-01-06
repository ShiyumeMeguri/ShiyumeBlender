import bpy
import os
import json
import math
import mathutils

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
        # e.g. D:\...\Area\Aojakushi\MyFile\
        file_name = os.path.splitext(os.path.basename(blend_path))[0]
        
        # If user explicitly set a path in a file browser workflow (not implemented in UI yet but good practice), use it.
        # Otherwise default to: [Expected Asset Path]/[FileName]/
        # We will follow the user's specific request structure: 
        # "D:\Ruri\02.Unity\Project\FractalProject\Assets\RuriAssets\Art\Stage\Area\Aojakushi\{file_name}\Models"
        # However, hardcoding the exact path is brittle. Let's assume we export RELATIVE to the blend file if it's in the project.
        # IF the blend file is external (User said "D:\Ruri\00.Model\NoSync\ShiyumeBlender" symlinked?), 
        # wait, the blend file is likely in the Art source folder.
        # User script example: output_folder = fr"D:\...\Aojakushi\{file_name}\Models"
        
        # We'll use the blend file's directory as the base.
        base_dir = os.path.dirname(blend_path)
        export_root = os.path.join(base_dir, "Models")
        
        if not os.path.exists(export_root):
            os.makedirs(export_root)

        self.report({'INFO'}, f"Exporting to {export_root}")
        
        # Data structures
        # unique_mesh_map: { mesh_data: { 'path': "Relative/Path.fbx", 'name': "MeshName" } }
        unique_mesh_map = {}
        
        # To avoid name collisions like "Cube" in Entity and "Cube" in Scene, we prefer unique names or just use Mesh Name directly.
        # We will use the Mesh Data Name as the filename source.
        
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
        # We need to ensure we don't modify the scene permanently.
        # We will store original transforms, zero them, export, restore.
        
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
            # If multiple objects share mesh 'Cube.001', we only export it once as 'Cube.001.fbx'
            
            if mesh_data not in unique_mesh_map:
                # Need to export this mesh
                # We use the CURRENT object as the exporter delegate
                # 1. Save state
                orig_loc = obj.location.copy()
                orig_rot = obj.rotation_euler.copy()
                orig_mode = obj.rotation_mode
                orig_scale = obj.scale.copy()
                orig_parent = obj.parent
                
                # 2. Reset Transform
                # We want the mesh to be at 0,0,0 in the FBX so Unity pivot is correct.
                # Unlink parent temporarily to ensure world origin is true origin
                if orig_parent:
                    # Storing matrix_world and restoring it is safer than unparenting?
                    # No, unparenting with matrix_world kept is best, then zero out.
                    # But assumes keep transform. 
                    # Simplest: Just set matrix_world to Identity.
                    pass
                 
                # We'll use matrix_world setting directly
                saved_matrix = obj.matrix_world.copy()
                obj.matrix_world = mathutils.Matrix.Identity(4)
                
                # 3. Export
                # Destination: Models/[Category]/[MeshName].fbx
                # Note: We use the Object's category for the Mesh. 
                # If a Mesh is shared across categories, the first one wins.
                
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
                    apply_scale_options='FBX_SCALE_ALL', # Crucial for clean scale
                    object_types={'MESH'},
                    use_mesh_modifiers=True, # Apply modifiers
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
                "type": col_category, # Entity or Scene
                "mesh_source_path": export_info['path'],
                "mesh_sub_asset": export_info['mesh_name'], # This might need refinement if FBX export changes name
                "position": u_pos,
                "rotation": u_rot,
                "scale": u_scale,
                "properties": {k: v for k, v in obj.items() if not k.startswith('_')}
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
