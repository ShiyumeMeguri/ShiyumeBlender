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

        # Helper: Generate Modifier Checksum/Signature
        def get_modifier_signature(obj):
            mods = [m for m in obj.modifiers if m.show_render]
            if not mods:
                return "NOMOD"
            
            sig_parts = []
            for m in mods:
                props = ""
                if m.type == 'ARRAY':
                    props = f"{m.count}_{m.fit_type}_{m.constant_offset_displace}_{m.relative_offset_displace}"
                elif m.type == 'MIRROR':
                    props = f"{m.use_axis}_{m.use_bisect_axis}_{m.use_mirror_merge}"
                elif m.type == 'BEVEL':
                    props = f"{m.width}_{m.segments}_{m.profile}_{m.limit_method}"
                elif m.type == 'SOLIDIFY':
                    props = f"{m.thickness}_{m.offset}"
                elif m.type == 'SUBSURF':
                    props = f"{m.levels}_{m.render_levels}"
                else:
                    props = m.name 
                sig_parts.append(f"{m.type}:{props}")
            return "_".join(sig_parts)

        # Helper: Calculate Rotation Matrix from Mesh A to Mesh B
        def calc_mesh_rotation_diff(mesh_base, mesh_var):
            if len(mesh_base.vertices) != len(mesh_var.vertices): return None
            if len(mesh_base.vertices) < 3: return mathutils.Matrix.Identity(4)
            
            # Use First 3 Vertices for Basis
            vA1, vA2, vA3 = mesh_base.vertices[0].co, mesh_base.vertices[1].co, mesh_base.vertices[2].co
            vB1, vB2, vB3 = mesh_var.vertices[0].co, mesh_var.vertices[1].co, mesh_var.vertices[2].co
            
            xA = (vA2 - vA1).normalized()
            nA = (vA2 - vA1).cross(vA3 - vA1).normalized()
            yA = xA.cross(nA).normalized()
            zA = nA
            matA = mathutils.Matrix((xA, yA, zA)).transposed()
            
            xB = (vB2 - vB1).normalized()
            nB = (vB2 - vB1).cross(vB3 - vB1).normalized()
            yB = xB.cross(nB).normalized()
            zB = nB
            matB = mathutils.Matrix((xB, yB, zB)).transposed()
            
            R = matB @ matA.inverted() 
            return R.to_4x4()

        # Helper: Verify if Rotation Matrix correctly maps Mesh A to Mesh B (Rigid check)
        def verify_rotation_match(mesh_base, mesh_var, R, samples=10):
            import random
            count = len(mesh_base.vertices)
            indices = list(range(count))
            # deterministic sample for stability
            sample_indices = indices if count <= samples else [indices[i*count//samples] for i in range(samples)]
            
            for i in sample_indices:
                va = mesh_base.vertices[i].co
                vb = mesh_var.vertices[i].co
                va_transformed = R @ va
                if (va_transformed - vb).length > 0.001: # Tolerance
                    return False
            return True

        # NEW DEDUPLICATION MAP
        # Key: (VertexCount, PolyCount, ModSignature) -> List of { 'path':..., 'mesh_name':..., 'ref_mesh':... }
        # logic: 
        # 1. Calc Key.
        # 2. Iterate List. Check 'verify_rotation_match'.
        # 3. If Match -> Reuse.
        # 4. If No Match -> Export New & Apppend.
        
        geometry_map = {}
        
        scene_json_items = []
        
        for obj, col_category in valid_objects:
            mesh_data = obj.data
            mod_sig = get_modifier_signature(obj)
            
            # Broad Phase Hash: Verts, Polys, Mods
            geo_key = (len(mesh_data.vertices), len(mesh_data.polygons), mod_sig)
            
            export_path = ""
            export_mesh_name = ""
            instance_correction_matrix = mathutils.Matrix.Identity(4)
            found_match = False
            
            if geo_key in geometry_map:
                # Potential Matches
                candidates = geometry_map[geo_key]
                for info in candidates:
                    ref_mesh = info['ref_mesh']
                    
                    # 1. Check if same object data (fast path)
                    if ref_mesh == mesh_data:
                        export_path = info['path']
                        export_mesh_name = info['mesh_name']
                        found_match = True
                        break
                        
                    # 2. Check Geometry match via Rotation
                    R_diff = calc_mesh_rotation_diff(ref_mesh, mesh_data)
                    if R_diff and verify_rotation_match(ref_mesh, mesh_data, R_diff):
                        export_path = info['path']
                        export_mesh_name = info['mesh_name']
                        instance_correction_matrix = R_diff
                        found_match = True
                        break
            else:
                 geometry_map[geo_key] = []
            
            if not found_match:
                # Export New
                saved_matrix = obj.matrix_world.copy()
                obj.matrix_world = mathutils.Matrix.Identity(4)
                
                sub_folder = model_root
                if not os.path.exists(sub_folder): os.makedirs(sub_folder)
                
                safe_name = obj.name.replace(".", "_").replace(":", "_")
                fbx_filename = f"{safe_name}.fbx"
                full_fbx_path = os.path.join(sub_folder, fbx_filename)
                
                obj.select_set(True)
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
                obj.matrix_world = saved_matrix
                
                info = {
                    'path': get_unity_rel_path(full_fbx_path),
                    'mesh_name': obj.name,
                    'ref_mesh': mesh_data
                }
                geometry_map[geo_key].append(info)
                
                export_path = info['path']
                export_mesh_name = info['mesh_name']

            # Final Matrix Calculation
            mat = obj.matrix_world
            final_mat = mat @ instance_correction_matrix
            loc = final_mat.to_translation()
            rot = final_mat.to_quaternion()
            scale = final_mat.to_scale()
            
            # Standard Unity Correction (-90 X) relative to World
            q_correction = mathutils.Euler((math.radians(-90), 0, 0)).to_quaternion()
            rot = rot @ q_correction 
            
            # User reported Z is inverted (-1.24 vs 1.24). 
            # Previous: z = loc.y. New: z = -loc.y
            u_pos = {"x": -loc.x, "y": loc.z, "z": -loc.y}
            u_rot = {"x": -rot.x, "y": rot.z, "z": rot.y, "w": -rot.w}
            u_scale = {"x": scale.x, "y": scale.z, "z": scale.y}
            
            scene_json_items.append({
                "name": obj.name,
                "type": col_category,
                "mesh_source_path": export_path,
                "mesh_sub_asset": export_mesh_name,
                "position": u_pos,
                "rotation": u_rot,
                "scale": u_scale,
                "properties": {k: to_json_compatible(obj[k]) for k in obj.keys() if not k.startswith('_')}
            })
            
            scene_json_items.append({
                "name": obj.name,
                "type": col_category,
                "mesh_source_path": export_path,
                "mesh_sub_asset": export_mesh_name,
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
