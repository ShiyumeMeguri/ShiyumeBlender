import bpy
import bmesh
import os


class SHIYUME_OT_SmartUVRedirect(bpy.types.Operator):
    """一键智能UV重定向:
    1. 复制渲染激活UV → _UVCopy (设为active)
    2. Average Islands Scale
    3. 关闭Sync → Unstack Islands
    4. UVPackMaster Pack
    5. Mesh to UV (生成展平Mesh)
    6. Viewport Render (用Workbench渲染已有贴图到新UV布局)
    7. 删除原始UV, 设Copy为RenderActive
    8. 将渲染出的贴图设置到选中网格的材质球"""
    bl_idname = "shiyume.smart_uv_redirect"
    bl_label = "智能UV重定向 (Smart UV Redirect)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_meshes:
            self.report({'ERROR'}, "请至少选择一个网格对象")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # ── Step 1: 复制渲染激活UV → _UVCopy ──
        processed_meshes = set()
        mesh_uv_info = {}  # mesh_id -> (render_uv_idx, copy_name)

        for obj in selected_meshes:
            mesh_data = obj.data
            mesh_id = id(mesh_data)

            if mesh_id in processed_meshes:
                continue
            processed_meshes.add(mesh_id)

            uv_layers = mesh_data.uv_layers
            if not uv_layers:
                self.report({'WARNING'}, f"'{obj.name}' 没有UV层, 跳过")
                continue

            # 找渲染激活UV (用index避免编码问题)
            render_uv = None
            render_uv_idx = 0
            for i, uv in enumerate(uv_layers):
                if uv.active_render:
                    render_uv = uv
                    render_uv_idx = i
                    break
            if not render_uv:
                render_uv = uv_layers.active
                render_uv_idx = uv_layers.active_index
            if not render_uv:
                continue

            copy_name = "_UVCopy"

            # 清除残留
            existing = uv_layers.get(copy_name)
            if existing:
                uv_layers.remove(existing)

            # 创建新UV并用bmesh复制数据
            new_uv = uv_layers.new(name=copy_name)
            if not new_uv:
                continue

            bm = bmesh.new()
            bm.from_mesh(mesh_data)
            bm.faces.ensure_lookup_table()

            uv_bm_layers = bm.loops.layers.uv
            src_layer = uv_bm_layers[render_uv_idx]
            dst_layer = uv_bm_layers[len(uv_bm_layers) - 1]

            for face in bm.faces:
                for loop in face.loops:
                    loop[dst_layer].uv = loop[src_layer].uv.copy()
            bm.to_mesh(mesh_data)
            bm.free()

            # copy设为active, 原始UV保持render_active
            uv_layers.active = new_uv
            mesh_uv_info[mesh_id] = (render_uv_idx, copy_name)

        if not mesh_uv_info:
            self.report({'ERROR'}, "没有找到可处理的UV层")
            return {'CANCELLED'}

        # ── Step 2: Average Islands Scale ──
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_meshes:
            obj.select_set(True)
        context.view_layer.objects.active = selected_meshes[0]

        # 保存用户的sync设置, 稍后恢复
        original_sync = context.scene.tool_settings.use_uv_select_sync

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.reveal()  # 取消隐藏所有网格

        # ★ 关键: 开启Sync后select_all, 确保所有对象的所有UV都被选中
        # 如果Sync是OFF, mesh.select_all不影响UV选择 → UV操作会漏掉部分对象
        context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.select_all(action='SELECT')

        try:
            bpy.ops.uv.average_islands_scale()
        except Exception as e:
            self.report({'WARNING'}, f"Average Scale 失败: {e}")

        # ── Step 3: Unstack Islands ──
        # Unstack 需要 Sync=OFF, 但关闭Sync后UV选择状态可能丢失
        # 技巧: 先在Sync=ON下全选mesh(=全选UV), 然后关闭Sync, UV选择状态会保留
        bpy.ops.mesh.select_all(action='SELECT')  # Sync仍为ON → UV也全选
        context.scene.tool_settings.use_uv_select_sync = False
        # 额外保险: 尝试在UV编辑器中也全选
        try:
            bpy.ops.uv.select_all(action='SELECT')
        except:
            pass

        if hasattr(bpy.ops.uv, "toolkit_unstack_islands"):
            try:
                bpy.ops.uv.toolkit_unstack_islands()
            except Exception as e:
                self.report({'WARNING'}, f"Unstack Islands 失败: {e}")
        else:
            self.report({'WARNING'}, "UV Toolkit 'Unstack Islands' 未找到, 跳过")

        # ── Step 4: UVPackMaster Pack ──
        # Pack也需要所有UV被选中, 再次确保
        context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.select_all(action='SELECT')
        context.scene.tool_settings.use_uv_select_sync = False
        try:
            bpy.ops.uv.select_all(action='SELECT')
        except:
            pass

        pack_ok = self._try_uvpackmaster_pack(context)
        if not pack_ok:
            self.report({'WARNING'}, "UVPackMaster 打包失败或未找到")

        # 恢复用户的Sync设置
        context.scene.tool_settings.use_uv_select_sync = original_sync

        # ── Step 5: Mesh to UV (生成展平Mesh对象) ──
        bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_meshes:
            obj.select_set(True)
        context.view_layer.objects.active = selected_meshes[0]

        try:
            bpy.ops.shiyume.mesh_to_uv()
        except Exception as e:
            self.report({'ERROR'}, f"Mesh to UV 失败: {e}")
            return {'CANCELLED'}

        # mesh_to_uv 改变了选择 → 现在选中的是展平对象
        flattened_objects = list(context.selected_objects)

        # ── Step 6: Viewport Render (用Workbench渲染已有贴图到新UV) ──
        # viewport_render 会自动处理: 复制对象→应用ShapeKey→Workbench渲染→清理
        # 输出到 Textures/{name}_UVRender.png (自动递增避免覆盖)
        
        # 先记录Textures目录中已有的文件, 以便找到新渲染的文件
        blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
        tex_dir = os.path.join(blend_dir, 'Textures') if blend_dir else ""
        
        existing_files = set()
        if tex_dir and os.path.exists(tex_dir):
            existing_files = set(os.listdir(tex_dir))

        try:
            bpy.ops.shiyume.render_viewport_texture()
        except Exception as e:
            self.report({'WARNING'}, f"Viewport渲染失败: {e}")

        # 找到viewport_render新生成的贴图文件
        rendered_texture_path = ""
        if tex_dir and os.path.exists(tex_dir):
            new_files = set(os.listdir(tex_dir)) - existing_files
            uv_render_files = [f for f in new_files if f.endswith('.png') and 'UVRender' in f]
            if uv_render_files:
                rendered_texture_path = os.path.join(tex_dir, uv_render_files[0])

        # ── Step 7: 清理 → 删除展平对象, 交换UV ──
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 删除mesh_to_uv创建的展平对象
        bpy.ops.object.select_all(action='DESELECT')
        for obj in flattened_objects:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if context.selected_objects:
            bpy.ops.object.delete()

        # UV交换: 删除原始UV, 设copy为RenderActive
        processed_swap = set()
        for obj in selected_meshes:
            if not obj or not obj.data:
                continue
            mesh_id = id(obj.data)
            if mesh_id in processed_swap:
                continue
            processed_swap.add(mesh_id)

            info = mesh_uv_info.get(mesh_id)
            if not info:
                continue

            render_uv_idx, copy_name = info
            uv_layers = obj.data.uv_layers

            if render_uv_idx < len(uv_layers):
                uv_layers.remove(uv_layers[render_uv_idx])

            copy_layer = uv_layers.get(copy_name)
            if copy_layer:
                copy_layer.active_render = True
                uv_layers.active = copy_layer

        # ── Step 8: 将渲染贴图设置到材质球 ──
        if rendered_texture_path and os.path.exists(rendered_texture_path):
            img_name = os.path.splitext(os.path.basename(rendered_texture_path))[0]
            img = bpy.data.images.get(img_name)
            if img:
                img.reload()
            else:
                img = bpy.data.images.load(rendered_texture_path)
                img.name = img_name

            for obj in selected_meshes:
                if not obj.data.materials:
                    continue
                for mat in obj.data.materials:
                    if not mat or not mat.use_nodes:
                        continue
                    tree = mat.node_tree

                    # 找Principled BSDF
                    principled = None
                    for node in tree.nodes:
                        if node.type == 'BSDF_PRINCIPLED':
                            principled = node
                            break
                    if not principled:
                        continue

                    base_color_input = principled.inputs.get("Base Color")
                    if not base_color_input:
                        continue

                    # 复用或创建Image Texture节点
                    tex_node = None
                    if base_color_input.links:
                        linked = base_color_input.links[0].from_node
                        if linked.type == 'TEX_IMAGE':
                            tex_node = linked

                    if not tex_node:
                        tex_node = tree.nodes.new('ShaderNodeTexImage')
                        tex_node.location = (principled.location.x - 300, principled.location.y)
                        tree.links.new(tex_node.outputs['Color'], base_color_input)

                    tex_node.image = img

            self.report({'INFO'}, f"智能UV重定向完成 — 贴图已设置: {rendered_texture_path}")
        else:
            self.report({'WARNING'}, "UV重定向完成但未找到渲染贴图, 请手动设置材质")

        # 恢复选择
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_meshes:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if selected_meshes:
            context.view_layer.objects.active = selected_meshes[0]

        return {'FINISHED'}

    def _try_uvpackmaster_pack(self, context):
        """调用 UVPackMaster3 Pack
        mode_id='pack.single_tile' → SCENARIO_ID='pack.general'
        pack_op_type='0' → PackOpType.PACK
        """
        uv_area = None
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                uv_area = area
                break

        def call_pack():
            if hasattr(bpy.ops, "uvpackmaster3"):
                bpy.ops.uvpackmaster3.pack(
                    mode_id='pack.single_tile',
                    pack_op_type='0'
                )
                return True
            return False

        try:
            if uv_area:
                with context.temp_override(area=uv_area):
                    return call_pack()
            else:
                return call_pack()
        except Exception as e:
            self.report({'WARNING'}, f"UVPackMaster Pack 失败: {e}")
            return False
