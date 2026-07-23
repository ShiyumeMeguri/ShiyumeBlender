import bpy

class SHIYUME_OT_SortRootsX(bpy.types.Operator):
    """将选中的根对象（无父级）按 X 轴排序并等距排列"""
    bl_idname = "shiyume.sort_roots_x"
    bl_label = "X轴排列根对象"
    bl_options = {'REGISTER', 'UNDO'}

    spacing: bpy.props.FloatProperty(
        name="间距",
        default=1.0,
        min=0.0,
        description="相邻根对象之间的 X 轴间距（米）",
        unit='LENGTH',
    )

    def execute(self, context):
        roots = [obj for obj in context.selected_objects if obj.parent is None]
        if not roots:
            self.report({'WARNING'}, "没有选中根对象")
            return {'CANCELLED'}

        # 按当前 X 坐标排序
        roots.sort(key=lambda o: o.location.x)

        # 沿 X 轴等距放置
        for i, obj in enumerate(roots):
            obj.location.x = i * self.spacing

        self.report({'INFO'}, f"已排列 {len(roots)} 个根对象（间距 {self.spacing:.2f}m）")
        return {'FINISHED'}
