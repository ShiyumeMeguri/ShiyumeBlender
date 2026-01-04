import bpy
import bmesh
import tempfile
import os

class SHIYUME_OT_RenderViewportAsTexture(bpy.types.Operator):
    """Render the active 3D viewport as a temporary texture"""
    bl_idname = "shiyume.render_viewport_texture"
    bl_label = "Viewport to Texture"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        orig_res_x = scene.render.resolution_x
        orig_res_y = scene.render.resolution_y
        orig_filepath = scene.render.filepath
        orig_format = scene.render.image_settings.file_format
        
        view3d_spaces = []
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        scene.render.resolution_x = region.width
                        scene.render.resolution_y = region.height
                for space in area.spaces:
                    if space.type == 'VIEW_3D' and space.overlay.show_overlays:
                        view3d_spaces.append(space)
                        space.overlay.show_overlays = False

        temp_path = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
        scene.render.filepath = temp_path
        scene.render.image_settings.file_format = 'PNG'

        bpy.ops.render.opengl(write_still=True, view_context=True)

        for space in view3d_spaces:
            space.overlay.show_overlays = True

        scene.render.resolution_x = orig_res_x
        scene.render.resolution_y = orig_res_y
        scene.render.filepath = orig_filepath
        scene.render.image_settings.file_format = orig_format

        self.report({'INFO'}, f"Rendered to: {temp_path}")
        return {'FINISHED'}

class SHIYUME_OT_NormalExpansion(bpy.types.Operator):
    """Expand normals and overwrite original normals (outline prep)"""
    bl_idname = "shiyume.normal_expansion"
    bl_label = "Normal Expansion Overwrite"
    bl_options = {'REGISTER', 'UNDO'}

    distance: bpy.props.FloatProperty(name="Distance", default=0.001, precision=4)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        processed_meshes = set()
        for obj in context.selected_objects:
            if obj.type != 'MESH' or obj.data in processed_meshes: continue
            
            # Implementation from script
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            context.collection.objects.link(new_obj)
            
            # Edit new object
            context.view_layer.objects.active = new_obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm_new = bmesh.from_edit_mesh(new_obj.data)
            for v in bm_new.verts:
                v.co += v.normal * self.distance
            bmesh.update_edit_mesh(new_obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')

            # Update original
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm_orig = bmesh.from_edit_mesh(obj.data)
            bm_orig.verts.ensure_lookup_table()

            for i, v_orig in enumerate(bm_orig.verts):
                bpy.ops.mesh.select_all(action='DESELECT')
                bm_orig.verts[i].select = True
                bmesh.update_edit_mesh(obj.data)
                global_new_co = new_obj.matrix_world @ new_obj.data.vertices[i].co
                bpy.ops.mesh.point_normals(target_location=global_new_co)

            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(new_obj)
            processed_meshes.add(obj.data)

        return {'FINISHED'}

class SHIYUME_OT_VertexColorRGBA(bpy.types.Operator):
    """Set vertex color RGBA channels from vertex groups (Red, Green, Blue, Alpha)"""
    bl_idname = "shiyume.vertex_color_rgba"
    bl_label = "Vertex Groups to RGBA"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type != 'MESH': continue
            
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='VERTEX_PAINT')
            if not obj.data.vertex_colors:
                obj.data.vertex_colors.new()
            
            color_layer = obj.data.vertex_colors.active
            mapping = {'Red': 0, 'Green': 1, 'Blue': 2, 'Alpha': 3}
            group_indices = {name: obj.vertex_groups[name].index for name in mapping if name in obj.vertex_groups}

            for poly in obj.data.polygons:
                for idx, loop_idx in enumerate(poly.loop_indices):
                    vert_idx = poly.vertices[idx]
                    vert = obj.data.vertices[vert_idx]
                    color = list(color_layer.data[loop_idx].color)
                    
                    for name, g_idx in group_indices.items():
                        c_idx = mapping[name]
                        for g in vert.groups:
                            if g.group == g_idx:
                                color[c_idx] = g.weight
                                break
                    color_layer.data[loop_idx].color = color
            
            bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}

class SHIYUME_OT_BatchBakeTextures(bpy.types.Operator):
    """Bake all materials to textures in BakeTex folder"""
    bl_idname = "shiyume.batch_bake_textures"
    bl_label = "Batch Bake All Materials"
    bl_options = {'REGISTER'}

    def execute(self, context):
        output_folder = os.path.join(bpy.path.abspath("//"), "BakeTex")
        if not os.path.exists(output_folder): os.makedirs(output_folder)

        bpy.ops.mesh.primitive_plane_add(size=2)
        plane = context.active_object
        context.scene.render.engine = 'CYCLES'
        context.scene.cycles.bake_type = 'COMBINED'

        for mat in bpy.data.materials:
            if not mat.use_nodes: continue
            tex_node = next((n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE'), None)
            if not tex_node or not tex_node.image: continue

            img = tex_node.image
            out_path = os.path.join(output_folder, img.name + ".png")
            if os.path.exists(out_path): continue

            bake_img = bpy.data.images.new(name=img.name + "_Bake", width=img.size[0], height=img.size[1])
            if not plane.data.materials: plane.data.materials.append(mat)
            else: plane.data.materials[0] = mat

            node = mat.node_tree.nodes.new(type='ShaderNodeTexImage')
            node.image = bake_img
            mat.node_tree.nodes.active = node

            bpy.ops.object.bake(type='COMBINED')
            bake_img.filepath_raw = out_path
            bake_img.file_format = 'PNG'
            bake_img.save()
            mat.node_tree.nodes.remove(node)
        
        bpy.ops.object.delete()
        return {'FINISHED'}

classes = (
    SHIYUME_OT_RenderViewportAsTexture,
    SHIYUME_OT_NormalExpansion,
    SHIYUME_OT_VertexColorRGBA,
    SHIYUME_OT_BatchBakeTextures,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
