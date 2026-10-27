"""
Проверка импорта в Blender в фоновом режиме:

    blender --background --python tools/blender_check.py -- <файл.glb|obj> [превью.png]

Печатает число объектов, размеры, материалы и загруженные текстуры, ошибки импорта.
Если указан путь превью - рендерит картинку (Workbench, вид сбоку-спереди).
Код возврата 0 - импорт без ошибок.
"""
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv:
    print("CHECK: не указан файл")
    sys.exit(2)
path = Path(argv[0])
preview = argv[1] if len(argv) > 1 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    if path.suffix.lower() in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    else:
        bpy.ops.wm.obj_import(filepath=str(path))
except Exception as exc:  # noqa: BLE001
    print("CHECK: ОШИБКА ИМПОРТА:", exc)
    sys.exit(1)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
empties = [o for o in bpy.data.objects if o.type == "EMPTY"]
print(f"CHECK: объектов {len(bpy.data.objects)}, мешей {len(meshes)}, пустышек {len(empties)}")
lo = Vector((1e9,) * 3)
hi = Vector((-1e9,) * 3)
verts = tris = 0
for o in meshes:
    verts += len(o.data.vertices)
    tris += sum(len(p.vertices) - 2 for p in o.data.polygons)
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector((min(lo[i], w[i]) for i in range(3)))
        hi = Vector((max(hi[i], w[i]) for i in range(3)))
size = hi - lo
print(f"CHECK: вершин {verts}, треугольников {tris}")
print(f"CHECK: габариты Blender (X,Y,Z) = {size.x:.2f} x {size.y:.2f} x {size.z:.2f} м; min z = {lo.z:.2f}")
imgs = [i for i in bpy.data.images if i.name not in ("Render Result", "Viewer Node")]
ok = sum(1 for i in imgs if i.size[0] > 0 and i.size[1] > 0)
print(f"CHECK: материалов {len(bpy.data.materials)}, изображений {len(imgs)}, загружено {ok}")
for i in imgs:
    if i.size[0] == 0:
        print("CHECK: изображение не загрузилось:", i.name)
with_tex = sum(1 for m in bpy.data.materials if m.use_nodes and any(n.type == "TEX_IMAGE" for n in m.node_tree.nodes))
print(f"CHECK: материалов с текстурами {with_tex}")

# согласованность обхода граней и нормалей вершин из файла (должна быть ~100 %)
agree = total = 0
for o in meshes:
    me = o.data
    try:
        cn = me.corner_normals
    except AttributeError:
        break
    for p in me.polygons:
        n = sum((Vector(cn[li].vector) for li in p.loop_indices), Vector())
        total += 1
        if n.dot(p.normal) > 0:
            agree += 1
if total:
    print(f"CHECK: грани с нормалью по обходу, совпадающей с нормалью вершин: {100.0 * agree / total:.1f} %")

if preview:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.filepath = preview
    center = (lo + hi) / 2
    dist = max(size) * 1.6
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = center + Vector((dist * 0.8, -dist * 0.9, dist * 0.45))
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    bpy.ops.render.render(write_still=True)
    print("CHECK: превью сохранено:", preview)
print("CHECK: OK")
