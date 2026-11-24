"""The 3D layer of a "How it works on your body" video (anatomy/howitworks.py): a macro block of skin in the gray
studio, cut open at the front. Runs inside Blender:

    blender -b --factory-startup -t 4 --python render/skin_scene.py -- '<json spec>'

What's built (units are arbitrary; the block is 3.2 wide, the skin's top is z = 0, the cut face is y = YF):
  the top surface    real-looking macro skin (skin_top): pores, microrelief, creases, redness, oil, fine hairs
  the cut face       epidermis (layered bands), dermis (pink, fibres, a few capillary loops), fat (yellow lobules)
  an eccrine gland   a coiled tube deep in the dermis, its duct rising to a pore at the front edge; the top of the
                     duct is a clear window so the sweat inside and the gel plug show
  a hair follicle    slanting down to its bulb, a sebaceous gland beside it and an apocrine gland whose duct joins
                     the follicle above it (apocrine glands empty into hair follicles, eccrine glands onto the skin)
  props              sweat droplets on pores, odor bacteria (rods), fragrance motes, aluminum salt crystals, skin
                     flakes, and the hook's hero: an unbranded electric-blue stick whose cap pops off, mist around it

spec: {"root", "out", "fps", "width", "height", "samples", "frames", "shots": [{"kind", "start", "end"}],
       "cues": [{"line", "at", "dur"}], "only": [frames]}
Shot kinds, in order: stick, surface, apocrine, deodorant, eccrine, renew, night, calm, chart. Every event is timed
from the narration cues, so the picture follows the voice. Writes <out>/#####.png (transparent film; the 2D layer
adds the studio, labels and captions) and anchors.json: per frame, where each label's pin is on screen.
"""

import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector, noise

spec = json.loads(sys.argv[sys.argv.index("--") + 1])
ROOT = Path(spec["root"])
FPS = spec.get("fps", 30)
TOTAL = spec["frames"]
SHOTS = spec["shots"]
CUES = {c["line"]: c for c in spec["cues"]}
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
rng = random.Random(11)

X0, X1, YF, YB = -1.6, 1.6, -1.0, 2.6
EPI, DERM, FAT = 0.22, 1.32, 2.05
PORE_E = Vector((0.38, YF + 0.035))  # the eccrine pore, at the front edge
PORE_H = Vector((-0.62, YF + 0.04))  # the hair follicle's opening
FRONT = YF - 0.012  # tubes on the cut face sit just proud of it


def L(i):
    return CUES[i]["at"]


def D(i):
    return CUES[i]["dur"]


def shot(kind):
    return next(s for s in SHOTS if s["kind"] == kind)


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def ease(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def ramp(t, a, b):
    return smooth((t - a) / max(1e-6, b - a))


# --- materials ---------------------------------------------------------------------------------------------------
def principled(name, rgb, rough=0.5, sss=0.0, radius=(0.08, 0.03, 0.02), alpha=1.0, emit=0.0, trans=0.0, ior=1.4,
               spec=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Specular IOR Level"].default_value = spec
    if sss:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = radius
        b.inputs["Subsurface Scale"].default_value = 1.0
    if trans:
        b.inputs["Transmission Weight"].default_value = trans
        b.inputs["IOR"].default_value = ior
        m.use_raytrace_refraction = True
    if emit:
        b.inputs["Emission Color"].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = emit
    if alpha < 1:  # dithered, not blended: blended layers hide what's inside them (the sweat in the duct)
        b.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "DITHERED"
    return m


def node(m, kind, **inputs):
    n = m.node_tree.nodes.new(kind)
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def link(m, a, b):
    m.node_tree.links.new(a, b)


def bsdf(m):
    return m.node_tree.nodes["Principled BSDF"]


def obj_coords(m):
    return m.node_tree.nodes.new("ShaderNodeTexCoord").outputs["Object"]


def skin_top():
    """Skin seen up close, built to read as real (Nov 21): the microrelief (a network of fine furrows in two sizes and
    a few long creases), pores sitting in it, shaved-hair follicles showing through as soft gray-blue dots, blotchy
    tone with patches of redness, and an uneven oily sheen (a thin clear coat that is glossier in places). Soft
    subsurface scattering lets light glow through the edges."""
    m = principled("skin", (0.78, 0.52, 0.42), 0.45, sss=0.8, radius=(0.08, 0.03, 0.016), spec=0.4)
    nt = m.node_tree
    co = obj_coords(m)

    def tex(kind, scale, **kw):
        n = node(m, kind, Scale=scale, **{k: v for k, v in kw.items() if k not in ("feature", "dims")})
        if "feature" in kw:
            n.feature = kw["feature"]
        if "dims" in kw:
            n.voronoi_dimensions = kw["dims"]
        link(m, warped, n.inputs["Vector"])
        return n

    def maprange(src, a, b, c=0.0, d=1.0, smooth=False):
        n = nt.nodes.new("ShaderNodeMapRange")
        if smooth:
            n.interpolation_type = "SMOOTHSTEP"
        n.inputs["From Min"].default_value, n.inputs["From Max"].default_value = a, b
        n.inputs["To Min"].default_value, n.inputs["To Max"].default_value = c, d
        link(m, src, n.inputs["Value"])
        return n.outputs["Result"]

    def math_(op, a, b):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b)):
            if isinstance(v, float):
                n.inputs[i].default_value = v
            else:
                link(m, v, n.inputs[i])
        return n.outputs["Value"]

    def mixc(fac, a, b, blend="MIX"):
        n = nt.nodes.new("ShaderNodeMix")
        n.data_type, n.blend_type = "RGBA", blend
        for sock, v in ((n.inputs[0], fac), (n.inputs[6], a), (n.inputs[7], b)):
            if isinstance(v, (float, tuple)):
                sock.default_value = v if isinstance(v, float) else (*v, 1)
            else:
                link(m, v, sock)
        return n.outputs[2]

    warp = node(m, "ShaderNodeTexNoise", Scale=3.0, Detail=3.0)
    link(m, co, warp.inputs["Vector"])
    wv = nt.nodes.new("ShaderNodeMix")
    wv.data_type = "VECTOR"
    wv.inputs["Factor"].default_value = 0.08
    link(m, co, wv.inputs[4])
    link(m, warp.outputs["Color"], wv.inputs[5])
    warped = wv.outputs[1]
    # microrelief: plateaus between furrows (1 on a plateau, 0 in a furrow), two sizes
    big = tex("ShaderNodeTexVoronoi", 13.0, Randomness=1.0, feature="DISTANCE_TO_EDGE")
    small = tex("ShaderNodeTexVoronoi", 34.0, Randomness=1.0, feature="DISTANCE_TO_EDGE")
    furrow = maprange(big.outputs["Distance"], 0.0, 0.2, smooth=True)  # rounded furrows, not cracks
    furrow2 = maprange(small.outputs["Distance"], 0.0, 0.22, smooth=True)
    # a few long, shallow creases running across (the skin folds this way)
    crease_n = tex("ShaderNodeTexWave", 1.6, Distortion=6.0, Detail=3.0)
    crease = maprange(crease_n.outputs["Fac"], 0.0, 0.08)
    # pores: tiny pits at random points (on top of the dimples modelled in the mesh)
    pores = tex("ShaderNodeTexVoronoi", 7.0, Randomness=0.9)
    pore = maprange(pores.outputs["Distance"], 0.04, 0.2, smooth=True)  # distances are in cell units
    # follicles: shaved hairs seen through the skin as soft dots, in a different pattern
    fol = node(m, "ShaderNodeTexVoronoi", Scale=4.5, Randomness=0.85)
    fol.voronoi_dimensions = "4D"
    fol.inputs["W"].default_value = 3.7
    link(m, warped, fol.inputs["Vector"])
    follicle = maprange(fol.outputs["Distance"], 0.05, 0.22, 1.0, 0.0, smooth=True)
    grain = tex("ShaderNodeTexNoise", 160.0, Detail=8.0)
    h = math_("MULTIPLY", furrow, 0.55)
    h = math_("ADD", h, math_("MULTIPLY", furrow2, 0.12))
    h = math_("ADD", h, math_("MULTIPLY", crease, 0.25))
    h = math_("MULTIPLY", h, pore)
    h = math_("ADD", h, math_("MULTIPLY", grain.outputs["Fac"], 0.08))
    bump = node(m, "ShaderNodeBump", Strength=0.28, Distance=0.01)
    link(m, h, bump.inputs["Height"])
    link(m, bump.outputs["Normal"], bsdf(m).inputs["Normal"])
    # colour: tone, redness, follicles, darker in furrows and pores
    tone = tex("ShaderNodeTexNoise", 2.2, Detail=5.0)
    base = mixc(maprange(tone.outputs["Fac"], 0.3, 0.7), (0.52, 0.24, 0.15), (0.64, 0.34, 0.22))
    red_n = tex("ShaderNodeTexNoise", 1.3, Detail=3.0, Roughness=0.6)
    red = maprange(red_n.outputs["Fac"], 0.48, 0.7, 0.0, 0.5)
    col = mixc(red, base, (0.62, 0.20, 0.17))
    col = mixc(math_("MULTIPLY", follicle, 0.7), col, (0.22, 0.18, 0.20))
    col = mixc(maprange(furrow, 0.0, 1.0, 0.22, 0.0), col, (0.40, 0.22, 0.18))
    col = mixc(maprange(pore, 0.0, 1.0, 0.75, 0.0), col, (0.22, 0.10, 0.08))
    link(m, col, bsdf(m).inputs["Base Color"])
    # oil: a thin clear coat, glossier in patches; dull in the furrows
    oil_n = tex("ShaderNodeTexNoise", 2.8, Detail=4.0)
    oil = maprange(oil_n.outputs["Fac"], 0.42, 0.62)
    link(m, math_("MULTIPLY", math_("MULTIPLY", oil, furrow), 0.35), bsdf(m).inputs["Coat Weight"])
    bsdf(m).inputs["Coat Roughness"].default_value = 0.22
    bsdf(m).inputs["Coat IOR"].default_value = 1.45
    link(m, maprange(oil, 0.0, 1.0, 0.55, 0.32), bsdf(m).inputs["Roughness"])
    return m


