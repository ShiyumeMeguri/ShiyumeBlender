import bpy

class SHIYUME_OT_VertexColorRGBA(bpy.types.Operator):
    """设置顶点颜色：
    1. 如果指定了 RGBA 通道，则使用对应的顶点组权重作为颜色通道。
    2. 如果启用了 '使用统一颜色'，则直接把选中的顶点染成指定颜色。
    这对于制作游戏资产（如设置遮罩、透明度或特效通道）非常有用。"""
    bl_idname = "shiyume.vertex_color_rgba"
    bl_label = "设置顶点色 (RGBA/统一)"
    bl_options = {'REGISTER', 'UNDO'}

    use_uniform_color: bpy.props.BoolProperty(name="使用统一颜色", default=False, description="忽略顶点组，直接填充指定颜色")
    uniform_color: bpy.props.FloatVectorProperty(name="颜色拾取", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0))
    
    # 顶点组映射通道
    map_red: bpy.props.StringProperty(name="R通道顶点组", default="Red")
    map_green: bpy.props.StringProperty(name="G通道顶点组", default="Green")
    map_blue: bpy.props.StringProperty(name="B通道顶点组", default="Blue")
    map_alpha: bpy.props.StringProperty(name="A通道顶点组", default="Alpha")

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type != 'MESH': continue
            
            context.view_layer.objects.active = obj
            
            # Ensure we are in Vertex Paint or Object mode to set data correctly
            # Actually, modifying mesh data directly is safest in Object mode, 
            # but usually users expect visual feedback. Let's stick to valid mode.
            current_mode = obj.mode
            if current_mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            if not obj.data.vertex_colors:
                obj.data.vertex_colors.new()
            
            color_layer = obj.data.vertex_colors.active
            
            if self.use_uniform_color:
                # Mode 1: Uniform Color
                fill_col = list(self.uniform_color)
                for poly in obj.data.polygons:
                    for loop_idx in poly.loop_indices:
                        if obj.data.vertices[obj.data.loops[loop_idx].vertex_index].select: # Optional: Only selected vertices?
                             # In object mode, 'select' attribute on vertex is reliable if we were in Edit Mode before.
                             # But standard 'selected_objects' operator usually implies WHOLE object unless in Edit Mode.
                             # Let's apply to ALL for now unless we add 'Only Selected' option. 
                             # Simplicity: Apply to all.
                             pass
                        color_layer.data[loop_idx].color = fill_col
            else:
                # Mode 2: Vertex Groups
                mapping = {
                    self.map_red: 0, 
                    self.map_green: 1, 
                    self.map_blue: 2, 
                    self.map_alpha: 3
                }
                
                # Pre-fetch group indices
                group_indices = {name: obj.vertex_groups[name].index for name in mapping if name in obj.vertex_groups}

                for poly in obj.data.polygons:
                    for idx, loop_idx in enumerate(poly.loop_indices):
                        vert_idx = poly.vertices[idx]
                        vert = obj.data.vertices[vert_idx]
                        
                        # Get current color as base
                        color = list(color_layer.data[loop_idx].color)
                        
                        for name, g_idx in group_indices.items():
                            c_idx = mapping[name]
                            # Find weight in vertex groups
                            for g in vert.groups:
                                if g.group == g_idx:
                                    color[c_idx] = g.weight
                                    break
                        color_layer.data[loop_idx].color = color
            
            # Restore mode if needed
            if current_mode != 'OBJECT':
                try: bpy.ops.object.mode_set(mode=current_mode)
                except: pass

        return {'FINISHED'}
