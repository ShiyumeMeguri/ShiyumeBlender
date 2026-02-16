import bpy
import bmesh
import os

# ─────────────────────────────────────────────────────────────
# 模块级状态, 在各个 Debug Step 之间共享数据
# ─────────────────────────────────────────────────────────────
_state = {
    "selected_mesh_names": [],   # 原始选中对象名列表
    "mesh_uv_info": {},          # mesh_data.name -> (render_uv_idx, copy_name)
    "flattened_names": [],       # mesh_to_uv 创建的临时对象名
    "rendered_texture_path": "", # viewport_render 输出的贴图路径
    "original_sync": False,      # 用户原始的 UV Sync 设置
}

def _get_selected_meshes():
    """从 _state 中恢复选中的网格对象列表"""
    return [bpy.data.objects[n] for n in _state["selected_mesh_names"]
            if n in bpy.data.objects and bpy.data.objects[n].type == 'MESH']

def _ensure_object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

def _reselect_meshes(context):
    """重新选中原始对象"""
    meshes = _get_selected_meshes()
    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes:
        obj.select_set(True)
    if meshes:
        context.view_layer.objects.active = meshes[0]
    return meshes


# ═══════════════════════════════════════════════════════════════
# Step 0: Init — 记录选中对象, 准备状态
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step0_Init(bpy.types.Operator):
    """[Debug] Step 0: 初始化 — 记录当前选中的网格对象"""
    bl_idname = "suvr.step0_init"
    bl_label = "Step 0: Init (记录选中)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            self.report({'ERROR'}, "请先选中网格对象")
            return {'CANCELLED'}

        _state["selected_mesh_names"] = [o.name for o in meshes]
        _state["mesh_uv_info"] = {}
        _state["flattened_names"] = []
        _state["rendered_texture_path"] = ""
        _state["original_sync"] = context.scene.tool_settings.use_uv_select_sync

        self.report({'INFO'}, f"Step 0 完成: 记录了 {len(meshes)} 个网格对象")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Step 1: 复制渲染激活UV → _UVCopy
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step1_CopyUV(bpy.types.Operator):
    """[Debug] Step 1: 复制RenderActive UV层 → _UVCopy, 设为Active"""
    bl_idname = "suvr.step1_copy_uv"
    bl_label = "Step 1: Copy UV"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()
        meshes = _get_selected_meshes()
        if not meshes:
            self.report({'ERROR'}, "没有记录的网格, 先运行 Step 0")
            return {'CANCELLED'}

        processed = set()
        info = {}

        for obj in meshes:
            mesh_data = obj.data
            mn = mesh_data.name
            if mn in processed:
                continue
            processed.add(mn)

            uv_layers = mesh_data.uv_layers
            if not uv_layers:
                self.report({'WARNING'}, f"'{obj.name}' 无UV层, 跳过")
                continue

            # 找 render active
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

            # 用原始UV名 + _Copy 命名
            try:
                orig_name = render_uv.name
                copy_name = orig_name + "_Copy"
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

            # ★ 关键: 设置 Active UV Map Index 到 copy (新UV总是在末尾)
            # active_index 决定 Blender 编辑/UV操作的目标层
            # active_render 保持指向原始UV → viewport_render 采样正确的贴图
            copy_idx = len(uv_layers) - 1
            uv_layers.active_index = copy_idx

            info[mn] = (render_uv_idx, copy_name)
            self.report({'INFO'},
                        f"  {obj.name}: UV[{render_uv_idx}] '{orig_name}' → "
                        f"'{copy_name}' (active_index={copy_idx})")

        _state["mesh_uv_info"] = info
        self.report({'INFO'}, f"Step 1 完成: 复制了 {len(info)} 个UV层")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Step 2: Average Islands Scale
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step2_AvgScale(bpy.types.Operator):
    """[Debug] Step 2: Average Islands Scale (开启Sync全选)"""
    bl_idname = "suvr.step2_avg_scale"
    bl_label = "Step 2: Average Islands Scale"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()
        meshes = _reselect_meshes(context)
        if not meshes:
            self.report({'ERROR'}, "无网格")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.reveal()
        context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.select_all(action='SELECT')

        try:
            bpy.ops.uv.average_islands_scale()
            self.report({'INFO'}, "Step 2 完成: Average Islands Scale OK")
        except Exception as e:
            self.report({'ERROR'}, f"Step 2 失败: {e}")

        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Step 3: Unstack Islands
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step3_Unstack(bpy.types.Operator):
    """[Debug] Step 3: Unstack Islands (关闭Sync)"""
    bl_idname = "suvr.step3_unstack"
    bl_label = "Step 3: Unstack Islands"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()
        meshes = _reselect_meshes(context)
        if not meshes:
            self.report({'ERROR'}, "无网格")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.reveal()

        # Sync ON → 全选 → Sync OFF (保留UV选择)
        context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.select_all(action='SELECT')
        context.scene.tool_settings.use_uv_select_sync = False
        try:
            bpy.ops.uv.select_all(action='SELECT')
        except:
            pass

        if hasattr(bpy.ops.uv, "toolkit_unstack_islands"):
            try:
                bpy.ops.uv.toolkit_unstack_islands()
                self.report({'INFO'}, "Step 3 完成: Unstack Islands OK")
            except Exception as e:
                self.report({'ERROR'}, f"Step 3 Unstack 失败: {e}")
        else:
            self.report({'WARNING'}, "Step 3: toolkit_unstack_islands 未找到")

        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Step 4: UVPackMaster Pack
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step4_Pack(bpy.types.Operator):
    """[Debug] Step 4: UVPackMaster Pack"""
    bl_idname = "suvr.step4_pack"
    bl_label = "Step 4: UVPackMaster Pack"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()
        meshes = _reselect_meshes(context)
        if not meshes:
            self.report({'ERROR'}, "无网格")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.reveal()

        # 确保全选
        context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.select_all(action='SELECT')
        context.scene.tool_settings.use_uv_select_sync = False
        try:
            bpy.ops.uv.select_all(action='SELECT')
        except:
            pass

        # 调用 Pack
        uv_area = None
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                uv_area = area
                break

        try:
            if hasattr(bpy.ops, "uvpackmaster3"):
                if uv_area:
                    with context.temp_override(area=uv_area):
                        bpy.ops.uvpackmaster3.pack(
                            mode_id='pack.single_tile',
                            pack_op_type='0'
                        )
                else:
                    bpy.ops.uvpackmaster3.pack(
                        mode_id='pack.single_tile',
                        pack_op_type='0'
                    )
                self.report({'INFO'}, "Step 4 完成: UVPackMaster Pack OK")
            else:
                self.report({'WARNING'}, "Step 4: uvpackmaster3 未找到")
        except Exception as e:
            self.report({'ERROR'}, f"Step 4 Pack 失败: {e}")

        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Step 5: Mesh to UV
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step5_MeshToUV(bpy.types.Operator):
    """[Debug] Step 5: Mesh to UV (生成展平Mesh)"""
    bl_idname = "suvr.step5_mesh_to_uv"
    bl_label = "Step 5: Mesh to UV"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()
        meshes = _reselect_meshes(context)
        if not meshes:
            self.report({'ERROR'}, "无网格")
            return {'CANCELLED'}

        try:
            bpy.ops.shiyume.mesh_to_uv()
        except Exception as e:
            self.report({'ERROR'}, f"Step 5 Mesh to UV 失败: {e}")
            return {'CANCELLED'}

        _state["flattened_names"] = [o.name for o in context.selected_objects]
        self.report({'INFO'}, f"Step 5 完成: 创建了 {len(_state['flattened_names'])} 个展平对象")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Step 6: Viewport Render
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step6_Render(bpy.types.Operator):
    """[Debug] Step 6: Viewport Render (渲染贴图)"""
    bl_idname = "suvr.step6_render"
    bl_label = "Step 6: Viewport Render"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()

        # 确保展平对象被选中
        flat_names = _state.get("flattened_names", [])
        if not flat_names:
            self.report({'ERROR'}, "没有展平对象, 先运行 Step 5")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        for name in flat_names:
            obj = bpy.data.objects.get(name)
            if obj:
                obj.select_set(True)
        if context.selected_objects:
            context.view_layer.objects.active = context.selected_objects[0]

        # 记录已有文件
        blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
        tex_dir = os.path.join(blend_dir, 'Textures') if blend_dir else ""
        existing = set()
        if tex_dir and os.path.exists(tex_dir):
            existing = set(os.listdir(tex_dir))

        try:
            bpy.ops.shiyume.render_viewport_texture()
        except Exception as e:
            self.report({'ERROR'}, f"Step 6 渲染失败: {e}")
            return {'CANCELLED'}

        # 找新文件
        rendered = ""
        if tex_dir and os.path.exists(tex_dir):
            new_files = set(os.listdir(tex_dir)) - existing
            uv_files = [f for f in new_files if f.endswith('.png') and 'UVRender' in f]
            if uv_files:
                rendered = os.path.join(tex_dir, uv_files[0])

        _state["rendered_texture_path"] = rendered
        self.report({'INFO'}, f"Step 6 完成: {rendered or '未找到渲染文件'}")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Step 7: 清理 + UV交换
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step7_Cleanup(bpy.types.Operator):
    """[Debug] Step 7: 删除展平对象, 删除原始UV, 设_UVCopy为RenderActive"""
    bl_idname = "suvr.step7_cleanup"
    bl_label = "Step 7: Cleanup + UV Swap"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()

        # 删除展平对象
        flat_names = _state.get("flattened_names", [])
        if flat_names:
            bpy.ops.object.select_all(action='DESELECT')
            for name in flat_names:
                obj = bpy.data.objects.get(name)
                if obj:
                    obj.select_set(True)
            if context.selected_objects:
                bpy.ops.object.delete()
            _state["flattened_names"] = []

        # UV交换
        info = _state.get("mesh_uv_info", {})
        swapped = 0
        for mesh_name, (ridx, cname) in info.items():
            md = bpy.data.meshes.get(mesh_name)
            if not md:
                continue
            uv_layers = md.uv_layers
            if ridx < len(uv_layers):
                uv_layers.remove(uv_layers[ridx])
            copy = uv_layers.get(cname)
            if copy:
                copy.active_render = True
                uv_layers.active = copy
                swapped += 1

        # 恢复sync
        context.scene.tool_settings.use_uv_select_sync = _state.get("original_sync", False)

        self.report({'INFO'}, f"Step 7 完成: 交换了 {swapped} 个UV层")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Step 8: 设置贴图到材质