def epidermis_cut():
    """The epidermis seen in section: a pale horny layer on top, living layers, a darker basal row."""
    m = principled("epidermis", (0.80, 0.58, 0.50), 0.55, sss=0.6, radius=(0.05, 0.02, 0.01))
    co = obj_coords(m)
    sep = m.node_tree.nodes.new("ShaderNodeSeparateXYZ")
    link(m, co, sep.inputs["Vector"])
    r = m.node_tree.nodes.new("ShaderNodeValToRGB")
    els = r.color_ramp.elements
    els[0].position, els[0].color = 0.0, (0.36, 0.18, 0.14, 1)   # basal row (z = -EPI)
    els[1].position, els[1].color = 1.0, (0.84, 0.72, 0.60, 1)   # horny layer (z = 0)
    e = els.new(0.15)
    e.color = (0.62, 0.38, 0.30, 1)
    e = els.new(0.8)
    e.color = (0.70, 0.47, 0.37, 1)
    e = els.new(0.9)
    e.color = (0.80, 0.64, 0.52, 1)
    mr = m.node_tree.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = -EPI, 0.0
    link(m, sep.outputs["Z"], mr.inputs["Value"])
    link(m, mr.outputs["Result"], r.inputs["Fac"])
    link(m, r.outputs["Color"], bsdf(m).inputs["Base Color"])
    cells = node(m, "ShaderNodeTexVoronoi", Scale=70.0)
    link(m, co, cells.inputs["Vector"])
    tint = node(m, "ShaderNodeMix")  # each cell a shade lighter or darker, so the layer reads as cells
    tint.data_type = "RGBA"
    tint.blend_type = "MULTIPLY"
    tint.inputs["Factor"].default_value = 0.12
    link(m, r.outputs["Color"], tint.inputs[6])
    link(m, cells.outputs["Color"], tint.inputs[7])
    link(m, tint.outputs[2], bsdf(m).inputs["Base Color"])
    bump = node(m, "ShaderNodeBump", Strength=0.12, Distance=0.01)
    link(m, cells.outputs["Distance"], bump.inputs["Height"])
    link(m, bump.outputs["Normal"], bsdf(m).inputs["Normal"])
    return m


def dermis_cut():
    """Dermis in section: rosy pink, with wavy collagen fibres (stretched noise)."""
    m = principled("dermis", (0.80, 0.42, 0.42), 0.6, sss=0.7, radius=(0.12, 0.04, 0.03))
    co = obj_coords(m)
    mp = m.node_tree.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (5.0, 5.0, 26.0)
    link(m, co, mp.inputs["Vector"])
    wave = node(m, "ShaderNodeTexNoise", Scale=2.2, Detail=6.0, Distortion=1.5)
    link(m, mp.outputs["Vector"], wave.inputs["Vector"])
    r = m.node_tree.nodes.new("ShaderNodeValToRGB")
    r.color_ramp.elements[0].color = (0.70, 0.30, 0.32, 1)
    r.color_ramp.elements[1].color = (0.93, 0.62, 0.58, 1)
    link(m, wave.outputs["Fac"], r.inputs["Fac"])
    link(m, r.outputs["Color"], bsdf(m).inputs["Base Color"])
    bump = node(m, "ShaderNodeBump", Strength=0.3, Distance=0.02)
    link(m, wave.outputs["Fac"], bump.inputs["Height"])
    link(m, bump.outputs["Normal"], bsdf(m).inputs["Normal"])
    return m


def fat_cut():
    """Subcutaneous fat: yellow lobules (Voronoi cells) with pinkish septa between them."""
    m = principled("fat", (0.95, 0.80, 0.42), 0.35, sss=0.8, radius=(0.12, 0.08, 0.03))
    co = obj_coords(m)
    vor = node(m, "ShaderNodeTexVoronoi", Scale=5.5)
    vor.feature = "DISTANCE_TO_EDGE"
    link(m, co, vor.inputs["Vector"])
    r = m.node_tree.nodes.new("ShaderNodeValToRGB")
    r.color_ramp.elements[0].color = (0.78, 0.45, 0.38, 1)
    r.color_ramp.elements[0].position = 0.0
    r.color_ramp.elements[1].position = 0.05
    r.color_ramp.elements[1].color = (0.96, 0.82, 0.45, 1)
    link(m, vor.outputs["Distance"], r.inputs["Fac"])
    link(m, r.outputs["Color"], bsdf(m).inputs["Base Color"])
    bump = node(m, "ShaderNodeBump", Strength=0.6, Distance=0.05)
    link(m, vor.outputs["Distance"], bump.inputs["Height"])
    link(m, bump.outputs["Normal"], bsdf(m).inputs["Normal"])
    return m


