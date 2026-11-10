"""The 3D layer of the "Types of fracture" video (format "types"). Runs inside Blender:

    blender -b --factory-startup --python render/fracture_scene.py -- '<json spec>'

One femur (Z-Anatomy) on a transparent background, broken eleven ways. anatomy/types.py works out the timeline from
the narration and passes it in the spec; this script builds every fracture with booleans, keys the camera, the
pieces and the bone-chip bursts, renders RGBA frames, and writes where each label's pin sits on screen per frame
(anchors.json), so the 2D labels stay pinned to the break while the camera moves.

spec: {"root": repo dir, "out": frames dir, "fps": 30, "width": 1080, "height": 1920, "engine": "BLENDER_EEVEE_NEXT",
       "timeline": [{"kind": "flash"|"intro"|"type"|"grid", ...}], "frames": total, "only": [frame, ...] (optional)}
"""

import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Matrix, Vector, noise

spec = json.loads(sys.argv[sys.argv.index("--") + 1])
ROOT = Path(spec["root"])
FPS = spec.get("fps", 30)
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)


# --- materials ----------------------------------------------------------------------------------------------
def bumped(m, scale, strength, kind="noise"):
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tex = nt.nodes.new("ShaderNodeTexNoise" if kind == "noise" else "ShaderNodeTexVoronoi")
    tex.inputs["Scale"].default_value = scale
    nt.links.new(tc.outputs["Object"], tex.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    nt.links.new(tex.outputs["Fac" if kind == "noise" else "Distance"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return tex


def material(name, rgb, roughness):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = roughness
    return m


IVORY = material("bone", (0.74, 0.69, 0.60), 0.5)
IVORY.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.12
IVORY.node_tree.nodes["Principled BSDF"].inputs["Subsurface Radius"].default_value = (0.004, 0.003, 0.002)
bumped(IVORY, 260, 0.06)
MARROW = material("marrow", (0.72, 0.42, 0.38), 0.85)
vor = bumped(MARROW, 900, 0.5, "voronoi")
mix = MARROW.node_tree.nodes.new("ShaderNodeMix")  # darker pits in the spongy bone
mix.data_type = "RGBA"
mix.inputs["A"].default_value = (0.78, 0.50, 0.45, 1)
mix.inputs["B"].default_value = (0.42, 0.16, 0.14, 1)
ramp = MARROW.node_tree.nodes.new("ShaderNodeMapRange")
ramp.inputs["From Min"].default_value, ramp.inputs["From Max"].default_value = 0.35, 0.0
MARROW.node_tree.links.new(vor.outputs["Distance"], ramp.inputs["Value"])
MARROW.node_tree.links.new(ramp.outputs["Result"], mix.inputs["Factor"])
MARROW.node_tree.links.new(mix.outputs["Result"], MARROW.node_tree.nodes["Principled BSDF"].inputs["Base Color"])


# --- the femur ----------------------------------------------------------------------------------------------
def bake(o):
    """Apply o's modifiers into its mesh."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
    old = o.data
    o.modifiers.clear()
    o.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)


def load_femur():
    with bpy.data.libraries.load(str(ROOT / "assets" / "models" / "leg.blend")) as (src, dst):
        dst.objects = ["Femur.r"]
    o = dst.objects[0]
    scene.collection.objects.link(o)
    o.hide_render = o.hide_viewport = False
    o.data = o.data.copy()
    o.data.transform(o.matrix_world)
    o.matrix_world = Matrix()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    zs = [v.co.z for v in bm.verts]
    c = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    bmesh.ops.translate(bm, verts=bm.verts, vec=Vector((-c.x, -c.y, -(min(zs) + max(zs)) / 2)))
    bm.to_mesh(o.data)
    bm.free()
    o.data.materials.clear()
    o.data.materials.append(IVORY)
    m = o.modifiers.new("smooth", "SUBSURF")
    m.levels = m.render_levels = 2
    bake(o)
    for p in o.data.polygons:
        p.use_smooth = True
    o.name = "femur"
    return o


FEMUR = load_femur()
VERTS = [v.co.copy() for v in FEMUR.data.vertices]
ZMIN, ZMAX = min(v.z for v in VERTS), max(v.z for v in VERTS)


def ring(z, band=0.003):
    pts = [v for v in VERTS if abs(v.z - z) < band]
    c = sum(pts, Vector()) / len(pts)
    r = max(math.hypot(p.x - c.x, p.y - c.y) for p in pts)
    return c, r, pts


def right_edge(z):
    """Where a label pins a break at height z: the right-hand edge of the bone's front half."""
    c, r, pts = ring(z, 0.004)
    front = [p for p in pts if p.y < c.y - 0.2 * r] or pts
    return max(front, key=lambda p: p.x).copy()


# --- cutters ------------------------------------------------------------------------------------------------
def solid(name, top, bot, frame=Matrix()):
    """A closed mesh between two height grids (lists of rows of points), moved by `frame`, with marrow on it."""
    n, m = len(top) - 1, len(top[0]) - 1
    bm = bmesh.new()
    T = [[bm.verts.new(frame @ Vector(p)) for p in row] for row in top]
    B = [[bm.verts.new(frame @ Vector(p)) for p in row] for row in bot]
    for i in range(n):
        for j in range(m):
            bm.faces.new((T[i][j], T[i + 1][j], T[i + 1][j + 1], T[i][j + 1]))
            bm.faces.new((B[i][j], B[i][j + 1], B[i + 1][j + 1], B[i + 1][j]))
    edge = [(i, 0) for i in range(n)] + [(n, j) for j in range(m)] + [(i, m) for i in range(n, 0, -1)] + \
           [(0, j) for j in range(m, 0, -1)]
    for k, a in enumerate(edge):
        b = edge[(k + 1) % len(edge)]
        bm.faces.new((T[a[0]][a[1]], B[a[0]][a[1]], B[b[0]][b[1]], T[b[0]][b[1]]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(MARROW)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    o.hide_render = True
    return o


def jag(x, y, amp, seed, freq=110.0):
    v = Vector((x * freq + seed * 7.1, y * freq - seed * 3.3, seed * 1.7))
    return amp * (noise.noise(v) + 0.5 * noise.noise(v * 2.7) + 0.25 * noise.noise(v * 6.1))


def halfspace(name, height, half=0.13, n=150, below=0.6, frame=Matrix()):
    """Everything under the surface z = height(x, y) (local coordinates, then `frame`)."""
    xs = [-half + 2 * half * i / n for i in range(n + 1)]
    top = [[(x, y, height(x, y)) for y in xs] for x in xs]
    bot = [[(x, y, -below) for y in xs] for x in xs]
    return solid(name, top, bot, frame)


def plane_cut(name, z0, tilt=0.0, amp=0.0024, seed=1, about="y"):
    """Under a jagged plane through the shaft at height z0, tilted `tilt` degrees (rising to +x, or +y)."""
    c, _, _ = ring(z0)
    t = math.tan(math.radians(tilt))
    return halfspace(name, lambda x, y: (t * x if about == "y" else t * y) + jag(x, y, amp, seed),
                     frame=Matrix.Translation((c.x, c.y, z0)))


def boolean(o, cutter, op):
    m = o.modifiers.new("cut", "BOOLEAN")
    m.object, m.operation, m.solver = cutter, op, "EXACT"
    m.material_mode = "TRANSFER"
    bake(o)
    return o


def copy(name, src=None):
    src = src or FEMUR
    o = bpy.data.objects.new(name, src.data.copy())
    scene.collection.objects.link(o)
    return o


def split(name, cutters):
    """Cut the femur with half-spaces into every non-empty piece (inside/outside each cutter)."""
    pieces = [copy(name)]
    for k, cut in enumerate(cutters):
        nxt = []
        for p in pieces:
            a = boolean(copy(p.name + "a", p), cut, "INTERSECT")
            b = boolean(copy(p.name + "b", p), cut, "DIFFERENCE")
            bpy.data.objects.remove(p)
            nxt += [x for x in (a, b) if len(x.data.vertices) > 60 or bpy.data.objects.remove(x)]
        pieces = nxt
    return pieces


def centre(o):
    vs = o.data.vertices
    return sum((v.co for v in vs), Vector()) / len(vs)


# --- the eleven fractures -----------------------------------------------------------------------------------
# Each returns pieces with their final move (offset, rotation in degrees, about the piece's centre), the pin for
# the label, the point the camera closes in on, and where the bone chips burst from.
def transverse():
    low, high = split("transverse", [plane_cut("tv", 0.0, 0, seed=2)])
    return dict(pieces=[(high, (0, 0, 0.003), (1.2, 0, 0)), (low, (0, 0, 0), (0, 0, 0))], z=0.0)


def oblique():
    low, high = split("oblique", [plane_cut("ob", 0.0, 34, seed=3)])
    return dict(pieces=[(high, (0.0015, 0, 0.0028), (0, -1.0, 0)), (low, (0, 0, 0), (0, 0, 0))], z=0.01)


def spiral():
    z0 = 0.0
    c, _, _ = ring(z0)
    pitch, start = 0.085, 0.0  # the seam (the straight part of the break) runs down the right side

    def h(x, y):
        a = (math.atan2(y, x) - start) % (2 * math.pi)
        return -pitch / 2 + pitch * a / (2 * math.pi) + jag(x, y, 0.0009, 5)
    cut = halfspace("sp", h, half=0.09, n=260, frame=Matrix.Translation((c.x, c.y, z0)))
    low, high = split("spiral", [cut])
    return dict(pieces=[(high, (0, 0, 0.002), (0, 0, 3.0)), (low, (0, 0, 0), (0, 0, 0))], z=0.0, pin_z=0.022)


def greenstick():
    z0 = 0.03
    c, r, _ = ring(z0)
    n, half, apex = 160, 0.08, -0.4 * r
    xs = [apex + (half - apex) * i / n for i in range(n + 1)]
    ys = [-half + 2 * half * i / n for i in range(n + 1)]

    def open_(x):  # wide open on the right, closing to a hairline before the far side
        return 0.0004 + ((x - apex) / (r - apex)) ** 0.9 * 0.0105

    top = [[(x, y, open_(x) / 2 + jag(x, y, 0.0026, 7)) for y in ys] for x in xs]
    bot = [[(x, y, -open_(x) / 2 + jag(x, y, 0.0026, 7)) for y in ys] for x in xs]
    wedge = solid("gs", top, bot, Matrix.Translation((c.x, c.y, z0)))
    bone = boolean(copy("greenstick"), wedge, "DIFFERENCE")
    return dict(pieces=[(bone, (0, 0, 0), (0, 0, 0))], z=z0, pin=right_edge(z0) + Vector((0, 0, 0.004)))


def displaced():
    low, high = split("displaced", [plane_cut("dp", -0.01, 36, seed=11)])
    return dict(pieces=[(high, (0, 0, 0), (0, 0, 0)), (low, (-0.017, -0.007, 0.016), (0, 4, 0))], z=-0.002)


def comminuted():
    z1, z2 = -0.03, 0.03
    c, r, _ = ring(0.0)
    cuts = [plane_cut("cm1", z1, -14, amp=0.0034, seed=13), plane_cut("cm2", z2, 12, amp=0.0034, seed=17, about="x")]
    pieces = split("comminuted", cuts)
    mid = [p for p in pieces if z1 + 0.004 < centre(p).z < z2 - 0.004]
    ends = [p for p in pieces if p not in mid]
    splits = []
    for k, (ang, tilt) in enumerate([(20, 24), (115, 32), (65, 58)]):
        fr = Matrix.Translation((c.x, c.y, 0.0)) @ Matrix.Rotation(math.radians(ang), 4, "Z") @ \
            Matrix.Rotation(math.radians(90 - tilt), 4, "Y")
        splits.append(halfspace(f"cs{k}", lambda x, y, k=k: jag(x, y, 0.0034, 20 + k), half=0.08, n=110, frame=fr))
    frags = []
    for p in mid:
        part = [p]
        for cut in splits:
            nxt = []
            for q in part:
                a = boolean(copy(q.name + "a", q), cut, "INTERSECT")
                b = boolean(copy(q.name + "b", q), cut, "DIFFERENCE")
                bpy.data.objects.remove(q)
                nxt += [x for x in (a, b) if len(x.data.vertices) > 60 or bpy.data.objects.remove(x)]
            part = nxt
        frags += part
    rng = random.Random(4)
    moves = []
    for f in frags:
        d = centre(f) - Vector((c.x, c.y, centre(f).z))
        d = d.normalized() if d.length > 1e-6 else Vector((1, 0, 0))
        moves.append((f, tuple(d * rng.uniform(0.0012, 0.0028)), (rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(-4, 4))))
    top = max(ends, key=lambda p: centre(p).z)
    moves += [(top, (0, 0, 0.002), (0, 0, 0)), (min(ends, key=lambda p: centre(p).z), (0, 0, -0.001), (0, 0, 0))]
    return dict(pieces=moves, z=0.0, pin_z=0.012)


def segmental():
    pieces = split("segmental", [plane_cut("sg1", 0.055, 12, seed=23), plane_cut("sg2", -0.05, -10, seed=29)])
    pieces.sort(key=lambda p: centre(p).z)
    low, mid, high = pieces[0], pieces[1], pieces[-1]
    return dict(pieces=[(high, (0, 0, 0.0015), (0, 0, 0)), (mid, (0.0035, -0.001, 0), (0, 3.5, 0)),
                        (low, (0, 0, -0.0012), (0, 0, 0))], z=0.0, pin_z=0.05, close=0.6)


def avulsion():
    band = [v for v in VERTS if ZMIN + 0.03 < v.z < ZMIN + 0.06]
    tip = max(band, key=lambda v: v.x)  # the inner (medial) side of the knee end
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=5, radius=0.019)
    for v in bm.verts:
        v.co += v.co.normalized() * jag(v.co.x, v.co.y + v.co.z, 0.004, 31, 160)
    me = bpy.data.meshes.new("av")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(MARROW)
    blob = bpy.data.objects.new("av", me)
    scene.collection.objects.link(blob)
    blob.location = tip + Vector((0.004, -0.002, 0.004))
    blob.hide_render = True
    chip = boolean(copy("avulsion_chip"), blob, "INTERSECT")
    rest = boolean(copy("avulsion"), blob, "DIFFERENCE")
    return dict(pieces=[(rest, (0, 0, 0), (0, 0, 0)), (chip, (0.007, -0.003, -0.002), (0, 16, -12))],
                z=tip.z, pin=tip + Vector((0.004, -0.004, 0.0)), focus=tip + Vector((-0.01, 0, 0.012)))


def surface(origin, direction):
    """Where a ray from outside hits the femur (its mesh, before any move), with the surface normal."""
    ok, loc, nrm, _ = FEMUR.ray_cast(Vector(origin), Vector(direction).normalized())
    return (loc, nrm) if ok else (None, None)


def crack_tube(name, samples, closed=False, depth=0.0026):
    """A thin solid along the surface, for hairline cracks: samples are (point, outward normal, side, half width)."""
    bm = bmesh.new()
    rings = []
    for p, out, side, w in samples:
        rings.append([bm.verts.new(p + side * a + out * b) for a, b in ((-w, 0.0015), (w, 0.0015), (w, -depth), (-w, -depth))])
    pairs = list(zip(rings, rings[1:])) + ([(rings[-1], rings[0])] if closed else [])
    for a, b in pairs:
        for i in range(4):
            bm.faces.new((a[i], a[(i + 1) % 4], b[(i + 1) % 4], b[i]))
    if not closed:
        bm.faces.new(rings[0][::-1])
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(MARROW)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    o.hide_render = True
    return o


def bulge(o, zb, height, half, ridges=0.0):
    """Push the surface out in a band around zb (a buckle), denser mesh there first."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    near = [e for e in bm.edges if any(abs(v.co.z - zb) < half + 0.003 for v in e.verts)]
    bmesh.ops.subdivide_edges(bm, edges=near, cuts=2, use_grid_fill=True)
    c, _, _ = ring(zb)
    for v in bm.verts:
        d = v.co.z - zb
        if abs(d) < half:
            w = math.cos(math.pi * d / (2 * half)) ** 2
            ridge = 1.0 if not ridges else 0.55 + 0.45 * math.cos(2 * math.pi * d / ridges)
            out = Vector((v.co.x - c.x, v.co.y - c.y, 0))
            if out.length > 1e-6:
                v.co += out.normalized() * height * w * ridge * (1 + 0.35 * noise.noise(v.co * 300))
    bm.to_mesh(o.data)
    bm.free()
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def impacted():
    """The ends jammed together: a thin, jagged seam all the way round, with the bone bulging just under it."""
    z0 = ZMIN + 0.11
    c, _, _ = ring(z0)
    n, half = 170, 0.09
    xs = [-half + 2 * half * i / n for i in range(n + 1)]
    seam = solid("im", [[(x, y, jag(x, y, 0.0024, 37) + 0.0006) for y in xs] for x in xs],
                 [[(x, y, jag(x, y, 0.0024, 37) - 0.0006) for y in xs] for x in xs], Matrix.Translation((c.x, c.y, z0)))
    bone = boolean(copy("impacted"), seam, "DIFFERENCE")
    bone = bulge(bone, z0 - 0.004, 0.0011, 0.0045)  # after the cut: the boolean wants the clean mesh
    return dict(pieces=[(bone, (0, 0, 0), (0, 0, 0))], z=z0)


def buckle():
    zb = ZMIN + 0.10
    return dict(pieces=[(bulge(copy("buckle"), zb, 0.0024, 0.009, ridges=0.006), (0, 0, 0), (0, 0, 0))], z=zb, burst=False)


def stress():
    z1, z2 = 0.015, 0.075
    c, _, _ = ring((z1 + z2) / 2)
    samples = []
    K = 90
    for k in range(K + 1):
        z = z1 + (z2 - z1) * k / K
        x = c.x - 0.002 + 0.0006 * math.sin(k * 0.45) + 0.0009 * noise.noise(Vector((k * 0.12, 1.3, 2.1)))
        hit, nrm = surface((x, -0.3, z), (0, 1, 0))
        side = nrm.cross(Vector((0, 0, 1))).normalized()
        samples.append((hit, nrm, side, 0.00055 * math.sin(math.pi * k / K) ** 0.5 + 0.00005))
    bone = boolean(copy("stress"), crack_tube("st", samples), "DIFFERENCE")
    pin = samples[int(K * 0.62)][0] + Vector((0.0008, 0, 0))
    return dict(pieces=[(bone, (0, 0, 0), (0, 0, 0))], z=(z1 + z2) / 2, pin=pin, burst=False, small=True)


BUILDERS = {"transverse": transverse, "oblique": oblique, "spiral": spiral, "greenstick": greenstick,
            "displaced": displaced, "comminuted": comminuted, "segmental": segmental, "avulsion": avulsion,
            "impacted": impacted, "buckle": buckle, "stress": stress}
FRACTURES = {}
for name in spec.get("types", list(BUILDERS)):
    f = BUILDERS[name]()
    f.setdefault("pin", right_edge(f.get("pin_z", f["z"])))
    f.setdefault("focus", Vector((ring(f["z"])[0].x, ring(f["z"])[0].y, f["z"])))
    FRACTURES[name] = f
    print(f"{name}: pieces", [len(p.data.vertices) for p, _, _ in f["pieces"]], flush=True)
for o in list(bpy.data.objects):  # the cutters
    if o.hide_render and o is not FEMUR:
        bpy.data.objects.remove(o)


def moved(piece, offset, rot, k=1.0):
    """The piece's matrix after k (0..1) of its final move."""
    c = centre(piece)
    r = Euler(tuple(math.radians(a) * k for a in rot)).to_matrix().to_4x4()
    return Matrix.Translation(Vector(offset) * k) @ Matrix.Translation(c) @ r @ Matrix.Translation(-c)


# --- stage: lights, render settings -------------------------------------------------------------------------
def light(name, loc, power, size, color=(1, 1, 1)):
    l = bpy.data.lights.new(name, "AREA")
    l.size, l.energy, l.color = size, power, color
    o = bpy.data.objects.new(name, l)
    scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return o


light("key", (-1.0, -1.1, 0.8), spec.get("key", 170), 1.0)
light("fill", (1.1, -0.9, 0.2), spec.get("fill", 22), 1.8, (0.95, 0.97, 1.0))
light("rim", (0.4, 1.2, 0.8), spec.get("rim", 220), 0.6)
scene.world = bpy.data.worlds.new("world")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.33, 0.35, 1)
scene.world.node_tree.nodes["Background"].inputs[1].default_value = spec.get("world", 0.22)
scene.render.engine = spec.get("engine", "BLENDER_EEVEE_NEXT")
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = spec.get("width", 1080), spec.get("height", 1920)
scene.render.fps = FPS
scene.eevee.taa_render_samples = spec.get("samples", 32)
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = spec.get("look", "AgX - Medium High Contrast")
scene.view_settings.exposure = spec.get("exposure", -0.7)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.lens = 70
cam.data.sensor_fit = "VERTICAL"
cam.data.clip_start = 0.005

if spec.get("mode") == "lineup":
    FEMUR.hide_render = True
    names = list(FRACTURES)
    for i, n in enumerate(names):
        dx = (i - (len(names) - 1) / 2) * 0.15
        for piece, off, rot in FRACTURES[n]["pieces"]:
            piece.matrix_world = Matrix.Translation((dx, 0, 0)) @ moved(piece, off, rot)
    scene.render.resolution_x, scene.render.resolution_y = 3200, 1100
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 0.15 * len(names) + 0.05
    cam.location = (0, -2, 0)
    cam.rotation_euler = (math.pi / 2, 0, 0)
    scene.render.filepath = spec["out"]
    bpy.ops.render.render(write_still=True)


# --- animation ----------------------------------------------------------------------------------------------
# Camera: on the front (-y) side looking at the bone, 4 degrees from above. frame_h(d) is the height of the
# picture at distance d; the wide shot shows the whole femur in ~78% of the height.
ELEV = math.radians(4)
TAN = 12 / cam.data.lens  # half the 24 mm sensor height over the lens
ASPECT = scene.render.resolution_x / scene.render.resolution_y
WIDE_D, CLOSE_D = (ZMAX - ZMIN) / 0.78 / (2 * TAN), spec.get("close", 0.36)


def frame_h(d):
    return 2 * d * TAN


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def look(target, d, slide=0.0):
    """Camera matrix: looking at target from distance d; slide moves it sideways by that many picture widths."""
    back = Vector((0, -math.cos(ELEV), math.sin(ELEV)))
    pos = Vector(target) + back * d + Vector((slide * frame_h(d) * ASPECT, 0, 0))
    rot = (-back).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    return Matrix.Translation(pos) @ rot


def aim(point, d, ox=-0.06, oy=0.07):
    """Where the camera looks so `point` lands ox picture-widths right and oy picture-heights above the centre."""
    return Vector(point) - Vector((ox * frame_h(d) * ASPECT, 0, oy * frame_h(d)))


pivot = bpy.data.objects.new("pivot", None)
scene.collection.objects.link(pivot)
FEMUR.parent = pivot
for f in FRACTURES.values():
    for piece, _, _ in f["pieces"]:
        piece.parent = pivot

ALL = [FEMUR] + [p for f in FRACTURES.values() for p, _, _ in f["pieces"]]
TL = spec.get("timeline", [])
TOTAL = spec.get("frames", 1)
F = lambda t: int(round(t * FPS))  # noqa: E731
shown: dict[int, set] = {}  # frame -> objects visible (filled per segment)


def show(objs, a, b):
    for k in range(a, b):
        shown.setdefault(k, set()).update(objs)


def key_piece(piece, off, rot, at):
    """Pieces jump apart at frame `at` (a quick move with a little overshoot)."""
    for k, amt in ((at - 1, 0.0), (at, 0.0), (at + 2, 1.15), (at + 4, 0.95), (at + 6, 1.0)):
        m = moved(piece, off, rot, amt)
        piece.matrix_basis = m
        piece.keyframe_insert("location", frame=k)
        piece.keyframe_insert("rotation_euler", frame=k)


CHIPS = []


def burst(f, at, rng, n=26):
    """Bone chips flying out of the break at frame `at` for ~0.7 s."""
    c, r, _ = ring(f["z"])
    for i in range(n):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
        for v in bm.verts:
            v.co *= rng.uniform(0.6, 1.3)
        me = bpy.data.meshes.new("chip")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(MARROW if rng.random() < 0.55 else IVORY)
        o = bpy.data.objects.new("chip", me)
        scene.collection.objects.link(o)
        o.parent = pivot
        a = rng.uniform(0, 2 * math.pi)
        p0 = Vector((c.x + r * math.cos(a), c.y + r * math.sin(a), f["z"] + rng.uniform(-0.004, 0.004)))
        v0 = Vector((math.cos(a), math.sin(a) - 0.5, 0)).normalized() * rng.uniform(0.05, 0.22) + Vector((0, 0, rng.uniform(-0.04, 0.08)))
        size = rng.uniform(0.0006, 0.0022)
        spin = Vector((rng.uniform(-20, 20), rng.uniform(-20, 20), rng.uniform(-20, 20)))
        life = rng.uniform(0.6, 1.1)
        for k in range(0, int(life * FPS) + 2, 2):
            t = k / FPS
            o.location = p0 + v0 * (1 - math.exp(-2.2 * t)) / 2.2 + Vector((0, 0, -0.08 * t * t))
            o.rotation_euler = spin * t
            o.scale = Vector((1, 1, 1)) * size * max(0.0, 1 - (t / life) ** 2)
            o.keyframe_insert("location", frame=at + k)
            o.keyframe_insert("rotation_euler", frame=at + k)
            o.keyframe_insert("scale", frame=at + k)
        CHIPS.append(o)
        show([o], at, at + int(life * FPS) + 2)


rng = random.Random(9)
cams, pivots, pins = {}, {}, {}
for seg in TL:
    a, b = F(seg["start"]), F(seg["end"])
    if seg["kind"] == "flash":  # the hook: the whole bone breaking a different way every half second
        names = seg["types"]
        step = (b - a) / len(names)
        for i, n in enumerate(names):
            fa, fb = a + int(i * step), a + int((i + 1) * step)
            f = FRACTURES[n]
            for piece, off, rot in f["pieces"]:
                key_piece(piece, off, rot, fa + 1)
            show([p for p, _, _ in f["pieces"]], fa, fb)
            if f.get("burst", True):
                burst(f, fa + 1, rng, 18)
            for k in range(fa, fb):
                pins[k] = {"pin": f["pin"], "label": n, "small": True}
        for k in range(a, b):
            cams[k] = look(Vector((0, 0, 0)), WIDE_D * (1.02 - 0.04 * (k - a) / max(1, b - a)))
            pivots[k] = 0.0
    elif seg["kind"] == "intro":  # extreme close-up on the head of the femur, pulling back to the whole bone
        head = max(VERTS, key=lambda v: v.z + 0.6 * v.x)
        show([FEMUR], a, b)
        for k in range(a, b):
            t = smooth((k - a) / max(1, b - a - 6))
            d = 0.16 + (WIDE_D - 0.16) * t
            tgt = head.lerp(Vector((0, 0, 0)), t) + Vector((0, 0, -0.015 * (1 - t)))
            cams[k] = look(tgt, d)
            pivots[k] = math.radians(-25 * (1 - t))
    elif seg["kind"] == "type":
        f = FRACTURES[seg["name"]]
        crack = a + F(seg.get("crack", 0.45))
        show([FEMUR], a, crack)
        show([p for p, _, _ in f["pieces"]], crack, b)
        for piece, off, rot in f["pieces"]:
            key_piece(piece, off, rot, crack)
        if f.get("burst", True):
            burst(f, crack, rng)
        whip = F(0.27)
        close = f.get("close", CLOSE_D) * (0.75 if f.get("small") else 1.0)
        for k in range(a, b):
            t = smooth((k - a - F(0.3)) / max(1, b - a - F(0.6)))
            ang = math.radians(-10 + 22 * (k - a) / max(1, b - a))
            rotz = Matrix.Rotation(ang, 4, "Z")
            d = WIDE_D + (close - WIDE_D) * t
            tgt = Vector((0, 0, 0)).lerp(aim(rotz @ Vector(f["focus"]), close), t)
            slide = 0.0
            if seg.get("whip_in", True) and k < a + whip:
                slide = -1.3 * (1 - smooth((k - a) / whip)) ** 2
            if k >= b - whip:
                slide = 1.3 * smooth((k - (b - whip)) / whip) ** 2
            cams[k] = look(tgt, d, slide)
            pivots[k] = ang
            if k >= crack:
                pins[k] = {"pin": f["pin"], "label": seg["name"]}
    elif seg["kind"] == "outro":  # pull far back from the last bone
        last = cams[a - 1] if a - 1 in cams else look(Vector(), WIDE_D)
        lastp = pivots.get(a - 1, 0.0)
        name = TL[TL.index(seg) - 1].get("name")
        objs = [p for p, _, _ in FRACTURES[name]["pieces"]] if name else [FEMUR]
        show(objs, a, b)
        for k in range(a, b):
            t = smooth((k - a) / max(1, b - a))
            d = WIDE_D * (1 + 3.5 * t)
            cams[k] = look(Vector((0, 0, 0)), d) if t > 0 else last
            pivots[k] = lastp

# the closing chart: every fracture, small, in rows of 4, 4 and 3
grid = next((s for s in TL if s["kind"] == "grid"), None)
GRID_D = 9.5
if grid:
    a, b = F(grid["start"]), F(grid["end"])
    names = list(FRACTURES)
    slots = [(i % 4, i // 4) for i in range(8)] + [(0.5 + i, 2) for i in range(3)]
    gap_x, gap_z = 0.24, 0.55
    for n, (col, row) in zip(names, slots):
        pos = Vector(((col - 1.5) * gap_x, 0, (1 - row) * gap_z + 0.08))
        objs = []
        for piece, off, rot in FRACTURES[n]["pieces"]:
            o = bpy.data.objects.new(piece.name + "_grid", piece.data)
            scene.collection.objects.link(o)
            o.matrix_basis = Matrix.Translation(pos) @ moved(piece, off, rot)
            objs.append(o)
        show(objs, a, b)
        for k in range(a, b):
            pins.setdefault(k, {"grid": []})["grid"].append({"label": n, "at": list(pos + Vector((0, 0, ZMIN - 0.035)))})
    for k in range(a, b):
        d = GRID_D * (1.04 - 0.04 * smooth((k - a) / FPS))
        cams[k] = look(Vector((0, 0, 0.08 - 0.0625 * frame_h(d))), d)  # the chart sits a little high: caption below
        pivots[k] = 0.0

# key everything frame by frame
for o in ALL + CHIPS + [x for x in bpy.data.objects if x.name.endswith("_grid")]:
    o.hide_render = True
    o.keyframe_insert("hide_render", frame=0)
for k in range(TOTAL):
    vis = shown.get(k, set())
    prev = shown.get(k - 1, set())
    for o in vis ^ prev:
        o.hide_render = o not in vis
        o.keyframe_insert("hide_render", frame=k)
    if k in cams:
        cam.matrix_world = cams[k]
        cam.keyframe_insert("location", frame=k)
        cam.keyframe_insert("rotation_euler", frame=k)
    if k in pivots:
        pivot.rotation_euler = (0, 0, pivots[k])
        pivot.keyframe_insert("rotation_euler", frame=k)
for o in [cam, pivot]:
    if o.animation_data:
        for fc in o.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"

scene.render.use_motion_blur = spec.get("blur", True)
scene.render.motion_blur_shutter = 0.6
scene.frame_start, scene.frame_end = 0, TOTAL - 1

# where each label pin lands on screen, per frame
W_, H_ = scene.render.resolution_x, scene.render.resolution_y
out = Path(spec["out"])
out.mkdir(parents=True, exist_ok=True)
anchors = {}
for k in sorted(pins):
    scene.frame_set(k)
    item = pins[k]
    if "grid" in item:
        anchors[k] = {"grid": [{"label": g["label"], "xy": [world_to_camera_view(scene, cam, Vector(g["at"])).x * W_,
                                (1 - world_to_camera_view(scene, cam, Vector(g["at"])).y) * H_]} for g in item["grid"]]}
        continue
    p = world_to_camera_view(scene, cam, pivot.matrix_world @ Vector(item["pin"]))
    anchors[k] = {"label": item["label"], "xy": [p.x * W_, (1 - p.y) * H_], "small": item.get("small", False)}
(out / "anchors.json").write_text(json.dumps(anchors))

if spec.get("mode") != "lineup":
    frames = spec.get("only") or list(range(TOTAL))
    if spec.get("only"):
        for k in frames:
            scene.frame_set(k)
            scene.render.filepath = str(out / f"{k:05d}.png")
            bpy.ops.render.render(write_still=True)
    else:
        scene.render.filepath = str(out / "#####")
        bpy.ops.render.render(animation=True)
