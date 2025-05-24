import bpy, os, math
from mathutils import Vector

# 顶部变量：控制是否开启正交渲染和透视渲染
enable_ortho = True
enable_persp = True

# 缩放系数
ortho_scale = 1.05
persp_extra = 1.5

# 旋转步长：默认90度，即前后左右
yaw_step = 90
pitch_step = 30

scene = bpy.context.scene

# 分辨率设置：正方形 改这么高是为了之后生成半身和 脸部聚焦
scene.render.resolution_x = 4096
scene.render.resolution_y = 4096
scene.render.resolution_percentage = 100

# 输出文件夹
out_dir = bpy.path.abspath("//renders")
if not os.path.exists(out_dir):
    os.makedirs(out_dir)

# 渲染设置：使用 Workbench 引擎、无光照扁平渲染，保留贴图
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'FLAT'
scene.display.shading.color_type = 'TEXTURE'
scene.display.shading.use_scene_lights = False
scene.display.shading.use_scene_world = False

# --- 透明输出（新增三行） ---
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
# ---------------------------

# 相机设置：复用同名相机或创建
cam_name = "FlatCam"
cam_obj = scene.objects.get(cam_name)
if cam_obj and cam_obj.type == 'CAMERA':
    cam = cam_obj
    cam_data = cam.data
else:
    cam_data = bpy.data.cameras.new(cam_name)
    cam = bpy.data.objects.new(cam_name, cam_data)
    scene.collection.objects.link(cam)
scene.camera = cam

# 根据控制变量决定渲染模式列表
modes = []
if enable_ortho:
    modes.append('ORTHO')
if enable_persp:
    modes.append('PERSP')

# 找到场景所有根对象并逐个渲染
roots = [o for o in scene.objects if o.parent is None]
for arm in roots:
    # 隐藏所有物体，仅显示当前根对象及其子网格
    for o in scene.objects:
        o.hide_render = True
    arm.hide_render = False
    meshes = [c for c in arm.children_recursive if c.type == 'MESH']
    for m in meshes:
        m.hide_render = False

    # 计算包围盒中心和最大尺寸
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

    # 按照选定模式渲染
    for mode in modes:
        cam_data.type = mode
        if mode == 'ORTHO':
            cam_data.ortho_scale = max_dim * ortho_scale
            dist = max_dim * ortho_scale
        else:
            dist = max_dim * ortho_scale * persp_extra

        for yaw in range(0, 360, yaw_step):
            for pitch in (0, pitch_step, -pitch_step):
                phi = math.radians(90 - pitch)
                theta = math.radians(yaw)
                x = center.x + dist * math.sin(phi) * math.cos(theta)
                y = center.y + dist * math.sin(phi) * math.sin(theta)
                z = center.z + dist * math.cos(phi)
                cam.location = (x, y, z)

                # 朝向模型中心
                direction = center - cam.location
                cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

                # 渲染并保存
                scene.render.filepath = os.path.join(
                    out_dir,
                    f"{mode}_{yaw}_{pitch}_{arm.name}.png"
                )
                bpy.ops.render.render(write_still=True)
