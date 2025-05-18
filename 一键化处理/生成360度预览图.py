import bpy, os, math
from mathutils import Vector

scene = bpy.context.scene

# 输出文件夹
out_dir = bpy.path.abspath("//renders")
if not os.path.exists(out_dir):
    os.makedirs(out_dir)

# 渲染设置：使用 Workbench 引擎、正交、无光照扁平渲染，保留贴图
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'FLAT'
scene.display.shading.color_type = 'TEXTURE'
scene.display.shading.use_scene_lights = False
scene.display.shading.use_scene_world = False

# 相机设置：复用同名相机或创建
cam_name = "FlatCam"
cam_obj = scene.objects.get(cam_name)
if cam_obj and cam_obj.type == 'CAMERA':
    cam = cam_obj
    cam_data = cam.data
else:
    cam_data = bpy.data.cameras.new(cam_name)
    cam_data.type = 'ORTHO'
    cam = bpy.data.objects.new(cam_name, cam_data)
    scene.collection.objects.link(cam)
scene.camera = cam
cam_data.type = 'ORTHO'

# 找到所有根骨骼并逐个渲染
roots = [o for o in scene.objects if o.type == 'ARMATURE' and o.parent is None]
for arm in roots:
    # 隐藏所有物体，仅显示当前骨骼及其子网格
    for o in scene.objects:
        o.hide_render = True
    arm.hide_render = False
    meshes = [c for c in arm.children_recursive if c.type == 'MESH']
    for m in meshes:
        m.hide_render = False

    # 计算选中网格的世界包围盒中心和最大尺寸
    coords = []
    for m in meshes:
        for v in m.bound_box:
            coords.append(m.matrix_world @ Vector(v))
    if coords:
        min_co = Vector((min(v.x for v in coords),
                         min(v.y for v in coords),
                         min(v.z for v in coords)))
        max_co = Vector((max(v.x for v in coords),
                         max(v.y for v in coords),
                         max(v.z for v in coords)))
        center = (min_co + max_co) / 2
        dims = max_co - min_co
        max_dim = max(dims.x, dims.y, dims.z)
    else:
        center = arm.location.copy()
        max_dim = 1

    cam_data.ortho_scale = max_dim * 2

    # 绕中心每45°一圈，三个俯仰角
    for yaw in range(0, 360, 45):
        for pitch in (0, 30, -30):
            phi = math.radians(90 - pitch)
            theta = math.radians(yaw)
            r = max_dim * 2
            x = center.x + r * math.sin(phi) * math.cos(theta)
            y = center.y + r * math.sin(phi) * math.sin(theta)
            z = center.z + r * math.cos(phi)
            cam.location = (x, y, z)

            # 朝向模型中心
            direction = center - cam.location
            cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

            # 渲染并保存
            scene.render.filepath = os.path.join(out_dir, f"{arm.name}_{yaw}_{pitch}.png")
            bpy.ops.render.render(write_still=True)
