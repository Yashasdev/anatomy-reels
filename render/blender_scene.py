"""Render the 3D layer of a reel: one organ model turning slowly, one part lit up. Runs inside Blender:

    blender -b --factory-startup --python render/blender_scene.py -- '<json spec>'

spec: {"model": "assets/models/heart.blend", "out": "out/x/frames", "frames": 360, "fps": 15,
       "highlight": "Left ventricle", "engine": "BLENDER_EEVEE_NEXT", "width": 1080, "height": 1920}
Frames are written as transparent PNGs; reels/compose.py puts the text, choices and captions over them.
"""

import json
import math
import sys

import bpy
import mathutils

spec = json.loads(sys.argv[sys.argv.index("--") + 1])
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

with bpy.data.libraries.load(spec["model"]) as (src, dst):
    dst.objects = src.objects
# solid parts only: the atlas also carries outline markers (".j") and cutting planes
parts = [o for o in dst.objects if o and o.type == "MESH" and not o.name.endswith(".j") and max(o.dimensions) > 0.01
         and not o.name.startswith("Cross Section")]
for o in parts:
    scene.collection.objects.link(o)
    o.hide_render = o.hide_viewport = False  # the atlas saves most parts hidden
    import bmesh  # some atlas parts are saved inside out, which renders them black
    bm = bmesh.new(); bm.from_mesh(o.data)
    if o.name in ("Stomach", "Duodenum"):  # cap the open ends (where the esophagus and intestine attach)
        bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(o.data); bm.free()
bpy.context.view_layer.update()


def material(name, rgb, roughness=0.45, coat=0.35):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = roughness
    b.inputs["Coat Weight"].default_value = coat
    return m


# colors by part name (first match wins), so each organ reads as what it is
BONE = (0.82, 0.76, 0.62)
COLORS = [("leaflet", (0.80, 0.68, 0.50)), ("papillary", (0.80, 0.68, 0.50)),
          ("muscle", (0.30, 0.03, 0.04)), ("Adductor", (0.30, 0.03, 0.04)), ("Tensor", (0.30, 0.03, 0.04)),
          ("cartilage", (0.70, 0.78, 0.84)), ("incisor", (0.93, 0.90, 0.80)), ("canine", (0.93, 0.90, 0.80)),
          ("molar", (0.93, 0.90, 0.80)), ("Sclera", (0.92, 0.90, 0.88)), ("Iris", (0.30, 0.18, 0.10)),
          ("Cornea", (0.85, 0.92, 1.00)), ("Lens", (0.90, 0.88, 0.70)),
          ("Femur", BONE), ("Patella", BONE), ("Tibia", BONE), ("Fibula", BONE), ("Talus", BONE), ("Calcaneus", BONE),
          ("metatarsal", BONE), ("metacarpal", BONE), ("phalanx", BONE), ("Sacrum", BONE), ("Coccyx", BONE),
          ("Vertebra", BONE), ("Atlas", BONE), ("Axis", BONE), (" rib", BONE), ("sternum", BONE), ("Xiphoid", BONE),
          ("lung", (0.62, 0.22, 0.24)), ("Trachea", (0.75, 0.62, 0.55)),
          ("Liver", (0.28, 0.05, 0.04)), ("Gallbladder", (0.20, 0.35, 0.12)), ("Stomach", (0.62, 0.30, 0.28)),
          ("Pancreas", (0.78, 0.58, 0.38)), ("Spleen", (0.32, 0.06, 0.12)), ("Duodenum", (0.60, 0.36, 0.30)),
          ("colon", (0.55, 0.32, 0.28)),
          ("bone", (0.82, 0.76, 0.62)), ("Mandible", (0.82, 0.76, 0.62)), ("Maxilla", (0.82, 0.76, 0.62)),
          ("Vomer", (0.82, 0.76, 0.62)), ("Humerus", (0.82, 0.76, 0.62)), ("Radius", (0.82, 0.76, 0.62)),
          ("Ulna", (0.82, 0.76, 0.62)), ("Scapula", (0.82, 0.76, 0.62)), ("Clavicle", (0.82, 0.76, 0.62)),
          ("concha", (0.82, 0.76, 0.62))]
