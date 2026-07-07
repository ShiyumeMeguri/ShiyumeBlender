"""UV 重定向两步工作流:先复制渲染 UV 供手动调整,再一键烘焙贴图并交换 UV。"""

import os

import bpy


class SHIYUME_OT_PrepareUVCopy(bpy.types.Operator):
    """第一步:把渲染激活 UV 复制为 {原名}_Copy 并设为编辑激活。
    之后手动调整副本布局(展开/打包等),完成后执行「UV重定向渲染」"""
    bl_idname = "shiyume.prepare_uv_copy"
    bl_label = "准备UV副本"
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
            mesh = obj.data
            if mesh.name in processed:
                continue
            processed.add(mesh.name)

            uv_layers = mesh.uv_layers
            if not uv_layers:
                self.report({'WARNING'}, f"'{obj.name}' 没有 UV 层,跳过")
                continue
            if len(uv_layers) >= 8:
                self.report({'WARNING'}, f"'{obj.name}' UV 层已满(8),跳过")
                continue

            # 渲染激活 UV;没有标记时退回编辑激活
            render_index = next(
                (index for index, layer in enumerate(uv_layers) if layer.active_render),
                uv_layers.active_index,
            )
            render_layer = uv_layers[render_index]

            # 命名 {原名}_Copy,去掉已有 _Copy 后缀防止叠加
            base_name = render_layer.name
            while base_name.endswith("_Copy"):
                base_name = base_name[:-5]
            copy_name = base_name + "_Copy"

            existing = uv_layers.get(copy_name)
            if existing:
                uv_layers.remove(existing)

            # do_init 会复制"编辑激活"层的数据:先把激活切到渲染层再新建
            uv_layers.active_index = render_index
            new_layer = uv_layers.new(name=copy_name, do_init=True)
            if not new_layer:
                continue

            # 编辑激活 → 副本;渲染激活保持原始 UV(渲染采样用)
            uv_layers.active_index = len(uv_layers) - 1
            copied += 1

        if copied == 0:
            self.report({'ERROR'}, "没有找到可处理的 UV 层")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"已创建 {copied} 个 UV 副本 — 手动调整布局后执行「UV重定向渲染」",
        )
        return {'FINISHED'}


