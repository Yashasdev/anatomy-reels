"""Render the 3D layer of a reel: one organ model turning slowly, one part lit up. Runs inside Blender:

    blender -b --factory-startup --python render/blender_scene.py -- '<json spec>'

spec: {"model": "assets/models/heart.blend", "out": "out/x/frames", "frames": 360, "fps": 15,
       "highlight": "Left ventricle", "engine": "BLENDER_EEVEE_NEXT", "width": 1080, "height": 1920}
Frames are written as transparent PNGs; anatomy/make.py puts the text, choices and captions over them.

Optional keys for the other formats (absent in the classic quiz, which renders exactly as before):
  "hide": [names]          parts left out of the main frames ("Which bone is missing?")
  "focus_on": [names]      with "focus": frame these parts instead of the highlight
  "glow": true             the lit material also glows a little (emission)
  "reveal": {"parts": [names], "frames": [k, ...], "out": dir}
                           after the main frames, show these parts lit and render frames k again into dir;
                           make.py cross-fades to them, so the part fades in glowing (or lights up)
  "sway": [amplitude, seconds]  swing back and forth around start_degrees instead of turning all the way
  "zoom": {"target": [names], "aim": [fx, fy, fz], "start": 0.03, "frames": 180, "orbit": 25}
                           the camera starts very close to the target's surface (the point seen from the final
                           camera direction, aimed at fractions fx/fy/fz of its box) and pulls back to the normal
                           framing over "frames"; the model holds still until then, then turns
  "studio": true           the light-gray studio look (anatomy/make.py look="studio"): softer, bigger lights with a
                           gray ambient matching the backdrop, bone with a little subsurface and grain, wet-looking
                           soft tissue, a lit part that glows a little so it reads on gray. Off, nothing changes.
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
if spec.get("glow"):
    _b = lit.node_tree.nodes["Principled BSDF"]
    _b.inputs["Emission Color"].default_value = (0.30, 0.85, 0.02, 1)
    _b.inputs["Emission Strength"].default_value = spec.get("glow_strength", 0.6)
natural = {}  # each part's own material, for the reveal pass
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
hidden = set(spec.get("hide") or [])
for o in parts:
    if o.name in hidden:
        o.hide_render = True

points = [o.matrix_world @ mathutils.Vector(c) for o in parts for c in o.bound_box]
lo = mathutils.Vector([min(p[i] for p in points) for i in range(3)])
hi = mathutils.Vector([max(p[i] for p in points) for i in range(3)])
center, size = (lo + hi) / 2, max(hi - lo)
if spec.get("focus"):  # small parts of a big region: turn around the glowing part and frame it (with a small distance)
    hl = set(spec.get("highlight") if isinstance(spec.get("highlight"), list) else [spec.get("highlight")])
    hl = set(spec["focus_on"]) if spec.get("focus_on") else hl
    pts = [o.matrix_world @ mathutils.Vector(c) for o in parts if o.name in hl for c in o.bound_box]
    if pts:
        center = (mathutils.Vector([min(p[i] for p in pts) for i in range(3)])
                  + mathutils.Vector([max(p[i] for p in pts) for i in range(3)])) / 2



def studio_look():
    """Realistic materials and soft studio light for the gray sweep make.py puts behind the model."""
    def grain(m, scale, strength):
        nt = m.node_tree
        tc, tex, bump = (nt.nodes.new(t) for t in ("ShaderNodeTexCoord", "ShaderNodeTexNoise", "ShaderNodeBump"))
        tex.inputs["Scale"].default_value = scale
        tex.inputs["Detail"].default_value = 6
        bump.inputs["Strength"].default_value = strength
        nt.links.new(tc.outputs["Object"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])

    for m in {m for o in parts for m in o.data.materials if m}:
        b = m.node_tree.nodes["Principled BSDF"]
        rgb = tuple(b.inputs["Base Color"].default_value)[:3]
        b.inputs["Subsurface Scale"].default_value = size * 0.01
        if m is lit:
            b.inputs["Emission Color"].default_value = (0.30, 0.85, 0.02, 1)
            b.inputs["Emission Strength"].default_value = max(0.15, b.inputs["Emission Strength"].default_value)
            b.inputs["Coat Weight"].default_value = 0.2
        elif rgb[0] > 0.8 and rgb[2] < rgb[0] * 0.8:  # bone and teeth: ivory, matte, a fine grain
            b.inputs["Base Color"].default_value = (rgb[0] * 0.86, rgb[1] * 0.86, rgb[2] * 0.88, 1)  # the Types ivory
            b.inputs["Roughness"].default_value = 0.55
            b.inputs["Coat Weight"].default_value = 0.0
            b.inputs["Subsurface Weight"].default_value = 0.15
            b.inputs["Subsurface Radius"].default_value = (1.0, 0.7, 0.45)
            grain(m, 90 / size, 0.08)
        else:  # soft tissue: light scatters through it and it looks wet
            b.inputs["Subsurface Weight"].default_value = 0.25
            b.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.25)
            b.inputs["Roughness"].default_value = 0.38
            b.inputs["Coat Weight"].default_value = 0.45
            b.inputs["Coat Roughness"].default_value = 0.12
            grain(m, 60 / size, 0.04)
    for obj in scene.objects:  # bigger lights for softer shadows, a little brighter on the gray
        if obj.type == "LIGHT":
            obj.data.size = size * 2.2
            obj.data.energy *= {"key": 1.2, "fill": 0.9, "rim": 0.9}[obj.name]
    bg = scene.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.32, 0.33, 0.35, 1)  # the backdrop's gray, as soft fill from every side
    bg.inputs[1].default_value = spec.get("world", 0.22)
    scene.view_settings.look = spec.get("agx_look", "AgX - Medium High Contrast")
    scene.view_settings.exposure = spec.get("exposure", -0.6)
    if hasattr(scene.eevee, "use_raytracing"):  # contact shadows and occlusion where parts touch
        scene.eevee.use_raytracing = True
    if hasattr(scene.eevee, "use_shadows"):
        scene.eevee.use_shadows = True


pivot = bpy.data.objects.new("pivot", None)
scene.collection.objects.link(pivot)
pivot.location = center
bpy.context.view_layer.update()
for o in parts:
    o.parent = pivot
    o.matrix_parent_inverse = pivot.matrix_world.inverted()

frames, fps = spec["frames"], spec.get("fps", 15)
turn = spec.get("degrees_per_second", 30)  # a slow, steady turn
zoom = spec.get("zoom")
hold = min(zoom["frames"], frames) if zoom else 1  # a zoom holds the model still until the camera has pulled back
pivot.rotation_euler = (0, 0, math.radians(spec.get("start_degrees", -20)))
pivot.keyframe_insert("rotation_euler", frame=1)
if spec.get("sway"):  # swing back and forth around start_degrees (amplitude, seconds per swing), so a view stays in sight
    amp, period = spec["sway"]
    for k in range(2, frames + 2):
        pivot.rotation_euler = (0, 0, math.radians(spec.get("start_degrees", -20)
                                                   + amp * math.sin(2 * math.pi * (k - 1) / (fps * period))))
        pivot.keyframe_insert("rotation_euler", frame=k)
elif hold > 1:
    pivot.keyframe_insert("rotation_euler", frame=hold)
if not spec.get("sway"):
    pivot.rotation_euler = (0, 0, math.radians(spec.get("start_degrees", -20) + turn * (frames + 1 - hold) / fps))
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

if zoom:  # start on the target's surface, pull straight back to the framing above
    scene.frame_set(1)
    bpy.context.view_layer.update()
    final = cam.location.copy()
    look_end = center + (final - (center + mathutils.Vector((0, -size * spec.get("distance", 6.0), size * 0.4))))
    away = (final - look_end).normalized()
    far = (final - look_end).length
    tgt = set(zoom["target"])
    pts = [o.matrix_world @ mathutils.Vector(c) for o in parts if o.name in tgt for c in o.bound_box]
    tlo = mathutils.Vector([min(p[i] for p in pts) for i in range(3)])
    thi = mathutils.Vector([max(p[i] for p in pts) for i in range(3)])
    aim = mathutils.Vector([tlo[i] + (thi[i] - tlo[i]) * f for i, f in enumerate(zoom.get("aim", (0.5, 0.5, 0.5)))])
    deps = bpy.context.evaluated_depsgraph_get()
    side = away.cross(mathutils.Vector((0, 0, 1))).normalized()
    up = side.cross(away).normalized()
    best = None  # the target's surface point (seen from the camera's side) nearest the aim
    span = (thi - tlo).length
    for a in range(-6, 7):
        for b in range(-6, 7):
            start_ = aim + side * (a * span / 12) + up * (b * span / 12)
            hit, loc, _n, _i, obj, _m = scene.ray_cast(deps, start_ + away * size * 3, -away)
            if hit and obj.name in tgt and (best is None or (start_ - aim).length < best[0]):
                best = ((start_ - aim).length, loc)
    if best is None:
        raise SystemExit(f"zoom: {sorted(tgt)} can't be seen from the camera's side; change start_degrees")
    loc = best[1]
    near = size * zoom.get("start", 0.03)
    zf = max(2, min(zoom["frames"], frames))
    cam.data.clip_start = near * 0.05
    cam.data.clip_end = size * 50
    rot = None
    for k in range(1, frames + 1):
        s_ = min(1.0, (k - 1) / (zf - 1))
        p = 0.5 * s_ + 0.5 * s_ * s_ * (3 - 2 * s_)             # steady, easing a little at both ends
        r = near * (far / near) ** p                            # even, steady-feeling zoom
        q = (r - near) / (far - near)                           # the aim drifts to the region's center as it pulls back
        look = loc.lerp(look_end, q)
        d = away.copy()
        d.rotate(mathutils.Euler((0, 0, math.radians(zoom.get("orbit", 0) * (1 - p)))))
        cam.location = look + d * r
        rot = (look - cam.location).to_track_quat("-Z", "Y").to_euler("XYZ", rot) if rot else \
            (look - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.rotation_euler = rot
        cam.keyframe_insert("location", frame=k)
        cam.keyframe_insert("rotation_euler", frame=k)

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
if spec.get("studio"):  # the light-gray studio of the Types videos (render/fracture_scene.py)
    studio_look()
scene.frame_start, scene.frame_end = 1, frames
scene.render.fps = fps
scene.render.filepath = spec["out"] + "/f"
bpy.ops.render.render(animation=True)

reveal = spec.get("reveal")
if reveal:  # the same frames again with the reveal parts shown and lit
    show = set(reveal["parts"])
    for o in parts:
        if o.name in show:
            o.hide_render = False
            o.data = o.data.copy()  # paired parts can share one mesh (the skull's .l/.r); light only this side
            o.data.materials.clear()
            o.data.materials.append(lit)
    for k in reveal["frames"]:
        scene.frame_set(k)
        scene.render.filepath = f"{reveal['out']}/f{k:04d}.png"
        bpy.ops.render.render(write_still=True)

