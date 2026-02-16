import bpy
import bmesh
import os


class SHIYUME_OT_SmartUVRedirect(bpy.types.Operator):
    """一键智能UV重定向:
    1. 复制渲染激活UV → {原名}_Copy (设为Active Index)
    2. Average Islands Scale
    3. Unstack Islands
    4. UVPackMaster Pack
    5. Mesh to UV (生成展平Mesh)
    6. Viewport Render (渲染已有贴图到新UV布局)
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

        original_sync = context.scene.tool_settings.use_uv_select_sync

        # ── Step 1: 复制渲染激活UV → {原名}_Copy ──────────────────
        processed_meshes = set()
        mesh_uv_info = {}  # mesh_data.name -> (render_uv_idx, copy_name)

        for obj in selected_meshes:
            mesh_data = obj.data
            mn = mesh_data.name
            if mn in processed_meshes:
                continue
            processed_meshes.add(mn)

            uv_layers = mesh_data.uv_layers
            if not uv_layers:
                continue

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

            try:
                copy_name = render_uv.name + "_Copy"
            except:
                copy_name = f"UV{render_uv_idx}_Copy"

            existing = uv_layers.get(copy_name)
            if existing:
                uv_layers.remove(existing)

            new_uv = uv_layers.new(name=copy_name)
            if not new_uv:
                continue

            bm = bmesh.new()
            bm.from_mesh(mesh_data)
            bm.faces.ensure_lookup_table()
            uv_bm = bm.loops.layers.uv
            src = uv_bm[render_uv_idx]
            dst = uv_bm[len(uv_bm) - 1]
            for f in bm.faces:
                for lp in f.loops:
                    lp[dst].uv = lp[src].uv.copy()
            bm.to_mesh(mesh_data)
            bm.free()

            # Active Index → copy, Active Render 保持原始UV
            uv_layers.active_index = len(uv_layers) - 1
            mesh_uv_info[mn] = (render_uv_idx, copy_name)

        if not mesh_uv_info:
            self.report({'ERROR'}, "没有找到可处理的UV层")
            return {'CANCELLED'}

        # ── Step 2: Average Islands Scale ─────────────────────────
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_meshes:
            obj.select_set(True)
        context.view_layer.objects.active = selected_meshes[0]

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.reveal()
        context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.select_all(action='SELECT')

        try:
            bpy.ops.uv.average_islands_scale()
        except Exception as e:
            self.report({'WARNING'}, f"Average Scale 失败: {e}")

        # ── Step 3: Unstack Islands ───────────────────────────────
        bpy.ops.mesh.select_all(action='SELECT')
        context.scene.tool_settings.use_uv_select_sync = False
        try:
            bpy.ops.uv.select_all(action='SELECT')
        except:
            pass

        if hasattr(bpy.ops.uv, "toolkit_unstack_islands"):
            try:
                bpy.ops.uv.toolkit_unstack_islands()
            except Exception as e:
                self.report({'WARNING'}, f"Unstack 失败: {e}")

        # ── Step 4: UVPackMaster Pack ─────────────────────────────
        context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.select_all(action='SELECT')
        context.scene.tool_settings.use_uv_select_sync = False
        try:
            bpy.ops.uv.select_all(action='SELECT')
        except:
            pass

        self._try_uvpackmaster_pack(context)

        context.scene.tool_settings.use_uv_select_sync = original_sync

        # ── Step 5: Mesh to UV ────────────────────────────────────
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

        flattened_objects = list(context.selected_objects)

        # ── Step 6: Viewport Render ───────────────────────────────
        blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
        tex_dir = os.path.join(blend_dir, 'Textures') if blend_dir else ""
        existing_files = set()
        if tex_dir and os.path.exists(tex_dir):
            existing_files = set(os.listdir(tex_dir))

        try:
            bpy.ops.shiyume.render_viewport_texture()
        except Exception as e:
            self.report({'WARNING'}, f"Viewport渲染失败: {e}")

        rendered_texture_path = ""
        if tex_dir and os.path.exists(tex_dir):
            new_files = set(os.listdir(tex_dir)) - existing_files
            uv_files = [f for f in new_files if f.endswith('.png') and 'UVRender' in f]
            if uv_files:
                rendered_texture_path = os.path.join(tex_dir, uv_files[0])

        # ── Step 7: 清理 + UV 交换 ────────────────────────────────
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 删除展平对象
        bpy.ops.object.select_all(action='DESELECT')
        for obj in flattened_objects:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if context.selected_objects:
            bpy.ops.object.delete()

        # UV 交换
        processed_swap = set()
        for obj in selected_meshes:
            if not obj or not obj.data:
                continue
            mn = obj.data.name
            if mn in processed_swap:
                continue
            processed_swap.add(mn)

            info = mesh_uv_info.get(mn)
            if not info:
                continue
            ridx, cname = info
            uv_layers = obj.data.uv_layers
            if ridx < len(uv_layers):
                uv_layers.remove(uv_layers[ridx])
            copy = uv_layers.get(cname)
            if copy:
                copy.active_render = True
                uv_layers.active = copy

        # ── Step 8: 设置贴图到材质 ────────────────────────────────
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
                    principled = None
                    for node in tree.nodes:
                        if node.type == 'BSDF_PRINCIPLED':
                            principled = node
                            break
                    if not principled:
                        continue
                    bc = principled.inputs.get("Base Color")
                    if not bc:
                        continue
                    tex_node = None
                    if bc.links:
                        linked = bc.links[0].from_node
                        if linked.type == 'TEX_IMAGE':
                            tex_node = linked
                    if not tex_node:
                        tex_node = tree.nodes.new('ShaderNodeTexImage')
                        tex_node.location = (principled.location.x - 300, principled.location.y)
                        tree.links.new(tex_node.outputs['Color'], bc)
                    tex_node.image = img

            self.report({'INFO'}, f"智能UV重定向完成 — 贴图: {rendered_texture_path}")
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