class SHIYUME_OT_SmartUVRedirect(bpy.types.Operator):
    """第二步:基于当前编辑激活 UV(已手动调整的副本)重定向渲染。
    流程:网格UV同步(拆分副本) → UV渲染贴图 → 删除原始 UV →
    副本转正为渲染激活 → 新贴图接入材质 Base Color"""
    bl_idname = "shiyume.smart_uv_redirect"
    bl_label = "UV重定向渲染"
    bl_options = {'REGISTER', 'UNDO'}

    avg_scale: bpy.props.BoolProperty(
        name="等比缩放孤岛", default=True,
        description="执行 Average Islands Scale 统一各孤岛纹素密度",
    )
    unstack: bpy.props.BoolProperty(
        name="分离重叠孤岛", default=True,
        description="调用 UV Toolkit 的 Unstack Islands(未安装则跳过)",
    )
    pack: bpy.props.BoolProperty(
        name="UVPackmaster 打包", default=True,
        description="调用 UVPackmaster 3 打包(未安装则跳过)",
    )
    assign_texture: bpy.props.BoolProperty(
        name="贴图接入材质", default=True,
        description="把渲染出的贴图接到选中网格材质的 Principled BSDF Base Color",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        column = layout.column(heading="打包流程")
        column.prop(self, "avg_scale")
        column.prop(self, "unstack")
        column.prop(self, "pack")
        layout.prop(self, "assign_texture")

    def execute(self, context):
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_meshes:
            self.report({'ERROR'}, "请至少选择一个网格对象")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 前置检查:每个网格的编辑激活 UV 必须不是渲染激活 UV(即已做过副本)
        mesh_uv_info = {}  # mesh名 -> (渲染UV下标, 副本名)
        processed = set()

        for obj in selected_meshes:
            mesh = obj.data
            if mesh.name in processed:
                continue
            processed.add(mesh.name)

            uv_layers = mesh.uv_layers
            if not uv_layers or len(uv_layers) < 2:
                self.report({'WARNING'}, f"'{obj.name}' UV 层不足 2 个,跳过")
                continue

            render_index = next(
                (index for index, layer in enumerate(uv_layers) if layer.active_render),
                0,
            )
            active_index = uv_layers.active_index
            if active_index == render_index:
                self.report(
                    {'WARNING'},
                    f"'{obj.name}' 的编辑激活 UV 就是渲染激活 UV,请先执行「准备UV副本」",
                )
                continue

            mesh_uv_info[mesh.name] = (render_index, uv_layers[active_index].name)

        if not mesh_uv_info:
            self.report({'ERROR'}, "没有可处理的对象。请先「准备UV副本」并手动调整后再执行")
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

        # ── 等比缩放孤岛 ─────────────────────────────────────────
        if self.avg_scale:
            try:
                bpy.ops.uv.average_islands_scale()
            except Exception as error:
                self.report({'WARNING'}, f"Average Scale 失败: {error}")

        # ── 分离重叠孤岛 ─────────────────────────────────────────
        if self.unstack:
            bpy.ops.mesh.select_all(action='SELECT')
            context.scene.tool_settings.use_uv_select_sync = False
            try:
                bpy.ops.uv.select_all(action='SELECT')
            except Exception:
                pass
            if hasattr(bpy.ops.uv, "toolkit_unstack_islands"):
                try:
                    bpy.ops.uv.toolkit_unstack_islands()
                except Exception as error:
                    self.report({'WARNING'}, f"Unstack 失败: {error}")

        # ── UVPackmaster 打包 ────────────────────────────────────
        if self.pack:
            context.scene.tool_settings.use_uv_select_sync = True
            bpy.ops.mesh.select_all(action='SELECT')
            context.scene.tool_settings.use_uv_select_sync = False
            try:
                bpy.ops.uv.select_all(action='SELECT')
            except Exception:
                pass
            self._try_uvpackmaster_pack(context)

        if need_edit:
            context.scene.tool_settings.use_uv_select_sync = original_sync

        # ── 网格UV同步(拆分副本) ────────────────────────────────
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_meshes:
            obj.select_set(True)
        context.view_layer.objects.active = selected_meshes[0]

        try:
            bpy.ops.shiyume.mesh_uv_morph(mode='COPY')
        except Exception as error:
            self.report({'ERROR'}, f"网格UV同步失败: {error}")
            return {'CANCELLED'}

        flattened_objects = list(context.selected_objects)

        # ── UV 渲染贴图 ──────────────────────────────────────────
        blend_directory = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
        texture_directory = os.path.join(blend_directory, 'Textures') if blend_directory else ""
        existing_files = set()
        if texture_directory and os.path.exists(texture_directory):
            existing_files = set(os.listdir(texture_directory))

        try:
            bpy.ops.shiyume.render_uv_texture(source='SELECTED', engine='WORKBENCH')
        except Exception as error:
            self.report({'WARNING'}, f"UV 渲染失败: {error}")

        rendered_texture_path = ""
        if texture_directory and os.path.exists(texture_directory):
            new_files = set(os.listdir(texture_directory)) - existing_files
            candidates = [name for name in new_files if name.endswith('.png') and 'UVRender' in name]
            if candidates:
                rendered_texture_path = os.path.join(texture_directory, candidates[0])

        # ── 清理展平副本 ─────────────────────────────────────────
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        for obj in flattened_objects:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if context.selected_objects:
            bpy.ops.object.delete()

        # ── UV 交换:删除原始 UV,副本转正 ───────────────────────
        swapped = set()
        for obj in selected_meshes:
            if not obj or not obj.data:
                continue
            mesh = obj.data
            if mesh.name in swapped:
                continue
            swapped.add(mesh.name)

            info = mesh_uv_info.get(mesh.name)
            if not info:
                continue
            render_index, copy_name = info
            uv_layers = mesh.uv_layers

            original_name = ""
            if render_index < len(uv_layers):
                original_name = uv_layers[render_index].name
                uv_layers.remove(uv_layers[render_index])

            copy_layer = uv_layers.get(copy_name)
            if copy_layer:
                if original_name:
                    copy_layer.name = original_name
                copy_layer.active_render = True
                uv_layers.active = copy_layer

        # ── 贴图接入材质 ─────────────────────────────────────────
        if self.assign_texture and rendered_texture_path and os.path.exists(rendered_texture_path):
            image_name = os.path.splitext(os.path.basename(rendered_texture_path))[0]
            image = bpy.data.images.get(image_name)
            if image:
                image.reload()
            else:
                image = bpy.data.images.load(rendered_texture_path)
                image.name = image_name

            for obj in selected_meshes:
                if not obj.data.materials:
                    continue
                for material in obj.data.materials:
                    if not material or not material.use_nodes:
                        continue
                    tree = material.node_tree
                    principled = next(
                        (node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED'),
                        None,
                    )
                    if not principled:
                        continue
                    base_color = principled.inputs.get("Base Color")
                    if not base_color:
                        continue
                    texture_node = None
                    if base_color.links:
                        linked = base_color.links[0].from_node
                        if linked.type == 'TEX_IMAGE':
                            texture_node = linked
                    if not texture_node:
                        texture_node = tree.nodes.new('ShaderNodeTexImage')
                        texture_node.location = (principled.location.x - 300, principled.location.y)
                        tree.links.new(texture_node.outputs['Color'], base_color)
                    texture_node.image = image

            self.report({'INFO'}, f"UV 重定向完成 — 贴图: {rendered_texture_path}")
        else:
            self.report({'INFO'}, "UV 重定向完成")

        # 恢复选择
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected_meshes:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if selected_meshes:
            context.view_layer.objects.active = selected_meshes[0]

        return {'FINISHED'}

    def _try_uvpackmaster_pack(self, context):
        uv_area = next(
            (area for area in context.screen.areas if area.type == 'IMAGE_EDITOR'),
            None,
        )

        def call_pack():
            if hasattr(bpy.ops, "uvpackmaster3"):
                bpy.ops.uvpackmaster3.pack(mode_id='pack.single_tile', pack_op_type='0')
                return True
            return False

        try:
            if uv_area:
                with context.temp_override(area=uv_area):
                    return call_pack()
            return call_pack()
        except Exception as error:
            self.report({'WARNING'}, f"UVPackmaster 打包失败: {error}")
            return False


classes = (
    SHIYUME_OT_PrepareUVCopy,
    SHIYUME_OT_SmartUVRedirect,
)