# ═══════════════════════════════════════════════════════════════
class SUVR_OT_Step8_AssignTex(bpy.types.Operator):
    """[Debug] Step 8: 将渲染贴图设置到选中网格的 Principled BSDF Base Color"""
    bl_idname = "suvr.step8_assign_tex"
    bl_label = "Step 8: Assign Texture"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_object_mode()
        meshes = _get_selected_meshes()
        tex_path = _state.get("rendered_texture_path", "")

        if not tex_path or not os.path.exists(tex_path):
            self.report({'ERROR'}, f"未找到渲染贴图: {tex_path}")
            return {'CANCELLED'}

        img_name = os.path.splitext(os.path.basename(tex_path))[0]
        img = bpy.data.images.get(img_name)
        if img:
            img.reload()
        else:
            img = bpy.data.images.load(tex_path)
            img.name = img_name

        assigned = 0
        for obj in meshes:
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
                assigned += 1

        _reselect_meshes(context)
        self.report({'INFO'}, f"Step 8 完成: 设置了 {assigned} 个材质")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# 一键执行 (原始完整流程)
# ═══════════════════════════════════════════════════════════════
class SHIYUME_OT_SmartUVRedirect(bpy.types.Operator):
    """一键智能UV重定向 (完整流程)"""
    bl_idname = "shiyume.smart_uv_redirect"
    bl_label = "智能UV重定向 (Smart UV Redirect)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 依次执行所有步骤
        steps = [
            ("suvr.step0_init",     "Init"),
            ("suvr.step1_copy_uv",  "Copy UV"),
            ("suvr.step2_avg_scale","Avg Scale"),
            ("suvr.step3_unstack",  "Unstack"),
            ("suvr.step4_pack",     "Pack"),
            ("suvr.step5_mesh_to_uv","Mesh to UV"),
            ("suvr.step6_render",   "Render"),
            ("suvr.step7_cleanup",  "Cleanup"),
            ("suvr.step8_assign_tex","Assign Tex"),
        ]

        for op_id, label in steps:
            try:
                result = eval(f"bpy.ops.{op_id}()")
                if result == {'CANCELLED'}:
                    self.report({'ERROR'}, f"在 {label} 步骤中止")
                    return {'CANCELLED'}
            except Exception as e:
                self.report({'ERROR'}, f"{label} 出错: {e}")
                return {'CANCELLED'}

        self.report({'INFO'}, "智能UV重定向完成")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════
