"""高光椭球物体：低模外壳加细分修改器，只显示线框；外壳按目标半径预先补偿细分带来的收缩。

外壳是立方体细分后投到球面（没有极点），物体缩放始终是 1，半径写在外壳顶点里；摆放（位置、旋转）留在物体上给用户直接调。
线框显示只管实体视图；材质预览和渲染里引擎照样画物体的面，所以椭球对引擎的所有光线与光照探头都设成不可见，只剩线框叠加层。
"""

import bmesh
import bpy
import numpy as np

OBJECT_NAME = "HighlightEllipsoid"
MODIFIER_NAME = "Subdivision"
CAGE_CUTS = 3
VIEWPORT_LEVELS = 2
RENDER_LEVELS = 3
INVISIBLE_PROPERTIES = ("visible_camera", "visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow", "visible_raycast")
PROBE_HIDDEN_PROPERTIES = ("hide_probe_plane", "hide_probe_sphere", "hide_probe_volume")


def _build_cage(mesh, radii):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=CAGE_CUTS, use_grid_fill=True)
    for vertex in bm.verts:
        vertex.co.normalize()
        for axis in range(3):
            vertex.co[axis] *= radii[axis]
    for face in bm.faces:
        face.smooth = True
    bm.to_mesh(mesh)
    bm.free()


def _measured_radii(context, obj):
    context.view_layer.update()
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    points = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", points)
    evaluated.to_mesh_clear()
    return np.abs(points.reshape(-1, 3)).max(axis=0)


def fit(context, obj, placement):
    """按摆放重置位置、旋转和外壳；细分是仿射不变的，量一次收缩再按比例放大外壳就让细分后的半径等于目标。"""
    obj.location = placement.center
    obj.rotation_euler = placement.euler
    obj.scale = (1.0, 1.0, 1.0)
    target = np.asarray(placement.semi_axes, dtype=np.float64)
    _build_cage(obj.data, target)
    _build_cage(obj.data, target * target / _measured_radii(context, obj))


def _set(obj, name, value):
    if getattr(obj, name) != value:
        setattr(obj, name, value)


def show_as_wire(obj):
    """只剩线框：实体视图线框显示且穿透显示，材质预览与渲染里对引擎所有光线和光照探头不可见（面不画、不投影、不进反射）。
    只改和期望不同的属性，对账每隔半秒调一次也不会白白触发引擎重新同步。"""
    _set(obj, "display_type", 'WIRE')
    _set(obj, "show_in_front", True)
    for name in INVISIBLE_PROPERTIES:
        _set(obj, name, False)
    for name in PROBE_HIDDEN_PROPERTIES:
        _set(obj, name, True)


def create(context, placement, collection):
    mesh = bpy.data.meshes.new(OBJECT_NAME)
    obj = bpy.data.objects.new(OBJECT_NAME, mesh)
    collection.objects.link(obj)
    modifier = obj.modifiers.new(MODIFIER_NAME, 'SUBSURF')
    modifier.levels = VIEWPORT_LEVELS
    modifier.render_levels = RENDER_LEVELS
    show_as_wire(obj)
    fit(context, obj, placement)
    return obj


def usable(scene, obj):
    """椭球还在这个场景里（没被删、没被移出场景）并且是网格。"""
    return obj is not None and obj.type == 'MESH' and bpy.data.objects.get(obj.name) is obj and obj.name in scene.objects