muscle = material("muscle", (0.30, 0.03, 0.04))
lit = material("lit", (0.30, 0.85, 0.02), roughness=0.35)
cache = {}
for o in parts:
    o.data.materials.clear()
    hl = spec.get("highlight") or []
    if o.name in (hl if isinstance(hl, list) else [hl]):
        o.data.materials.append(lit)
        continue
    rgb = next((c for key, c in COLORS if key.lower() in o.name.lower()), None)
    if rgb is None:
        o.data.materials.append(muscle)
        continue
    if o.name.split(".")[0] in ("Cornea", "Lens"):  # clear in life; left out so the iris shows
        o.hide_render = True
        continue
    if rgb not in cache:
        cache[rgb] = material(f"m{len(cache)}", rgb, roughness=0.6 if rgb[0] > 0.8 else 0.45)
    o.data.materials.append(cache[rgb])

points = [o.matrix_world @ mathutils.Vector(c) for o in parts for c in o.bound_box]
lo = mathutils.Vector([min(p[i] for p in points) for i in range(3)])
hi = mathutils.Vector([max(p[i] for p in points) for i in range(3)])
center, size = (lo + hi) / 2, max(hi - lo)
if spec.get("focus"):  # small parts of a big region: turn around the glowing part and frame it (with a small distance)
    hl = set(spec.get("highlight") if isinstance(spec.get("highlight"), list) else [spec.get("highlight")])
    pts = [o.matrix_world @ mathutils.Vector(c) for o in parts if o.name in hl for c in o.bound_box]
    if pts:
        center = (mathutils.Vector([min(p[i] for p in pts) for i in range(3)])
                  + mathutils.Vector([max(p[i] for p in pts) for i in range(3)])) / 2

pivot = bpy.data.objects.new("pivot", None)
scene.collection.objects.link(pivot)
pivot.location = center
bpy.context.view_layer.update()
for o in parts:
    o.parent = pivot
    o.matrix_parent_inverse = pivot.matrix_world.inverted()

frames, fps = spec["frames"], spec.get("fps", 15)
turn = spec.get("degrees_per_second", 30)  # a slow, steady turn
pivot.rotation_euler = (0, 0, math.radians(spec.get("start_degrees", -20)))
pivot.keyframe_insert("rotation_euler", frame=1)
pivot.rotation_euler = (0, 0, math.radians(spec.get("start_degrees", -20) + turn * frames / fps))
pivot.keyframe_insert("rotation_euler", frame=frames + 1)  # frame k sits at start + turn * (k - 1) / fps, so a full turn loops
for fc in pivot.animation_data.action.fcurves:
    for k in fc.keyframe_points:
        k.interpolation = "LINEAR"

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
cam.data.lens = 85
cam.location = center + mathutils.Vector((0, -size * spec.get("distance", 6.0), size * 0.4))
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.location.z -= size * spec.get("lift", 0.0)  # positive lift moves the organ up in the frame
scene.camera = cam

for name, offset, power in [("key", (-1, -1.2, 1.2), 25), ("fill", (1.2, -0.8, 0.3), 8), ("rim", (0.3, 1.5, 1), 22)]:
    light = bpy.data.lights.new(name, "AREA")
    light.size = size
    v = mathutils.Vector(offset) * size * 2.5
    light.energy = spec.get("light", 0.55) * power * v.length ** 2 / 0.36  # same brightness whatever the organ's real size
    obj = bpy.data.objects.new(name, light)
    scene.collection.objects.link(obj)
    obj.location = center + v
    obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()

scene.world = bpy.data.worlds.new("world")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
scene.render.engine = spec.get("engine", "BLENDER_EEVEE_NEXT")
if scene.render.engine == "CYCLES":  # GitHub's machines have no graphics chip, so they render with Cycles on the CPU
    scene.cycles.device = "CPU"
    scene.cycles.samples = spec.get("samples", 8)
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.cycles.max_bounces, scene.cycles.diffuse_bounces, scene.cycles.glossy_bounces = 3, 1, 1
    scene.cycles.transmission_bounces = scene.cycles.volume_bounces = scene.cycles.transparent_max_bounces = 0
    scene.cycles.caustics_reflective = scene.cycles.caustics_refractive = False
    scene.render.use_persistent_data = True  # keep the scene loaded between frames
scene.render.resolution_x, scene.render.resolution_y = spec.get("width", 1080), spec.get("height", 1920)
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast"
scene.frame_start, scene.frame_end = 1, frames
scene.render.fps = fps
scene.render.filepath = spec["out"] + "/f"
bpy.ops.render.render(animation=True)