M_SKIN, M_EPI, M_DERM, M_FAT = skin_top(), epidermis_cut(), dermis_cut(), fat_cut()
M_GLAND = principled("gland", (0.90, 0.60, 0.34), 0.35, sss=0.5, radius=(0.04, 0.02, 0.01))
M_APO = principled("apocrine", (0.80, 0.50, 0.30), 0.35, sss=0.5, radius=(0.04, 0.02, 0.01))
M_DUCT_GLASS = principled("duct window", (0.95, 0.66, 0.45), 0.15, alpha=0.28, spec=0.9)
M_SWEAT = principled("sweat", (0.16, 0.48, 0.95), 0.05, alpha=0.9, emit=0.6)
M_PLUG = principled("gel plug", (0.45, 0.85, 1.0), 0.06, alpha=0.6, emit=0.0, spec=1.0)
M_WATER = principled("droplet", (1.0, 1.0, 1.0), 0.02, trans=1.0, ior=1.33)
M_HAIR = principled("hair", (0.05, 0.03, 0.02), 0.55, spec=0.35)
M_FINE = principled("fine hair", (0.16, 0.10, 0.07), 0.4, sss=0.4, radius=(0.01, 0.006, 0.004), spec=0.5)
M_FOLL = principled("follicle", (0.82, 0.56, 0.44), 0.4, sss=0.5, radius=(0.04, 0.02, 0.01))
M_SEB = principled("sebaceous", (0.98, 0.88, 0.58), 0.3, sss=0.7, radius=(0.05, 0.04, 0.02))
M_CAP = principled("capillary", (0.48, 0.04, 0.05), 0.35, sss=0.3, radius=(0.02, 0.01, 0.01))
M_BACT = principled("bacteria", (0.45, 0.55, 0.16), 0.3, sss=0.6, radius=(0.02, 0.02, 0.01), emit=0.15)
M_SCENT = principled("fragrance", (0.95, 0.70, 0.90), 0.3, alpha=0.7, emit=2.0)
M_SALT = principled("salt", (0.96, 0.97, 1.0), 0.15, trans=0.5, ior=1.5, emit=0.15)
M_FLAKE = principled("flake", (0.93, 0.85, 0.76), 0.6, alpha=0.85, sss=0.3)
M_WAX = principled("product", (0.97, 0.97, 0.98), 0.55, sss=0.4, radius=(0.05, 0.05, 0.05))
M_INK = principled("ink", (0.10, 0.12, 0.16), 0.35)
M_INK2 = principled("ink accent", (0.20, 0.45, 0.80), 0.35)


def keyed(m, socket, frame, value):
    s = bsdf(m).inputs[socket]
    s.default_value = value
    s.keyframe_insert("default_value", frame=frame)


# --- the skin's top surface -----------------------------------------------------------------------------------------
def pore_points():
    pts = [PORE_E, PORE_H]
    tries = 0
    while len(pts) < 260 and tries < 20000:
        tries += 1
        p = Vector((rng.uniform(X0, X1), rng.uniform(YF + 0.03, YB)))
        if all((p - q).length > 0.17 for q in pts):
            pts.append(p)
    return pts


PORES = pore_points()
BUCKET = {}
for _p in PORES:
    BUCKET.setdefault((int(math.floor(_p.x / 0.1)), int(math.floor(_p.y / 0.1))), []).append(_p)


def height(x, y):
    h = 0.012 * noise.noise(Vector((x * 1.3, y * 1.3, 0.5))) + 0.004 * noise.noise(Vector((x * 6, y * 6, 2.0)))
    bx, by = int(math.floor(x / 0.1)), int(math.floor(y / 0.1))
    near = [p for i in (-1, 0, 1) for j in (-1, 0, 1) for p in BUCKET.get((bx + i, by + j), ())]
    for p in near:
        d2 = (x - p.x) ** 2 + (y - p.y) ** 2
        if d2 < 0.01:
            deep = 0.03 if p in (PORE_E, PORE_H) else 0.016
            h -= deep * math.exp(-d2 / (0.019 ** 2))
            h += 0.004 * math.exp(-d2 / (0.034 ** 2))  # a faint rim
    return h


def grid(nx, ny):
    """The epidermis as a solid: the displaced top, walls down to -EPI on all four sides. The front wall (the cut)
    and the others get the section material."""
    bm = bmesh.new()
    xs = [X0 + (X1 - X0) * i / nx for i in range(nx + 1)]
    ys = []
    y = YF
    while y < YB:  # finer near the front edge, where the camera looks closest
        ys.append(y)
        y += 0.006 if y < YF + 0.6 else 0.014 if y < YF + 1.6 else 0.03
    ys.append(YB)
    top = [[bm.verts.new((x, y, height(x, y))) for x in xs] for y in ys]
    for j in range(len(ys) - 1):
        for i in range(nx):
            f = bm.faces.new((top[j][i], top[j][i + 1], top[j + 1][i + 1], top[j + 1][i]))
            f.material_index = 0
            f.smooth = True
    ring = [top[0][i] for i in range(nx + 1)] + [top[j][nx] for j in range(1, len(ys))] + \
           [top[-1][i] for i in range(nx - 1, -1, -1)] + [top[j][0] for j in range(len(ys) - 2, 0, -1)]
    low = [bm.verts.new((v.co.x, v.co.y, -EPI)) for v in ring]
    n = len(ring)
    for i in range(n):
        f = bm.faces.new((ring[(i + 1) % n], ring[i], low[i], low[(i + 1) % n]))
        f.material_index = 1
    me = bpy.data.meshes.new("epidermis")
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M_SKIN)
    me.materials.append(M_EPI)
    o = bpy.data.objects.new("epidermis", me)
    scene.collection.objects.link(o)
    return o


