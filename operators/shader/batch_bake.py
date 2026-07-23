import bpy
import os

class SHIYUME_OT_BatchBakeTextures(bpy.types.Operator):
    """批量烘焙所有材质的漫反射/Combined贴图到 'BakeTex' 文件夹。
    自动为每个材质创建烘焙节点，烘焙完成后自动保存并清理。"""
    bl_idname = "shiyume.batch_bake_textures"
    bl_label = "批量烘焙所有材质"
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