# Debug 面板
# ═══════════════════════════════════════════════════════════════
class SUVR_PT_DebugPanel(bpy.types.Panel):
    bl_label = "Smart UV Redirect Debug"
    bl_idname = "SUVR_PT_DebugPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'SUVR'

    def draw(self, context):
        layout = self.layout

        # 状态信息
        box = layout.box()
        box.label(text="状态:", icon='INFO')
        names = _state.get("selected_mesh_names", [])
        box.label(text=f"  记录对象: {len(names)}")
        box.label(text=f"  UV Info: {len(_state.get('mesh_uv_info', {}))}")
        box.label(text=f"  展平对象: {len(_state.get('flattened_names', []))}")
        tex = _state.get("rendered_texture_path", "")
        box.label(text=f"  贴图: {'✓' if tex else '—'}")

        layout.separator()

        # 完整执行
        layout.operator("shiyume.smart_uv_redirect", text="▶ 一键执行全部", icon='PLAY')

        layout.separator()
        layout.label(text="逐步执行:", icon='SEQUENCE')

        col = layout.column(align=True)
        col.operator("suvr.step0_init",      text="0. Init (记录选中)",      icon='CHECKBOX_HLT')
        col.operator("suvr.step1_copy_uv",   text="1. Copy UV",              icon='COPYDOWN')
        col.operator("suvr.step2_avg_scale",  text="2. Average Scale",        icon='UV_ISLANDSEL')
        col.operator("suvr.step3_unstack",    text="3. Unstack Islands",      icon='SNAP_VERTEX')
        col.operator("suvr.step4_pack",       text="4. UVPackMaster Pack",    icon='PACKAGE')
        col.separator()
        col.operator("suvr.step5_mesh_to_uv", text="5. Mesh to UV",          icon='MESH_UVSPHERE')
        col.operator("suvr.step6_render",     text="6. Viewport Render",      icon='RENDER_STILL')
        col.separator()
        col.operator("suvr.step7_cleanup",    text="7. Cleanup + UV Swap",    icon='TRASH')
        col.operator("suvr.step8_assign_tex", text="8. Assign Texture",       icon='TEXTURE')


# ═══════════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════════
_debug_classes = (
    SUVR_OT_Step0_Init,
    SUVR_OT_Step1_CopyUV,
    SUVR_OT_Step2_AvgScale,
    SUVR_OT_Step3_Unstack,
    SUVR_OT_Step4_Pack,
    SUVR_OT_Step5_MeshToUV,
    SUVR_OT_Step6_Render,
    SUVR_OT_Step7_Cleanup,
    SUVR_OT_Step8_AssignTex,
    SHIYUME_OT_SmartUVRedirect,
    SUVR_PT_DebugPanel,
)