def box(name, x0, x1, y0, y1, z0, z1, mat):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector(((x0 + x1) / 2 + v.co.x * (x1 - x0), (y0 + y1) / 2 + v.co.y * (y1 - y0),
                       (z0 + z1) / 2 + v.co.z * (z1 - z0)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    return o


SKIN = [grid(420, 0), box("dermis", X0, X1, YF, YB, -DERM, -EPI + 0.002, M_DERM),
        box("fat", X0, X1, YF, YB, -FAT, -DERM, M_FAT)]


# --- tubes ---------------------------------------------------------------------------------------------------------
def tube(name, pts, radius, mat, radii=None, caps=True, res=8):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = res // 2
    cu.use_fill_caps = caps
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        sp.points[i].co = (*p, 1)
        sp.points[i].radius = radii[i] if radii else 1.0
    cu.materials.append(mat)
    o = bpy.data.objects.new(name, cu)
    scene.collection.objects.link(o)
    return o


def resample(pts, step=0.008):
    out = [Vector(pts[0])]
    for a, b in zip(pts, pts[1:]):
        a, b = Vector(a), Vector(b)
        n = max(1, int((b - a).length / step))
        out += [a.lerp(b, (i + 1) / n) for i in range(n)]
    return out


def chaikin(pts, n=3):
    for _ in range(n):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out += [a.lerp(b, 0.25), a.lerp(b, 0.75)]
        out.append(pts[-1])
        pts = out
    return pts


def coil(center, r, loops, seed, flat=0.35):
    """A coiled gland: a looping path that stays in a ball of radius r, flattened toward the cut face."""
    g = random.Random(seed)
    pts = []
    n = loops * 24
    ph = [g.uniform(0, 6.28) for _ in range(6)]
    for i in range(n + 1):
        t = i / n * loops * 2 * math.pi
        x = math.sin(t * 1.0 + ph[0]) * 0.65 + 0.35 * math.sin(t * 0.37 + ph[1])
        z = math.cos(t * 1.0 + ph[2]) * 0.55 + 0.45 * math.sin(t * 0.23 + ph[3])
        y = math.sin(t * 0.61 + ph[4]) * flat
        pts.append(center + Vector((x * r, y * r - r * flat, z * r)))
    return pts


def eccrine_paths():
    c = Vector((PORE_E.x + 0.02, FRONT, -1.12))
    gl = coil(c, 0.16, 7, 3)
    top = gl[-1]
    rise = [top, Vector((PORE_E.x + 0.05, FRONT - 0.01, -0.85)), Vector((PORE_E.x - 0.03, FRONT - 0.012, -0.58)),
            Vector((PORE_E.x + 0.02, FRONT - 0.015, -0.36))]
    spiral = []  # the duct winds through the epidermis (the acrosyringium)
    for i in range(41):
        f = i / 40
        z = -0.36 + f * (0.36 + height(PORE_E.x, PORE_E.y) - 0.012)
        spiral.append(Vector((PORE_E.x + 0.02 * math.cos(f * 2.2 * math.pi) - 0.0, FRONT - 0.015 - 0.008 * math.sin(f * 2.2 * math.pi), z)))
    duct = chaikin(rise + spiral[1:], 3)
    return gl, resample(duct)


GLAND_E, DUCT_E = eccrine_paths()
WIN = next(i for i, p in enumerate(DUCT_E) if p.z > -0.5)  # the clear window starts here
tube("eccrine gland", chaikin(GLAND_E, 2), 0.034, M_GLAND)
tube("eccrine duct", DUCT_E[: WIN + 2], 0.026, M_GLAND)
tube("duct window", DUCT_E[WIN:], 0.03, M_DUCT_GLASS, caps=False, res=12)
SWEAT_COL = tube("sweat column", DUCT_E[WIN:], 0.019, M_SWEAT, caps=True)
_n = len(DUCT_E[WIN:])
PLUG = tube("gel plug", DUCT_E[WIN:], 0.022, M_PLUG, caps=True, res=10,  # a rounded top, not a cut pipe
            radii=[max(0.15, math.sqrt(max(0.0, 1 - ((i - (_n - 5)) / 4.0) ** 2))) if i > _n - 5 else 1.0 for i in range(_n)])
for _o in (PLUG, SWEAT_COL):
    _o.data.bevel_factor_mapping_start = _o.data.bevel_factor_mapping_end = "SPLINE"


def follicle_paths():
    top = Vector((PORE_H.x, FRONT, height(PORE_H.x, PORE_H.y) - 0.01))
    bulb = Vector((PORE_H.x - 0.32, FRONT, -1.12))
    shaft = [top.lerp(bulb, i / 30) for i in range(31)]
    return top, bulb, shaft


H_TOP, H_BULB, H_SHAFT = follicle_paths()
tube("follicle", H_SHAFT, 0.055, M_FOLL)
bulb = bpy.data.objects.new("bulb", bpy.data.meshes.new("bulb"))
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=0.085)
bm.to_mesh(bulb.data)
bm.free()
for p in bulb.data.polygons:
    p.use_smooth = True
bulb.data.materials.append(M_FOLL)
bulb.location = H_BULB
bulb.scale = (1.0, 0.9, 1.15)
scene.collection.objects.link(bulb)
# the hair shaft: inside the follicle, then out of the skin, leaning and curling a little
out_dir = (H_TOP - H_BULB).normalized()
lean = Vector((0.35, 0.75, 0.55)).normalized()  # leaning away from the camera, which looks in from the front
above = [H_TOP + lean * (0.045 * i) + Vector((-0.0002 * i * i, 0, -0.0002 * i * i)) for i in range(11)]
inside = [p + Vector((0, -0.035, 0)) for p in H_SHAFT[::-1][:-1]]  # drawn on the follicle's open face
shaft = resample(inside + [above[0] + Vector((0, -0.035, 0))] + above[1:], 0.01)
tube("hair shaft", shaft, 0.017, M_HAIR, radii=[1.0 if p.z < 0 else 0.75 for p in shaft[:-4]] + [0.6, 0.42, 0.25, 0.08])


def sphere(name, loc, r, mat, seg=16):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(8, seg // 2), radius=r)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    o.location = loc
    scene.collection.objects.link(o)
    return o


for i, (dx, dz, r) in enumerate([(0.0, -0.34, 0.05), (0.04, -0.40, 0.045), (0.0, -0.46, 0.05), (0.05, -0.31, 0.035),
                                  (0.03, -0.51, 0.04)]):
    f = (H_TOP.z - dz) / (H_TOP.z - H_BULB.z)
    sphere(f"sebaceous {i}", H_TOP.lerp(H_BULB, f) + Vector((0.085 + dx, -0.01, 0)), r, M_SEB)

APO_C = Vector((PORE_H.x + 0.06, FRONT, -1.36))
GLAND_A = coil(APO_C, 0.2, 5, 9, flat=0.3)
join = H_TOP.lerp(H_BULB, 0.23)  # the apocrine duct enters the follicle above the sebaceous gland
DUCT_A = resample(chaikin([GLAND_A[-1], APO_C + Vector((0.12, -0.01, 0.3)), Vector((join.x + 0.2, FRONT - 0.01, -0.7)),
                           Vector((join.x + 0.09, FRONT - 0.012, join.z - 0.08)), join], 3))
tube("apocrine gland", chaikin(GLAND_A, 2), 0.045, M_APO)
tube("apocrine duct", DUCT_A, 0.03, M_APO)

# a few capillary loops just under the epidermis, on the cut face
for i, x in enumerate([-1.35, -1.0, -0.25, 0.05, 0.75, 1.05, 1.4]):
    base = -EPI - 0.18
    loop = [Vector((x - 0.035, FRONT + 0.004, base)), Vector((x - 0.03, FRONT + 0.002, -EPI - 0.03)),
            Vector((x, FRONT, -EPI + 0.005)), Vector((x + 0.03, FRONT + 0.002, -EPI - 0.03)),
            Vector((x + 0.035, FRONT + 0.004, base))]
    tube(f"capillary {i}", resample(chaikin(loop, 3)), 0.0055, M_CAP)
tube("arteriole", resample(chaikin([Vector((X0, FRONT + 0.01, -0.95)), Vector((-1.2, FRONT, -0.88)),
                                    Vector((-0.75, FRONT, -1.0)), Vector((-0.2, FRONT, -0.93)), Vector((0.5, FRONT, -1.02)),
                                    Vector((1.0, FRONT, -0.9)), Vector((X1, FRONT + 0.01, -0.97))], 3)), 0.016, M_CAP)

# fine hairs on the top surface (a few dozen; underarm skin is shaved or not, these read as "skin up close")
for i in range(70):
    p = rng.choice(PORES[2:])
    if p.y > YF + 1.9:
        continue
    root = Vector((p.x, p.y, height(p.x, p.y) - 0.01))
    yaw = rng.uniform(0, 2 * math.pi)
    lean = rng.uniform(0.75, 1.2)  # fine hairs lie close to the skin
    length = rng.uniform(0.2, 0.6)
    d = Vector((math.cos(yaw) * math.sin(lean), math.sin(yaw) * math.sin(lean), math.cos(lean)))
    side = Vector((-math.sin(yaw), math.cos(yaw), 0)) * rng.uniform(-0.12, 0.12)
    pts = []
    for k in range(16):
        f = k / 15
        pts.append(root + d * length * f + side * length * f * f + Vector((0, 0, -0.22 * length * f * f)))
    tube(f"hair {i}", pts, 0.0055, M_FINE, radii=[1 - 0.8 * k / 15 for k in range(16)], res=6)


# --- props -----------------------------------------------------------------------------------------------------
def droplet(name, at, r):
    o = sphere(name, Vector((at.x, at.y, height(at.x, at.y) - r * 0.25)), r, M_WATER, seg=32)
    o.scale = (1, 1, 0.62)
    return o


DROP_E = droplet("sweat drop", Vector((PORE_E.x, PORE_E.y + 0.045)), 0.075)
DROPS = [DROP_E] + [droplet(f"drop {i}", p, rng.uniform(0.035, 0.065))
                    for i, p in enumerate([q for q in PORES[2:] if YF + 0.15 < q.y < YF + 1.4 and -0.6 < q.x < 1.4][:9])]
SALT_DROP = sphere("salty drop", DROP_E.location, 0.075, principled("salty", (0.92, 0.95, 1.0), 0.2, alpha=0.0))
SALT_DROP.scale = (1.0, 1.0, 0.62)

BACT_AT = next(p for p in sorted(PORES[2:], key=lambda q: (q - Vector((PORE_H.x + 0.05, YF + 0.42))).length))
BACT = []
for i in range(110):
    a = rng.uniform(0, 2 * math.pi)
    rr = 0.04 + 0.22 * math.sqrt(rng.random())
    x, y = BACT_AT.x + math.cos(a) * rr * 1.2, BACT_AT.y + math.sin(a) * rr
    o = sphere(f"bacterium {i}", Vector((x, y, height(x, y) + 0.008)), 0.0085, M_BACT, seg=10)
    o["scale"] = (1.0, 1.0, rng.uniform(2.2, 3.6)) if i % 3 else (1.0, 1.0, 1.0)  # rods and a few cocci
    o.rotation_euler = (math.pi / 2, 0, rng.uniform(0, math.pi))
    o["born"] = rng.random()
    BACT.append(o)

SCENT = []
for i in range(36):
    o = sphere(f"scent {i}", Vector((0, 0, 0)), rng.uniform(0.008, 0.02), M_SCENT, seg=10)
    o["seed"] = [rng.uniform(-0.5, 0.5), rng.uniform(0.0, 0.6), rng.uniform(0, 6.28), rng.uniform(0.3, 0.7)]
    SCENT.append(o)


def crystal(name, size):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=size * 0.08, segments=1, affect="EDGES")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M_SALT)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    return o


