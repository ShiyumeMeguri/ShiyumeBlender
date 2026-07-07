"""模块化场景导出:唯一网格去重导出 FBX + RuriScene JSON 布局。"""

import json
import math
import os

import bpy
import mathutils


def _to_json_compatible(value):
    """把 Blender 侧类型递归转换成 JSON 可序列化的 Python 类型。"""
    import idprop
    if isinstance(value, (int, float, str, bool, type(None))):
        return value
    if hasattr(value, "to_list"):
        return value.to_list()
    if isinstance(value, (list, tuple)):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, (idprop.types.IDPropertyGroup, dict)):
        return {key: _to_json_compatible(value[key]) for key in value.keys()}
    if hasattr(value, "__iter__"):
        return [_to_json_compatible(item) for item in value]
    return str(value)


class SHIYUME_OT_ModularExport(bpy.types.Operator):
    """模块化导出:Entity/Scene 集合内每个唯一网格只导出一次 FBX
    (旋转变体自动识别复用),同时生成 .ruriscene JSON 描述场景布局。
    输出到环境变量 FractalPath 指向的工程目录"""
    bl_idname = "shiyume.modular_export"
    bl_label = "模块化导出 (RuriScene)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({'ERROR'}, "请先保存 .blend 文件")
            return {'CANCELLED'}

        # 环境变量取 FractalPath,Windows 下回退注册表
        fractal_path = os.environ.get("FractalPath")
        if not fractal_path and os.name == 'nt':
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    fractal_path, _ = winreg.QueryValueEx(key, "FractalPath")
            except Exception as error:
                print(f"注册表查询失败: {error}")

        if not fractal_path:
            self.report({'ERROR'}, "环境变量 'FractalPath' 未设置")
            return {'CANCELLED'}

        file_name = os.path.splitext(os.path.basename(blend_path))[0]

        model_root = os.path.join(fractal_path, "Assets", "RuriAssets", "Art", "Stage", file_name, "Models")
        scene_root = os.path.join(fractal_path, "Assets", "RuriAssets", "Art", "Scene", file_name)
        os.makedirs(model_root, exist_ok=True)
        os.makedirs(scene_root, exist_ok=True)

        self.report({'INFO'}, f"模型导出到 {model_root}")

        # 收集目标物体:Entity/Scene 集合优先,退回当前选择
        target_collections = ["Entity", "Scene"]
        valid_objects = []
        for collection_name in target_collections:
            collection = bpy.data.collections.get(collection_name)
            if collection:
                for obj in collection.objects:
                    if obj.type == 'MESH':
                        valid_objects.append((obj, collection_name))

        if not valid_objects:
            for obj in context.selected_objects:
                if obj.type == 'MESH':
                    category = obj.users_collection[0].name if obj.users_collection else "Misc"
                    valid_objects.append((obj, category))

        if not valid_objects:
            self.report({'ERROR'}, "没有可导出的网格(Entity/Scene 集合为空且未选中物体)")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')

        def unity_relative_path(path):
            return os.path.relpath(path, fractal_path).replace("\\", "/")

        def modifier_signature(obj):
            """修改器指纹:同网格不同修改器栈视为不同资源。"""
            modifiers = [modifier for modifier in obj.modifiers if modifier.show_render]
            if not modifiers:
                return "NOMOD"
            parts = []
            for modifier in modifiers:
                if modifier.type == 'ARRAY':
                    detail = f"{modifier.count}_{modifier.fit_type}_{modifier.constant_offset_displace}_{modifier.relative_offset_displace}"
                elif modifier.type == 'MIRROR':
                    detail = f"{modifier.use_axis}_{modifier.use_bisect_axis}_{modifier.use_mirror_merge}"
                elif modifier.type == 'BEVEL':
                    detail = f"{modifier.width}_{modifier.segments}_{modifier.profile}_{modifier.limit_method}"
                elif modifier.type == 'SOLIDIFY':
                    detail = f"{modifier.thickness}_{modifier.offset}"
                elif modifier.type == 'SUBSURF':
                    detail = f"{modifier.levels}_{modifier.render_levels}"
                else:
                    detail = modifier.name
                parts.append(f"{modifier.type}:{detail}")
            return "_".join(parts)

        def rotation_between(mesh_base, mesh_variant):
            """用前三个顶点构造基底,求 base → variant 的刚体旋转;不可解返回 None。"""
            if len(mesh_base.vertices) != len(mesh_variant.vertices):
                return None
            if len(mesh_base.vertices) < 3:
                return mathutils.Matrix.Identity(4)

            def basis(mesh):
                point_0 = mesh.vertices[0].co
                point_1 = mesh.vertices[1].co
                point_2 = mesh.vertices[2].co
                x_axis = (point_1 - point_0).normalized()
                normal = (point_1 - point_0).cross(point_2 - point_0).normalized()
                y_axis = x_axis.cross(normal).normalized()
                return mathutils.Matrix((x_axis, y_axis, normal)).transposed()

            basis_a = basis(mesh_base)
            basis_b = basis(mesh_variant)
            return (basis_b @ basis_a.inverted()).to_4x4()

        def rotation_matches(mesh_base, mesh_variant, rotation, samples=10):
            """抽样校验旋转矩阵是否把 base 顶点精确映射到 variant。"""
            count = len(mesh_base.vertices)
            if count <= samples:
                sample_indices = range(count)
            else:
                sample_indices = [index * count // samples for index in range(samples)]
            for index in sample_indices:
                mapped = rotation @ mesh_base.vertices[index].co
                if (mapped - mesh_variant.vertices[index].co).length > 0.001:
                    return False
            return True

        # 去重表:(顶点数, 面数, 修改器指纹) -> [{path, mesh_name, ref_mesh}]
        geometry_map = {}
        scene_json_items = []

        for obj, category in valid_objects:
            mesh_data = obj.data
            geometry_key = (len(mesh_data.vertices), len(mesh_data.polygons), modifier_signature(obj))

            export_path = ""
            export_mesh_name = ""
            instance_correction = mathutils.Matrix.Identity(4)
            found = False

            for info in geometry_map.setdefault(geometry_key, []):
                reference_mesh = info['ref_mesh']
                if reference_mesh == mesh_data:
                    export_path = info['path']
                    export_mesh_name = info['mesh_name']
                    found = True
                    break
                rotation = rotation_between(reference_mesh, mesh_data)
                if rotation and rotation_matches(reference_mesh, mesh_data, rotation):
                    export_path = info['path']
                    export_mesh_name = info['mesh_name']
                    instance_correction = rotation
                    found = True
                    break

            if not found:
                saved_matrix = obj.matrix_world.copy()
                obj.matrix_world = mathutils.Matrix.Identity(4)

                safe_name = obj.name.replace(".", "_").replace(":", "_")
                fbx_path = os.path.join(model_root, f"{safe_name}.fbx")

                obj.select_set(True)
                bpy.ops.export_scene.fbx(
                    filepath=fbx_path,
                    use_selection=True,
                    global_scale=1.0,
                    apply_scale_options='FBX_SCALE_ALL',
                    object_types={'MESH'},
                    use_mesh_modifiers=True,
                    mesh_smooth_type='OFF',
                    use_custom_props=True,
                    bake_anim=False,
                    axis_forward='-Z',
                    axis_up='Y',
                )
                obj.select_set(False)
                obj.matrix_world = saved_matrix

                info = {
                    'path': unity_relative_path(fbx_path),
                    'mesh_name': obj.name,
                    'ref_mesh': mesh_data,
                }
                geometry_map[geometry_key].append(info)
                export_path = info['path']
                export_mesh_name = info['mesh_name']

            # 世界变换 → Unity 坐标系(-90°X 修正 + 轴交换)
            final_matrix = obj.matrix_world @ instance_correction
            location = final_matrix.to_translation()
            rotation = final_matrix.to_quaternion()
            scale = final_matrix.to_scale()

            unity_correction = mathutils.Euler((math.radians(-90), 0, 0)).to_quaternion()
            rotation = rotation @ unity_correction

            scene_json_items.append({
                "name": obj.name,
                "type": category,
                "mesh_source_path": export_path,
                "mesh_sub_asset": export_mesh_name,
                "position": {"x": -location.x, "y": location.z, "z": -location.y},
                "rotation": {"x": -rotation.x, "y": rotation.z, "z": rotation.y, "w": -rotation.w},
                "scale": {"x": scale.x, "y": scale.z, "z": scale.y},
                "properties": {
                    key: _to_json_compatible(obj[key])
                    for key in obj.keys() if not key.startswith('_')
                },
            })

        scene_data = {
            "format_version": 1,
            "scene_name": file_name,
            "items": scene_json_items,
        }

        json_path = os.path.join(scene_root, f"{file_name}.ruriscene")
        with open(json_path, 'w', encoding='utf-8') as stream:
            json.dump(scene_data, stream, indent=4)

        self.report({'INFO'}, f"模块化导出完成,共 {len(scene_json_items)} 项")
        return {'FINISHED'}


classes = (
    SHIYUME_OT_ModularExport,
)
