import bpy
import bmesh
import os


class SHIYUME_OT_PrepareUVCopy(bpy.types.Operator):
    """Step 1: 复制渲染激活UV → {原名}_Copy 并设为Active。
    之后你可以手动调整UV布局 (展开、打包等)，
    调整完毕后再使用「UV重定向渲染」烘焙贴图。"""
    bl_idname = "shiyume.prepare_uv_copy"
    bl_label = "准备UV副本 (Prepare UV Copy)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_meshes:
            self.report({'ERROR'}, "请至少选择一个网格对象")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        processed = set()
        copied = 0

        for obj in selected_meshes:
            mesh_data = obj.data
            mn = mesh_data.name
            if mn in processed:
                continue
            processed.add(mn)

            uv_layers = mesh_data.uv_layers
            if not uv_layers:
                self.report({'WARNING'}, f"'{obj.name}' 没有UV层, 跳过")
                continue

            # 找渲染激活UV
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

            # 命名: {原始UV名}_Copy (去除已有的 _Copy 后缀防止叠加)
            try:
                orig_name = render_uv.name
                base_name = orig_name
                while base_name.endswith("_Copy"):
                    base_name = base_name[:-5]
                copy_name = base_name + "_Copy"
            except:
                copy_name = f"UV{render_uv_idx}_Copy"

            # 清除同名残留
            existing = uv_layers.get(copy_name)
            if existing:
                uv_layers.remove(existing)

            new_uv = uv_layers.new(name=copy_name)
            if not new_uv:
                continue

            # bmesh 复制 UV 坐标
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

            # 设 Active Index → copy (编辑用), Render Active 保持原始UV (渲染采样用)
            uv_layers.active_index = len(uv_layers) - 1
            copied += 1

        if copied == 0:
            self.report({'ERROR'}, "没有找到可处理的UV层")
            return {'CANCELLED'}

        self.report({'INFO'},
                    f"已创建 {copied} 个UV副本 — 现在可以手动调整UV布局，"
                    f"完成后使用「UV重定向渲染」")
        return {'FINISHED'}


class SHIYUME_OT_SmartUVRedirect(bpy.types.Operator):
    """Step 2: 基于当前 Active UV (已手动调整的副本) 进行重定向渲染。
    流程: Mesh to UV → Viewport Render → 删除原始UV → 设副本为RenderActive → 设置贴图到材质"""
    bl_idname = "shiyume.smart_uv_redirect"
    bl_label = "UV重定向渲染 (UV Redirect Render)"
    bl_options = {'REGISTER', 'UNDO'}

    avg_scale: bpy.props.BoolProperty(
        name="Average Islands Scale", default=True,
        description="等比缩放UV岛")
    unstack: bpy.props.BoolProperty(
        name="Unstack Islands", default=True,
        description="分离重叠UV岛")
    pack: bpy.props.BoolProperty(
        name="UVPackMaster Pack", default=True,
        description="使用UVPackMaster打包UV")
    assign_texture: bpy.props.BoolProperty(
        name="设置贴图到材质", default=True,
        description="将渲染出的贴图设置到选中网格的Principled BSDF Base Color")

    def execute(self, context):
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_meshes:
            self.report({'ERROR'}, "请至少选择一个网格对象")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # ── 检查: 确保每个mesh的active UV不是render active UV ──
        mesh_uv_info = {}  # mesh_data.name -> (render_uv_idx, active_copy_name)
        processed = set()

        for obj in selected_meshes:
            mesh_data = obj.data
            mn = mesh_data.name
            if mn in processed:
                continue
            processed.add(mn)

            uv_layers = mesh_data.uv_layers
            if not uv_layers or len(uv_layers) < 2:
                self.report({'WARNING'}, f"'{obj.name}' UV层不足2个, 跳过")
                continue

            render_uv_idx = 0
            for i, uv in enumerate(uv_layers):
                if uv.active_render:
                    render_uv_idx = i
                    break

            active_idx = uv_layers.active_index
            if active_idx == render_uv_idx:
                self.report({'WARNING'},
                            f"'{obj.name}' 的 Active UV 就是 Render Active UV，"
                            f"请先用「准备UV副本」创建副本并调整")
                continue

            active_uv = uv_layers[active_idx]
            try:
                copy_name = active_uv.name
            except:
                copy_name = f"UV{active_idx}"

            mesh_uv_info[mn] = (render_uv_idx, copy_name)

        if not mesh_uv_info:
            self.report({'ERROR'},
                        "没有可处理的对象。请先使用「准备UV副本」创建副本，"
                        "手动调整UV后再执行此操作")
            return {'CANCELLED'}

        need_edit = self.avg_scale or self.unstack or self.pack
        original_sync = context.scene.tool_settings.use_uv_select_sync

        if need_edit:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in selected_meshes:
                obj.select_set(True)
            context.view_layer.objects.active = selected_meshes[0]

            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.reveal()
            context.scene.tool_settings.use_uv_select_sync = True
            bpy.ops.mesh.select_all(action='SELECT')

        # ── Average Islands Scale ─────────────────────────────────
        if self.avg_scale:
            try:
                bpy.ops.uv.average_islands_scale()
            except Exception as e:
                self.report({'WARNING'}, f"Average Scale 失败: {e}")

        # ── Unstack Islands ───────────────────────────────────────
        if self.unstack:
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

        # ── UVPackMaster Pack ─────────────────────────────────────
        if self.pack:
            context.scene.tool_settings.use_uv_select_sync = True
            bpy.ops.mesh.select_all(action='SELECT')
            context.scene.tool_settings.use_uv_select_sync = False
            try:
                bpy.ops.uv.select_all(action='SELECT')
            except:
                pass
            self._try_uvpackmaster_pack(context)

        if need_edit:
            context.scene.tool_settings.use_uv_select_sync = original_sync

        # ── Mesh to UV ────────────────────────────────────────────
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

        # ── Viewport Render ───────────────────────────────────────
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

        # ── 清理展平对象 ──────────────────────────────────────────
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        for obj in flattened_objects:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if context.selected_objects:
            bpy.ops.object.delete()

        # ── UV交换: 删除原始UV, 设副本为Render Active ─────────────
        swapped = set()
        for obj in selected_meshes:
            if not obj or not obj.data:
                continue
            mn = obj.data.name
            if mn in swapped:
                continue
            swapped.add(mn)

            info = mesh_uv_info.get(mn)
            if not info:
                continue
            ridx, cname = info
            uv_layers = obj.data.uv_layers

            # 记住原始UV的名字
            orig_uv_name = ""
            if ridx < len(uv_layers):
                try:
                    orig_uv_name = uv_layers[ridx].name
                except:
                    pass
                uv_layers.remove(uv_layers[ridx])

            copy = uv_layers.get(cname)
            if copy:
                # 重命名为原始UV的名字
                if orig_uv_name:
                    copy.name = orig_uv_name
                copy.active_render = True
                uv_layers.active = copy

        # ── 设置贴图到材质 ────────────────────────────────────────
        if self.assign_texture and rendered_texture_path and os.path.exists(rendered_texture_path):
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

            self.report({'INFO'}, f"UV重定向完成 — 贴图: {rendered_texture_path}")
        else:
            self.report({'INFO'}, "UV重定向完成")

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
