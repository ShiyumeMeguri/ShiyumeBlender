import bpy
import math

class SHIYUME_OT_GridSort(bpy.types.Operator):
    """将选中的物体按照尺寸排序并在二维平面上排列成网格。
    用于整理散乱的资产，方便浏览和检查。"""
    bl_idname = "shiyume.grid_sort"
    bl_label = "网格化排列物体"
    bl_options = {'REGISTER', 'UNDO'}

    margin: bpy.props.FloatProperty(name="间距", default=0.1, description="物体之间的间隔距离")

    def execute(self, context):
        objs = context.selected_objects
        if not objs: return {'CANCELLED'}
        
        objs.sort(key=lambda o: math.sqrt(o.dimensions.x**2 + o.dimensions.y**2 + o.dimensions.z**2))
        
        grid_size = math.ceil(math.sqrt(len(objs)))
        cur_x = 0.0
        cur_y = 0.0
        row_max_h = 0.0
        
        for i, obj in enumerate(objs):
            max_dim = max(obj.dimensions.x, obj.dimensions.y)
            if i % grid_size == 0 and i != 0:
                cur_x = 0.0
                cur_y += row_max_h + self.margin
                row_max_h = 0.0
            
            obj.location.x = cur_x + max_dim / 2.0
            obj.location.y = cur_y + max_dim / 2.0
            row_max_h = max(row_max_h, max_dim)
            cur_x += max_dim + self.margin
            
        return {'FINISHED'}