SALTS = []
for i in range(16):
    o = crystal(f"salt {i}", rng.uniform(0.02, 0.034))
    o["seed"] = [rng.uniform(-0.09, 0.09), rng.uniform(-0.02, 0.1), rng.uniform(0, 0.5), rng.uniform(0, 6.28)]
    SALTS.append(o)

FLAKES = []
for i in range(14):
    me = bpy.data.meshes.new(f"flake {i}")
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=True, segments=6, radius=rng.uniform(0.03, 0.05))
    for v in bm.verts:
        v.co *= rng.uniform(0.75, 1.15)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M_FLAKE)
    o = bpy.data.objects.new(f"flake {i}", me)
    scene.collection.objects.link(o)
    o["seed"] = [rng.uniform(-0.25, 0.25), rng.uniform(0.0, 0.25), rng.uniform(0, 0.6), rng.uniform(-1, 1)]
    FLAKES.append(o)

# the stick, off to the side for the hook (Nov 23: a hero shot): a glossy electric-blue oval case with plain white
# print, the cap pops off, the white product twists up, fine mist hangs in the rim light. No brand, logo or trade dress.
STICK_AT = Vector((60.0, 0.0, 0.0))
SA, SB, SZ = 0.78, 0.38, 1.3  # the case's half width, half depth and half height
M_STICK = principled("stick", (0.004, 0.11, 0.9), 0.16, spec=0.6)
bsdf(M_STICK).inputs["Coat Weight"].default_value = 1.0
bsdf(M_STICK).inputs["Coat Roughness"].default_value = 0.04
M_PRINT = principled("print", (0.95, 0.96, 0.98), 0.3)
M_PRINT2 = principled("print accent", (0.55, 0.85, 1.0), 0.3, emit=0.15)
M_MIST = principled("mist", (0.85, 0.93, 1.0), 0.3, alpha=0.4, emit=1.0)


