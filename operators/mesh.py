import bpy
import bmesh
import math
import re

class SHIYUME_OT_AABBSelect(bpy.types.Operator):
    """Select objects based on AABB size threshold"""
    bl_idname = "shiyume.aabb_select"
    bl_label = "Select by AABB Size"
    bl_options = {'REGISTER', 'UNDO'}

    threshold: bpy.props.FloatProperty(name="Threshold (m)", default=1.0)

    def execute(self, context):
        for obj in context.scene.objects:
            dim = obj.dimensions
            length = math.sqrt(dim.x**2 + dim.y**2 + dim.z**2)
            obj.select_set(length < self.threshold)
        return {'FINISHED'}

class SHIYUME_OT_GridSort(bpy.types.Operator):
    """Arrange selected objects in a grid based on size similarity"""
    bl_idname = "shiyume.grid_sort"
    bl_label = "Grid Sort Objects"
    bl_options = {'REGISTER', 'UNDO'}

    margin: bpy.props.FloatProperty(name="Margin", default=0.1)

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

class SHIYUME_OT_CleanupVertexGroups(bpy.types.Operator):
    """Remove vertex groups that don't match bones (except safe list)"""
    bl_idname = "shiyume.cleanup_vgs"
    bl_label = "Cleanup Non-Bone Vertex Groups"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH': return {'CANCELLED'}
        
        arm = obj.find_armature()
        if not arm: return {'CANCELLED'}
        
        bone_names = set(b.name for b in arm.data.bones)
        safe_list = {'Alpha', 'Red', 'Blue', 'Green'}
        
        to_remove = [g.index for g in obj.vertex_groups if g.name not in bone_names and g.name not in safe_list]
        for idx in reversed(to_remove):
            obj.vertex_groups.remove(obj.vertex_groups[idx])
            
        return {'FINISHED'}

class SHIYUME_OT_WeightPrune(bpy.types.Operator):
    """Prune vertex weights to a maximum of 4 per vertex (lowest weights removed)"""
    bl_idname = "shiyume.weight_prune"
    bl_label = "Prune Weights (Max 4)"
    bl_options = {'REGISTER', 'UNDO'}

    max_groups: bpy.props.IntProperty(name="Max Groups", default=4)
    min_weight: bpy.props.FloatProperty(name="Min Weight", default=0.01)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}
            
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        
        dvert_layer = bm.verts.layers.deform.active
        if not dvert_layer:
            self.report({'ERROR'}, "No vertex groups found")
            bm.free()
            return {'CANCELLED'}
            
        for v in bm.verts:
            dvert = v[dvert_layer]
            if len(dvert) <= self.max_groups:
                continue
                
            # Get weights and sort
            weights = sorted(dvert.items(), key=lambda x: x[1], reverse=True)
            
            # Prune
            to_remove = weights[self.max_groups:]
            for group_idx, _ in to_remove:
                del dvert[group_idx]
                
            # Normalize
            total = sum(dvert.values())
            if total > 0:
                for group_idx in dvert.keys():
                    dvert[group_idx] /= total
                    
        bm.to_mesh(mesh)
        bm.free()
        
        self.report({'INFO'}, f"Pruned weights for {obj.name}")
        return {'FINISHED'}

class SHIYUME_OT_BatchRename(bpy.types.Operator):
    """Batch rename objects and materials (Kazaniwa standard)"""
    bl_idname = "shiyume.batch_rename"
    bl_label = "Batch Rename (Kazaniwa)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 1. Rename Objects
        for obj in context.selected_objects:
            # Remove .000 suffixes
            name = re.sub(r'\.\d+$', '', obj.name)
            if obj.type == 'MESH':
                if not name.startswith("Mesh_"):
                    obj.name = "Mesh_" + name
                else:
                    obj.name = name
            elif obj.type == 'ARMATURE':
                if not name.startswith("Arm_"):
                    obj.name = "Arm_" + name
                else:
                    obj.name = name
            
            # 2. Rename Materials
            if obj.type == 'MESH':
                for slot in obj.material_slots:
                    if slot.material:
                        mat = slot.material
                        mat_name = re.sub(r'\.\d+$', '', mat.name)
                        if not mat_name.startswith("Mat_"):
                            mat.name = "Mat_" + mat_name
                        else:
                            mat.name = mat_name
        
        self.report({'INFO'}, "Batch renamed objects and materials")
        return {'FINISHED'}

class SHIYUME_OT_MaterialLinkObject(bpy.types.Operator):
    """Set material link to 'OBJECT' for all selected mesh objects"""
    bl_idname = "shiyume.mat_link_object"
    bl_label = "Link Material to Object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type != 'MESH': continue
            for slot in obj.material_slots:
                mat = slot.material
                slot.link = 'OBJECT'
                if mat: slot.material = mat
        return {'FINISHED'}

classes = (
    SHIYUME_OT_AABBSelect,
    SHIYUME_OT_GridSort,
    SHIYUME_OT_CleanupVertexGroups,
    SHIYUME_OT_WeightPrune,
    SHIYUME_OT_BatchRename,
    SHIYUME_OT_MaterialLinkObject,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
