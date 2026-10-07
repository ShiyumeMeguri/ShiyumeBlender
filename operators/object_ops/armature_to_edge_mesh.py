import bpy
from mathutils import Matrix


def _ordered_bones(armature_data):
    ordered = []
    stack = [bone for bone in reversed(armature_data.bones) if bone.parent is None]
    while stack:
        bone = stack.pop()
        ordered.append(bone)
        stack.extend(reversed(bone.children))
    return ordered


def _is_displayed(armature, bone):
    if armature.pose.bones[bone.name].hide:
        return False
    if len(bone.collections) == 0:
        return True
    return any(collection.is_visible_effectively for collection in bone.collections)


def _displayed_ancestor(bone, displayed):
    ancestor = bone.parent
    while ancestor is not None and ancestor.name not in displayed:
        ancestor = ancestor.parent
    return ancestor


def _build_graph(armature, merge_distance, bridge_gaps):
    positions = []
    members = {}
    edges = []
    tail_index = {}
    ordered = _ordered_bones(armature.data)
    displayed = {bone.name for bone in ordered if _is_displayed(armature, bone)}
    for bone in ordered:
        if bone.name not in displayed:
            continue
        parent = _displayed_ancestor(bone, displayed)
        head = bone.head_local
        connected = bone.use_connect and parent is bone.parent
        if parent is not None and (connected or (head - parent.tail_local).length <= merge_distance):
            head_index = tail_index[parent.name]
        else:
            head_index = len(positions)
            positions.append(head.copy())
            if parent is not None and bridge_gaps:
                edges.append((tail_index[parent.name], head_index))
        bone_tail_index = len(positions)
        positions.append(bone.tail_local.copy())
        members[bone.name] = [head_index, bone_tail_index]
        tail_index[bone.name] = bone_tail_index
        edges.append((head_index, bone_tail_index))
    return positions, members, edges


def _assign_bone_groups(mesh_object, members):
    for bone_name, vertex_indices in members.items():
        mesh_object.vertex_groups.new(name=bone_name).add(vertex_indices, 1.0, 'REPLACE')


class SHIYUME_OT_ArmatureToEdgeMesh(bpy.types.Operator):
    """把选中骨架里当前显示的骨骼（未隐藏且所在骨骼集合可见）各生成一条边（head→tail），父子相连处共用顶点，骨骼链连成折线网格"""
    bl_idname = "shiyume.armature_to_edge_mesh"
    bl_label = "骨架转边网格"
    bl_options = {'REGISTER', 'UNDO'}

    merge_distance: bpy.props.FloatProperty(
        name="合并距离",
        description="子骨骼 head 与父骨骼 tail 相距不超过此值时视为相连、共用顶点（骨架局部空间）",
        default=1e-4,
        min=0.0,
        precision=6,
    )
    bridge_gaps: bpy.props.BoolProperty(
        name="补连父子断口",
        description="子骨骼未与父骨骼相连时，额外补一条父 tail → 子 head 的边，整棵骨骼树连成一体",
        default=False,
    )
    bind_to_armature: bpy.props.BoolProperty(
        name="绑定到骨架",
        description="以骨骼名建顶点组，父级到骨架并加骨架修改器，网格随姿态运动",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(
            selected.type == 'ARMATURE' for selected in context.selected_objects)

    def execute(self, context):
        armatures = [selected for selected in context.selected_objects if selected.type == 'ARMATURE']
        created = []
        for armature in armatures:
            positions, members, edges = _build_graph(armature, self.merge_distance, self.bridge_gaps)
            if not edges:
                continue
            mesh = bpy.data.meshes.new(f"{armature.name}_Edges")
            mesh.from_pydata(positions, edges, [])
            mesh.update()
            mesh_object = bpy.data.objects.new(mesh.name, mesh)
            collections = armature.users_collection or (context.scene.collection,)
            collections[0].objects.link(mesh_object)
            _assign_bone_groups(mesh_object, members)
            if self.bind_to_armature:
                mesh_object.parent = armature
                mesh_object.matrix_parent_inverse = Matrix.Identity(4)
                mesh_object.matrix_basis = Matrix.Identity(4)
                modifier = mesh_object.modifiers.new(name="Armature", type='ARMATURE')
                modifier.object = armature
            else:
                mesh_object.matrix_world = armature.matrix_world.copy()
            created.append(mesh_object)

        if not created:
            self.report({'WARNING'}, "选中的骨架里没有当前显示的骨骼")
            return {'CANCELLED'}

        for selected in context.selected_objects:
            selected.select_set(False)
        for mesh_object in created:
            mesh_object.select_set(True)
        context.view_layer.objects.active = created[-1]
        self.report({'INFO'}, f"已生成 {len(created)} 个边网格")
        return {'FINISHED'}