def oval(name, z0, z1, a, b, mat, top=True, bottom=True):
    """An oval prism (a superellipse in section, flat enough at the front for print) from z0 to z1."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    n = 96
    ring = []
    for i in range(n):
        t = 2 * math.pi * i / n
        c, s_ = math.cos(t), math.sin(t)
        ring.append((a * math.copysign(abs(c) ** 0.5, c), b * math.copysign(abs(s_) ** 0.5, s_)))
    lo = [bm.verts.new((x, y, z0)) for x, y in ring]
    hi = [bm.verts.new((x, y, z1)) for x, y in ring]
    for i in range(n):
        bm.faces.new((lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]))
    if top:
        bm.faces.new(hi)
    if bottom:
        bm.faces.new(lo[::-1])
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = len(p.vertices) == 4
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    bev = o.modifiers.new("bevel", "BEVEL")
    bev.width, bev.segments, bev.limit_method = 0.05, 4, "ANGLE"
    o.modifiers.new("smooth", "WEIGHTED_NORMAL")
    return o


def pivot(name, at):
    e = bpy.data.objects.new(name, None)
    e.location = at
    scene.collection.objects.link(e)
    return e


def stick():
    case = oval("stick", -SZ, SZ, SA, SB, M_STICK)
    case.location = STICK_AT
    prod = pivot("product pivot", STICK_AT + Vector((0, 0, SZ)))  # the product: a column with a domed top
    col = oval("product column", -0.45, 0.02, SA * 0.9, SB * 0.84, M_WAX, top=False)
    col.parent = prod
    dome = sphere("product", Vector((0, 0, 0.02)), 1.0, M_WAX, seg=48)
    dome.scale = (SA * 0.88, SB * 0.82, 0.17)
    dome.parent = prod
    cap = pivot("cap pivot", STICK_AT + Vector((0, 0, SZ - 0.06)))
    shell = oval("cap", 0.0, 0.78, SA * 1.025, SB * 1.06, M_STICK)
    shell.parent = cap
    lid = sphere("cap top", Vector((0, 0, 0.78)), 1.0, M_STICK, seg=48)
    lid.scale = (SA * 1.02, SB * 1.05, 0.1)
    lid.parent = cap
    font = bpy.data.fonts.load(str(ROOT / "assets" / "fonts" / "Inter-ExtraBold.otf"))
    for text, z, size, mat in (("ANTIPERSPIRANT", 1.0, 0.1, M_PRINT2), ("+", 0.86, 0.11, M_PRINT2),
                               ("DEODORANT", 0.66, 0.19, M_PRINT)):
        cu = bpy.data.curves.new(text, "FONT")
        cu.body, cu.font, cu.size, cu.align_x, cu.align_y = text, font, size, "CENTER", "CENTER"
        cu.extrude = 0.003
        cu.materials.append(mat)
        t = bpy.data.objects.new(text, cu)
        t.location = STICK_AT + Vector((0, -SB - 0.004, z))
        t.rotation_euler = (math.pi / 2, 0, 0)
        scene.collection.objects.link(t)
    return case, prod, cap


MIST = []
for i in range(150):
    burst = i < 60  # these fly out of the cap's rim when it pops; the rest hang in the air
    o = sphere(f"mist {i}", STICK_AT, rng.uniform(0.006, 0.02), M_MIST, seg=8)
    if burst:
        a_ = rng.uniform(0, 2 * math.pi)
        o["seed"] = [1, math.cos(a_), math.sin(a_) * 0.6, rng.uniform(0.3, 1.2), rng.uniform(0.6, 1.6), rng.uniform(0, 6.28)]
    else:
        o["seed"] = [0, rng.uniform(-2.2, 2.2), rng.uniform(-1.8, 1.6), rng.uniform(-0.6, 3.2), rng.uniform(0.05, 0.16),
                     rng.uniform(0, 6.28)]
    MIST.append(o)

STICK, PRODUCT, CAP = stick()


# --- stage -------------------------------------------------------------------------------------------------------
def light(name, loc, power, size, color=(1, 1, 1), at=Vector((0, 0, -0.6))):
    l = bpy.data.lights.new(name, "AREA")
    l.size, l.energy, l.color = size, power, color
    o = bpy.data.objects.new(name, l)
    scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (at - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return o


KEY = light("key", (-4.5, -5.0, 4.0), spec.get("key", 1500), 4.0)
FILL = light("fill", (5.0, -4.0, 0.5), spec.get("fill", 260), 6.0, (0.95, 0.97, 1.0))
RIM = light("rim", (1.5, 6.0, 4.5), spec.get("rim", 1500), 3.0)
TOP = light("top", (0.0, 1.0, 6.0), 400, 5.0, (1.0, 0.98, 0.95))
light("stick key", tuple(STICK_AT + Vector((-4, -6, 3))), 1300, 3.0, at=STICK_AT)
light("stick fill", tuple(STICK_AT + Vector((5, -4, 0))), 300, 6.0, (0.95, 0.97, 1.0), at=STICK_AT)
light("stick rim L", tuple(STICK_AT + Vector((-3.5, 3.5, 2.5))), 2600, 1.5, (0.8, 0.9, 1.0), at=STICK_AT + Vector((0, 0, 1)))
light("stick rim R", tuple(STICK_AT + Vector((3.5, 3.5, 2.0))), 2600, 1.5, (0.8, 0.9, 1.0), at=STICK_AT + Vector((0, 0, 1)))
light("stick top", tuple(STICK_AT + Vector((0, 1.0, 6.0))), 900, 2.0, at=STICK_AT + Vector((0, 0, 1.5)))
scene.world = bpy.data.worlds.new("world")
scene.world.use_nodes = True
BG = scene.world.node_tree.nodes["Background"]
BG.inputs[0].default_value = (0.32, 0.33, 0.35, 1)
BG.inputs[1].default_value = spec.get("world", 0.22)
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = spec.get("width", 1080), spec.get("height", 1920)
scene.render.fps = FPS
scene.eevee.taa_render_samples = spec.get("samples", 32)
scene.eevee.use_raytracing = True
scene.eevee.ray_tracing_options.resolution_scale = "1"
scene.eevee.use_shadows = True
scene.eevee.shadow_ray_count = 2
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast"
scene.view_settings.exposure = spec.get("exposure", -1.05)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.lens = 50
cam.data.sensor_fit = "VERTICAL"
cam.data.clip_start = 0.01
cam.data.dof.use_dof = True
TAN = 12 / cam.data.lens


# --- the camera, shot by shot -----------------------------------------------------------------------------------
def view(target, yaw, pitch, dist, fstop=6.0):
    return {"t": Vector(target), "yaw": yaw, "pitch": pitch, "d": dist, "f": fstop}


def mix(a, b, f):
    return {"t": a["t"].lerp(b["t"], f), "yaw": a["yaw"] + (b["yaw"] - a["yaw"]) * f,
            "pitch": a["pitch"] + (b["pitch"] - a["pitch"]) * f, "d": a["d"] * (b["d"] / a["d"]) ** f,
            "f": a["f"] + (b["f"] - a["f"]) * f}


def pose(v):
    yaw, pitch = math.radians(v["yaw"]), math.radians(v["pitch"])
    fwd = Vector((math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)))
    loc = v["t"] - fwd * v["d"]
    return loc, fwd.to_track_quat("-Z", "Y").to_euler()


def keys_for(s):
    """[(time, view)] for a shot. Eased between keys; a shot holds its first and last view outside them."""
    a, b, k = s["start"], s["end"], s["kind"]
    E, H = Vector((PORE_E.x, YF, 0)), Vector((PORE_H.x, YF, 0))
    B = Vector((BACT_AT.x, BACT_AT.y - 0.05, 0.0))
    if k == "stick":
        hero, top = STICK_AT + Vector((0, -0.38, 1.1)), STICK_AT + Vector((0, -0.1, 1.55))
        # a slow push-in that keeps the print in view for "Check the label", then the whip into the skin
        return [(a, view(hero, -10, 4, 7.6, 1.6)), (b - 0.25, view(hero + Vector((0, 0, 0.1)), -3, 6, 6.6, 1.6)),
                (b, view(hero + Vector((3.0, 0, 0.1)), 40, 6, 6.6, 1.6))]
    if k == "surface":
        far = view(E + Vector((0.12, 0.42, 0.0)), 205, -17, 1.25, 1.1)
        return [(a, view(E + Vector((-1.2, 0.5, 0)), 175, -17, 1.25, 1.1)), (a + 0.27, far),
                (b, view(E + Vector((0.05, 0.22, 0.0)), 196, -19, 0.95, 1.0))]
    if k == "apocrine":
        wide = view(Vector((PORE_H.x - 0.05, YF, -1.11)), 0, 0, 6.75, 12)
        return [(a, view(Vector((PORE_H.x, YF, -0.5)), 60, -8, 3.6, 8)), (a + 1.0, wide),
                (L(4) - 0.2, view(Vector((PORE_H.x - 0.05, YF, -1.0)), -3, 0, 6.3, 12)),
                (L(4) + 1.0, view(B, -8, -42, 1.2, 4.0)), (b, view(B, -12, -44, 1.1, 4.0))]
    if k == "deodorant":
        return [(a, view(B, -12, -44, 1.1, 4.0)), (b, view(B + Vector((0.03, 0, 0.04)), -20, -46, 1.25, 4.0))]
    if k == "eccrine":
        wide = view(Vector((PORE_E.x, YF, -0.98)), 4, 0, 6.0, 12)  # the surface near y 300, the coil above the captions
        close = view(E + Vector((0.0, 0.0, -0.1)), 10, -12, 1.25, 5.0)
        return [(a, view(Vector((0.0, YF, -0.6)), -25, -4, 5.4, 12)), (a + 0.9, wide), (L(7) - 0.1, wide),
                (L(7) + 0.9, close), (L(8) + 0.3, view(E + Vector((0.0, 0.0, -0.16)), 6, -8, 1.0, 5.0)),
                (b, view(E + Vector((0.0, 0.0, -0.12)), 2, -10, 1.15, 5.0))]
    if k == "renew":
        return [(a, view(E + Vector((0.0, 0.0, -0.12)), 2, -10, 1.15, 5.0)), (b, view(E + Vector((0.0, 0.05, -0.05)), -10, -22, 1.3, 5.0))]
    if k == "night":
        return [(a, view(E + Vector((-0.4, 0.4, -0.05)), -20, -32, 2.2, 5.0)), (b, view(E + Vector((-0.35, 0.4, -0.05)), -28, -34, 2.0, 5.0))]
    if k == "calm":
        return [(a, view(Vector((-0.1, 0.0, -0.95)), 28, -16, 8.5, 16)), (b, view(Vector((-0.1, 0.0, -0.95)), 14, -14, 8.0, 16))]
    return [(a, view(Vector((0, 0, 500)), 0, 0, 1, 16))]  # the chart: nothing of the 3D layer shows


def camera(t):
    s = next((s for s in SHOTS if s["start"] <= t < s["end"]), SHOTS[-1])
    ks = keys_for(s)
    if t <= ks[0][0]:
        return ks[0][1]
    for (ta, va), (tb, vb) in zip(ks, ks[1:]):
        if ta <= t < tb:
            return mix(va, vb, smooth((t - ta) / max(1e-6, tb - ta)))
    return ks[-1][1]


# --- the story, frame by frame ------------------------------------------------------------------------------------
def on_path(pts, f):
    f = min(1.0, max(0.0, f)) * (len(pts) - 1)
    i = min(int(f), len(pts) - 2)
    return pts[i].lerp(pts[i + 1], f - i)


T_SURF, T_APO, T_DEO, T_ECC, T_REN, T_NIGHT = (shot(k)["start"] for k in ("surface", "apocrine", "deodorant", "eccrine", "renew", "night"))
T_SALT, T_PLUG, T_LESS = L(7), L(8), L(9)
T_BACT = L(4)
T_POP = 0.5  # the cap pops; before it, a capped stick that reads as a stick on its own
T_HERO_END = shot("stick")["end"] + 0.1
PLUG_TOP = 0.55  # the plug fills the top 45% of the clear window


def state(t):
    """Everything that moves, as a dict of values at time t."""
    s = {}
    # droplets: bead up on the surface shot, stay, then dry off for the night tip
    grow = ramp(t, T_SURF + 0.2, T_SURF + 1.6)
    dry = ramp(t, T_NIGHT, T_NIGHT + 1.2)
    s["drops"] = grow * (1 - dry)
    # the eccrine drop: shrinks once the plug holds ("less sweat gets out"), comes back a little at renew
    s["drop_e"] = s["drops"] * (1 - 0.75 * ramp(t, T_LESS, T_LESS + 1.0)) + 0.35 * ramp(t, T_REN + 0.6, T_REN + 1.8) * (1 - dry)
    # sweat rising in the duct, all the time except where the plug blocks it
    s["sweat_end"] = 1.0
    plug = ramp(t, T_PLUG, T_PLUG + 1.4) * (1 - ramp(t, T_REN + 0.2, T_REN + 1.6))
    s["plug"] = plug
    s["salt_cloud"] = ramp(t, T_SALT + 0.5, T_SALT + 1.6) * (1 - ramp(t, T_PLUG + 0.6, T_PLUG + 1.6))
    s["bact"] = ramp(t, T_BACT - 0.1, T_BACT + 1.2)
    s["bact_kill"] = ramp(t, T_DEO + 0.3, T_DEO + 1.8)
    s["scent"] = ramp(t, T_DEO + 0.6, T_DEO + 1.6) * (1 - ramp(t, T_ECC - 0.2, T_ECC + 0.3))
    s["flakes"] = ramp(t, T_REN, T_REN + 2.2)
    return s


SHAPES = {o.name: tuple(o.scale) for o in DROPS}
BASE = {o.name: o.location.copy() for o in DROPS + BACT}
anchors = {}
for k in range(TOTAL):
    t = k / FPS
    v = camera(t)
    loc, rot = pose(v)
    cam.location, cam.rotation_euler = loc, rot
    cam.data.dof.focus_distance = v["d"]
    cam.data.dof.aperture_fstop = v["f"]
    for path in ("location", "rotation_euler"):
        cam.keyframe_insert(path, frame=k)
    cam.data.dof.keyframe_insert("focus_distance", frame=k)
    cam.data.dof.keyframe_insert("aperture_fstop", frame=k)
    st = state(t)
    # the hero stick: the cap pops off at T_POP and flies up and away, the product twists up, mist drifts
    hero = t <= T_HERO_END
    up = ease((t - T_POP) / 0.9) if t >= T_POP else 0.0
    jig = 0.015 * math.sin(t * 60) * ramp(t, T_POP - 0.2, T_POP) if t < T_POP else 0.0
    CAP.location = STICK_AT + Vector((0.6 * up, 0.3 * up, SZ - 0.06 + jig + 2.6 * up))
    CAP.rotation_euler = (math.radians(-35) * up, math.radians(20) * up, math.radians(25) * up)
    rise = smooth((t - T_POP - 0.35) / 1.3)
    PRODUCT.location = STICK_AT + Vector((0, 0, SZ + 0.4 * rise))
    PRODUCT.rotation_euler = (0, 0, 0)  # it slides straight up (an oval can't turn inside an oval case)
    for o in (CAP, PRODUCT) if hero else ():
        o.keyframe_insert("location", frame=k)
        o.keyframe_insert("rotation_euler", frame=k)
    for o in MIST if hero else ():
        sd = o["seed"]
        if sd[0]:  # out of the cap's rim
            f = ease((t - T_POP) / 1.6) if t >= T_POP else 0.0
            o.location = STICK_AT + Vector((sd[1] * (SA + sd[3] * f), sd[2] * (SB + sd[3] * f) - 0.1, SZ + sd[4] * f))
            g = (1 - ramp(t, T_POP + 0.6, T_POP + 2.4)) if t >= T_POP else 0.0
        else:
            o.location = STICK_AT + Vector((sd[1] + 0.06 * math.sin(t * 0.7 + sd[5]), sd[2], sd[3] + sd[4] * t))
            g = 1.0
        o.scale = (max(g, 0.001),) * 3
        o.keyframe_insert("location", frame=k)
        o.keyframe_insert("scale", frame=k)
    for j, o in enumerate(DROPS):
        g = st["drop_e"] if o is DROP_E else st["drops"] * (0.85 + 0.15 * math.sin(j * 1.7 + t * 0.8))
        sx, sy, sz = SHAPES[o.name]
        o.scale = (sx * max(g, 0.001), sy * max(g, 0.001), sz * max(g, 0.001))
        o.keyframe_insert("scale", frame=k)
    SALT_DROP.scale = DROP_E.scale
    SALT_DROP.keyframe_insert("scale", frame=k)
    for o in BACT:
        born = ramp(st["bact"], o["born"] * 0.6, o["born"] * 0.6 + 0.4)
        shrink = 1 - 0.65 * st["bact_kill"]
        sx, sy, sz = o["scale"]
        g = max(born * shrink, 0.001)
        o.scale = (sx * g, sy * g, sz * g)
        o.keyframe_insert("scale", frame=k)
    for i, o in enumerate(SCENT):
        dx, dy, ph, sp = o["seed"]
        rise = (t * sp * 0.25 + ph) % 1.0
        o.location = Vector((BACT_AT.x + dx + 0.05 * math.sin(t * 1.3 + ph), BACT_AT.y + dy - 0.1, 0.03 + rise * 0.45))
        g = st["scent"] * math.sin(rise * math.pi)
        o.scale = (max(g, 0.001),) * 3
        o.keyframe_insert("location", frame=k)
        o.keyframe_insert("scale", frame=k)
    for o in SALTS:
        dx, dy, delay, spin = o["seed"]
        a0 = T_SALT + delay
        fall = ease((t - a0) / 0.5)
        landed = Vector((PORE_E.x + dx, PORE_E.y + 0.045 + dy, height(PORE_E.x + dx, PORE_E.y + dy) + 0.03))
        o.location = landed + Vector((0, 0, 0.9 * (1 - fall)))
        o.rotation_euler = (spin + t * 0.8, spin * 0.5, spin + t * 0.5)
        melt = 1 - ramp(t, a0 + 0.55, a0 + 1.4)
        vis = 1.0 if t >= a0 - 0.02 else 0.0
        o.scale = (max(vis * melt, 0.001),) * 3
        for p in ("location", "rotation_euler", "scale"):
            o.keyframe_insert(p, frame=k)
    for i, o in enumerate(FLAKES):
        dx, dy, delay, tilt = o["seed"]
        f = ramp(st["flakes"], delay * 0.6, delay * 0.6 + 0.5)
        x, y = PORE_E.x + dx, PORE_E.y + 0.04 + dy
        o.location = Vector((x, y, height(x, y) + 0.004 + 0.5 * f * f))
        o.rotation_euler = (tilt * f * 1.2, tilt * f * 0.6, tilt * 3)
        o.scale = (max(1 - ramp(f, 0.6, 1.0), 0.001) if st["flakes"] > 0 else 0.001,) * 3
        for p in ("location", "rotation_euler", "scale"):
            o.keyframe_insert(p, frame=k)
    PLUG.data.bevel_factor_start = 1.0 - (1.0 - PLUG_TOP) * st["plug"]
    PLUG.data.keyframe_insert("bevel_factor_start", frame=k)
    SWEAT_COL.data.bevel_factor_end = PLUG.data.bevel_factor_start if st["plug"] > 0.02 else 1.0
    SWEAT_COL.data.keyframe_insert("bevel_factor_end", frame=k)
    keyed(M_BACT, "Base Color", k, (0.55 - 0.15 * st["bact_kill"], 0.66 - 0.3 * st["bact_kill"], 0.22 + 0.15 * st["bact_kill"], 1))
    keyed(M_BACT, "Emission Strength", k, 0.25 * (1 - st["bact_kill"]))
    keyed(M_PLUG, "Emission Strength", k, 0.5 * st["plug"])
    keyed(bpy.data.materials["salty"], "Alpha", k, 0.55 * st["salt_cloud"])
    night = ramp(t, T_NIGHT, T_NIGHT + 0.8) * (1 - ramp(t, shot("calm")["start"], shot("calm")["start"] + 0.8))
    KEY.data.energy = spec.get("key", 1500) * (1 - 0.6 * night)
    KEY.data.color = (1 - 0.35 * night, 1 - 0.2 * night, 1.0)
    KEY.data.keyframe_insert("energy", frame=k)
    KEY.data.keyframe_insert("color", frame=k)

for o in bpy.data.objects:
    ad = o.animation_data
    if ad and ad.action:
        for fc in ad.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
scene.frame_start, scene.frame_end = 0, TOTAL - 1
scene.render.use_motion_blur = spec.get("blur", False)  # slow motion: no blur needed, and it renders faster
scene.render.motion_blur_shutter = 0.5

# where each label's pin is on screen, per frame
PINS = {
    "apocrine": APO_C + Vector((0.0, -0.06, 0.05)),
    "follicle": H_TOP.lerp(H_BULB, 0.55) + Vector((0, -0.05, 0)),
    "bacteria": Vector((BACT_AT.x + 0.08, BACT_AT.y - 0.06, 0.01)),
    "eccrine": GLAND_E[len(GLAND_E) // 3] + Vector((0, -0.04, 0)),
    "salts": Vector((PORE_E.x, PORE_E.y + 0.04, 0.06)),
    "plug": on_path(DUCT_E[WIN:], 0.8) + Vector((0, -0.03, 0)),
    "pore": Vector((PORE_E.x, YF, 0.0)),
    "duct": on_path(DUCT_E, 0.35) + Vector((0, -0.03, 0)),
}
W_, H_ = scene.render.resolution_x, scene.render.resolution_y
out = Path(spec["out"])
out.mkdir(parents=True, exist_ok=True)
frames = spec.get("only") or list(range(TOTAL))
for k in range(TOTAL):
    scene.frame_set(k)
    anchors[k] = {n: [world_to_camera_view(scene, cam, p).x * W_, (1 - world_to_camera_view(scene, cam, p).y) * H_]
                  for n, p in PINS.items()}
(out / "anchors.json").write_text(json.dumps(anchors))
if spec.get("only"):
    for k in frames:
        scene.frame_set(k)
        scene.render.filepath = str(out / f"{k:05d}.png")
        bpy.ops.render.render(write_still=True)
else:
    scene.render.filepath = str(out / "#####")
    scene.render.use_overwrite = False  # a stopped render picks up where it left off (kept frames dir)
    bpy.ops.render.render(animation=True)
