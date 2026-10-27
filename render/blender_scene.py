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
bpy.context.view_layer.update()


def material(name, rgb, roughness=0.45, coat=0.35):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = roughness
    b.inputs["Coat Weight"].default_value = coat
    return m


muscle = material("muscle", (0.30, 0.03, 0.04))
tissue = material("tissue", (0.80, 0.68, 0.50), roughness=0.55)
lit = material("lit", (0.52, 0.85, 0.10), roughness=0.35)
for o in parts:
    o.data.materials.clear()
    small = "leaflet" in o.name or "papillary" in o.name
    o.data.materials.append(lit if o.name == spec.get("highlight") else tissue if small else muscle)

points = [o.matrix_world @ mathutils.Vector(c) for o in parts for c in o.bound_box]
lo = mathutils.Vector([min(p[i] for p in points) for i in range(3)])
hi = mathutils.Vector([max(p[i] for p in points) for i in range(3)])
center, size = (lo + hi) / 2, max(hi - lo)

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
pivot.keyframe_insert("rotation_euler", frame=frames)
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
    light.energy = power * v.length ** 2 / 0.36  # same brightness whatever the organ's real size
    obj = bpy.data.objects.new(name, light)
    scene.collection.objects.link(obj)
    obj.location = center + v
    obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()

scene.world = bpy.data.worlds.new("world")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
scene.render.engine = spec.get("engine", "BLENDER_EEVEE_NEXT")
if scene.render.engine == "CYCLES":
    scene.cycles.samples = spec.get("samples", 24)
    scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = spec.get("width", 1080), spec.get("height", 1920)
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"
scene.frame_start, scene.frame_end = 1, frames
scene.render.fps = fps
scene.render.filepath = spec["out"] + "/f"
bpy.ops.render.render(animation=True)

