import bpy

class SHIYUME_OT_ClearEmpty(bpy.types.Operator):
    """Clear Empty objects that have no mesh descendants"""
    bl_idname = "shiyume.clear_empty"
    bl_label = "Clear Empty Objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Collect all empty objects in the scene
        all_objects = context.scene.objects
        empty_objects = [obj for obj in all_objects if obj.type == 'EMPTY']
        
        objects_to_remove = []

        def has_mesh_descendant(obj, visited):
            if obj in visited:
                return False
            visited.add(obj)
            
            # Direct children check
            children = obj.children
            for child in children:
                if child.type == 'MESH':
                    return True
                # Recursive check
                if has_mesh_descendant(child, visited):
                    return True
            return False

        for empty_obj in empty_objects:
            # We strictly check for MESH descendants.
            # If an Empty has only other Empties or nothing as children, and none of those have meshes, it's a candidate for deletion.
            visited = set()
            if not has_mesh_descendant(empty_obj, visited):
                objects_to_remove.append(empty_obj)

        if not objects_to_remove:
            self.report({'INFO'}, "No empty objects found to clear.")
            return {'CANCELLED'}

        count = len(objects_to_remove)
        
        # Determine removal order to avoid orphan issues if parents are removed first?
        # Actually bpy.data.objects.remove handles it, but safer to loop.
        # However, deleting a parent unlinks children. Ideally we want to delete them all.
        # Since we identified them as not having mesh content, deleting them is safe.
        
        for obj in objects_to_remove:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except ReferenceError:
                # Already removed?
                pass

        self.report({'INFO'}, f"Removed {count} empty objects.")
        return {'FINISHED'}
