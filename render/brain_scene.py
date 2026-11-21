"""The 3D layer of the brain deep dive (dd-brain-anger): a real-looking brain on near-black, with a soft glass window
on the near side through which the deep structures show, glowing when active; signals and hormones as streams of
light. Runs inside Blender:

    blender -b --factory-startup -t 4 --python render/brain_scene.py -- '<json spec>'

The model is assets/models/brain.blend (scripts/extract_organ.py, Z-Anatomy). Its parts are sorted into roles
(spec "roles": {role: name pattern}). The cortex gyri, cerebellum and brainstem pieces are joined per hemisphere /
cerebellum / stem and voxel-remeshed into clean, watertight, smoothed surfaces ("merged"), shaded as living tissue
(pinkish grey, subsurface scattering, a wet coat). Inside a soft tunnel from the camera to the active structure
("window") that tissue turns to clear glass with a cool rim. Deep structures (amygdala, hippocampus, hypothalamus,
pituitary, thalamus) are solid glossy objects that glow in their colour when "lit".

Each shot: {"name", "cam": {"focus": role | [x, y, z], "dir": [x, y, z], "dist", "lens", "fstop", "aim", "shift"},
            "window": {"at": role, "radius", "soft"} (fractions of the model's size),
            "lit": {role: [r, g, b, strength]}, "flows": [{"from", "to", "color", "head", "n", "arc", "spread"}],
            "pins": [roles], "dust": n, "seed"}
spec: {"root", "out", "roles", "width", "height", "samples", "engine": "eevee" | "cycles", "voxel", "raw", "shots"}
Writes <out>/<name>.png and .json (pins in pixels).
"""

import json
import math
import random
import re
import sys
import time
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

spec = json.loads(sys.argv[sys.argv.index("--") + 1])
ROOT, OUT = Path(spec["root"]), Path(spec["out"])
W, H = spec.get("width", 1080), spec.get("height", 1920)
scene = bpy.context.scene
ROLES = {}  # role -> part names, matched from spec["roles"] (role -> name pattern) once the model loads

# --- materials --------------------------------------------------------------------------------------------------
WINDOW = {"eye": Vector(), "target": Vector(), "radius": 0.02, "soft": 0.008}


def _vec(nt, op, a, b=None):
    n = nt.nodes.new("ShaderNodeVectorMath")
    n.operation = op
    for k, x in enumerate((a, b)):
        if x is None:
            continue
        if isinstance(x, (tuple, list, Vector)):
            n.inputs[k].default_value = tuple(x)
        else:
            nt.links.new(x, n.inputs[k])
    return n


def _math(nt, op, a, b=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for k, x in enumerate((a, b)):
        if x is None:
            continue
        if isinstance(x, (int, float)):
            n.inputs[k].default_value = x
        else:
            nt.links.new(x, n.inputs[k])
    return n.outputs[0]


def tissue(name, rgb=(0.46, 0.29, 0.29), window=True):
    """Living brain tissue: pinkish grey, light passing a little way under the surface, a wet sheen. With window,
    surfaces in the tunnel from the camera to the active structure fade to clear glass with a cool rim."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = 0.42
    b.inputs["Subsurface Weight"].default_value = 0.35
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.25)
    b.inputs["Subsurface Scale"].default_value = 0.0025
    b.inputs["Coat Weight"].default_value = 0.35
    b.inputs["Coat Roughness"].default_value = 0.18
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")  # darker down in the sulci, so the folds read
    ao.inputs["Distance"].default_value = 0.004
    ao.inputs["Color"].default_value = (*rgb, 1)
    dark = nt.nodes.new("ShaderNodeMix")
    dark.data_type = "RGBA"
    dark.inputs["A"].default_value = (rgb[0] * 0.28, rgb[1] * 0.2, rgb[2] * 0.22, 1)
    dark.inputs["B"].default_value = (*rgb, 1)
    nt.links.new(_math(nt, "POWER", ao.outputs["AO"], 2.5), dark.inputs["Factor"])
    nt.links.new(dark.outputs["Result"], b.inputs["Base Color"])
    if not window:
        return m
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    eye, tgt = WINDOW["eye"], WINDOW["target"]
    u = (tgt - eye).normalized()
    v = _vec(nt, "SUBTRACT", geo.outputs["Position"], eye)
    t = _vec(nt, "DOT_PRODUCT", v.outputs[0], u)
    along = _vec(nt, "SCALE", u)
    nt.links.new(t.outputs["Value"], along.inputs["Scale"])
    perp = _vec(nt, "SUBTRACT", v.outputs[0], along.outputs[0])
    dist = _vec(nt, "LENGTH", perp.outputs[0])
    outside = _math(nt, "DIVIDE", _math(nt, "SUBTRACT", dist.outputs["Value"], WINDOW["radius"]), WINDOW["soft"])
    behind = _math(nt, "DIVIDE", _math(nt, "SUBTRACT", t.outputs["Value"], (tgt - eye).length + 0.006), 0.004)
    solid = _math(nt, "MAXIMUM", _math(nt, "MAXIMUM", outside, 0.0, clamp=True),
                  _math(nt, "MAXIMUM", behind, 0.0, clamp=True))
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.3
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.55, 0.75, 1.0, 1)
    nt.links.new(_math(nt, "MULTIPLY", _math(nt, "POWER", lw.outputs["Facing"], 3.0), 0.6), em.inputs["Strength"])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    glass = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(tr.outputs[0], glass.inputs[0])
    nt.links.new(em.outputs[0], glass.inputs[1])
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(solid, mix.inputs[0])
    nt.links.new(glass.outputs[0], mix.inputs[1])
    nt.links.new(b.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return m


def glossy(name, rgb, glow=0.0):
    """A deep structure: solid, glossy, clearly shaped; it glows in its own colour when active."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = 0.22
    b.inputs["Coat Weight"].default_value = 0.8
    b.inputs["Coat Roughness"].default_value = 0.05
    b.inputs["Subsurface Weight"].default_value = 0.25
    b.inputs["Subsurface Radius"].default_value = tuple(0.3 + 0.7 * c for c in rgb)
    b.inputs["Subsurface Scale"].default_value = 0.002
    if glow:
        b.inputs["Emission Color"].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = glow
    nt = m.node_tree
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.25
    rim = nt.nodes.new("ShaderNodeEmission")
    rim.inputs["Color"].default_value = (*(min(1.0, c * 1.3 + 0.1) for c in rgb), 1)
    nt.links.new(_math(nt, "MULTIPLY", _math(nt, "POWER", lw.outputs["Facing"], 2.5), 0.7), rim.inputs["Strength"])
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(b.outputs[0], add.inputs[0])
    nt.links.new(rim.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return m


def emissive(name, rgb, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*rgb, 1)
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return m


DEEP = {  # resting colours: clear and distinct, not neon
    "amygdala": (0.7, 0.1, 0.08), "hippocampus": (0.85, 0.6, 0.18), "hypothalamus": (0.95, 0.36, 0.04),
    "pituitary": (0.5, 0.28, 0.85), "thalamus": (0.42, 0.45, 0.55),
}
HIDE = ("callosum", "basal", "ventricle", "thalamus")  # clutter inside the window


# --- model ------------------------------------------------------------------------------------------------------
def load():
    with bpy.data.libraries.load(str(ROOT / "assets" / "models" / "brain.blend")) as (src, dst):
        dst.objects = list(src.objects)
    objs = {}
    for o in dst.objects:
        if o is not None and o.type == "MESH" and not o.name.startswith("Cross Section"):  # atlas cutting planes
            scene.collection.objects.link(o)
            o.hide_render = o.hide_viewport = False  # the atlas saves most parts hidden
            o.data.materials.clear()
            trim(o)
            for p in o.data.polygons:
                p.use_smooth = True
            objs[o.name] = o
    ROLES.clear()
    for r, pat in spec["roles"].items():
        found = sorted(n for n in objs if re.match(pat, n))
        if found:
            ROLES[r] = found
    return objs


def trim(o, limit=0.06):
    """Drop stray vertices: the atlas Hypothalamus carries a few half a metre away from the rest."""
    if max(o.dimensions) < 0.2:
        return
    med = Vector([sorted(v.co[i] for v in o.data.vertices)[len(o.data.vertices) // 2] for i in range(3)])
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if (v.co - med).length > limit], context="VERTS")
    bm.to_mesh(o.data)
    bm.free()


def centre(names, objs):
    pts = [objs[n].matrix_world @ v.co for n in names if n in objs for v in objs[n].data.vertices]
    return sum(pts, Vector()) / len(pts)


def box(names, objs):
    pts = [objs[n].matrix_world @ v.co for n in names if n in objs for v in objs[n].data.vertices]
    return (Vector([min(p[i] for p in pts) for i in range(3)]), Vector([max(p[i] for p in pts) for i in range(3)]))


def link(o):
    scene.collection.objects.link(o)
    return o


def merged(name, parts, voxel):
    """Many atlas pieces as one clean, watertight surface: joined, voxel-remeshed, smoothed."""
    verts, faces = [], []
    for o in parts:
        base = len(verts)
        verts += [tuple(o.matrix_world @ v.co) for v in o.data.vertices]
        faces += [tuple(base + k for k in p.vertices) for p in o.data.polygons]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    o = link(bpy.data.objects.new(name, me))
    rm = o.modifiers.new("remesh", "REMESH")
    rm.mode, rm.voxel_size, rm.adaptivity = "VOXEL", voxel, 0.0
    sm = o.modifiers.new("smooth", "LAPLACIANSMOOTH")
    sm.lambda_factor, sm.iterations = 0.6, 4
    sm.use_volume_preserve = True
    dg = bpy.context.evaluated_depsgraph_get()
    clean = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
    o.modifiers.clear()
    o.data = clean
    for p in clean.polygons:
        p.use_smooth = True
    print("MERGED", name, len(parts), "parts ->", len(clean.polygons), "faces")
    return o


def bezier(a, b, arc, t):
    mid = (a + b) / 2 + Vector(arc)
    return a * (1 - t) ** 2 + mid * 2 * t * (1 - t) + b * t * t


def flow(name, a, b, f, rng, unit):
    """A stream of glowing particles from a to b: a comet (nerve signal) or a loose cloud (hormone)."""
    head, n, spread = f.get("head", 0.8), f.get("n", 60), f.get("spread", 0.0)
    trail = f.get("trail", 0.55)
    arc = Vector(f.get("arc", [0, 0, 0])) * unit
    bm = bmesh.new()
    for i in range(n):
        u = i / max(1, n - 1)  # 0 tail .. 1 head
        t = head - trail * (1 - u) ** 1.3
        if t < 0:
            continue
        p = bezier(a, b, arc, t)
        jitter = Vector([rng.gauss(0, 1) for _ in range(3)]) * unit * (0.004 + spread * 0.03) * (0.4 + u)
        r = unit * f.get("size", 0.0022) * (0.35 + 0.9 * u ** 1.5) * (1 + spread * rng.random())
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r, matrix=Matrix.Translation(p + jitter))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(emissive(name, f.get("color", (1, 0.2, 0.1)), f.get("strength", 30)))
    o = link(bpy.data.objects.new(name, me))
    if f.get("thread", True):  # the faint path it travels: a nerve tract or the pituitary stalk
        bm = bmesh.new()
        prev = None
        for i in range(41):
            p = bezier(a, b, arc, i / 40)
            if prev is not None:
                d = p - prev
                m = Matrix.Translation((p + prev) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
                bmesh.ops.create_cone(bm, cap_ends=False, segments=8, radius1=unit * 0.0012, radius2=unit * 0.0012,
                                      depth=d.length, matrix=m)
            prev = p
        tme = bpy.data.meshes.new(name + " path")
        bm.to_mesh(tme)
        bm.free()
        tme.materials.append(emissive(name + " path", f.get("color", (1, 0.2, 0.1)), 1.5))
        link(bpy.data.objects.new(name + " path", tme))
    return o


def dust(n, rng, centre_, size):
    """Specks floating between camera and brain; depth of field turns them into soft bokeh."""
    bm = bmesh.new()
    for _ in range(n):
        p = centre_ + Vector([rng.uniform(-1, 1) * size[i] for i in range(3)])
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=rng.uniform(0.0003, 0.0009), matrix=Matrix.Translation(p))
    me = bpy.data.meshes.new("dust")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(emissive("dust", (0.75, 0.85, 1.0), 2.5))
    link(bpy.data.objects.new("dust", me))


# --- stage ------------------------------------------------------------------------------------------------------
def light(name, loc, target, power, size, color):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.color, ld.size = power, color, size
    o = link(bpy.data.objects.new(name, ld))
    o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def setup(samples):
    scene.render.resolution_x, scene.render.resolution_y = W, H
    if spec.get("engine") == "cycles":  # the Mac's GPU through Metal, denoised
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for dev in prefs.devices:
            dev.use = True
        scene.render.engine = "CYCLES"
        scene.cycles.device = "GPU"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        scene.cycles.max_bounces = 8
        scene.cycles.transparent_max_bounces = 16
    else:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
        scene.eevee.taa_render_samples = samples
        scene.eevee.use_raytracing = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
    scene.view_settings.exposure = spec.get("exposure", -0.35)
    w = bpy.data.worlds.new("world")
    scene.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.006, 0.008, 0.014, 1)
    scene.use_nodes = True
    ct = scene.node_tree
    for n in list(ct.nodes):
        ct.nodes.remove(n)
    rl = ct.nodes.new("CompositorNodeRLayers")
    comp = ct.nodes.new("CompositorNodeComposite")
    if spec.get("raw"):
        ct.links.new(rl.outputs["Image"], comp.inputs["Image"])
        return
    glare = ct.nodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"  # a gentle glow on the lit parts only
    glare.quality = "HIGH"
    glare.threshold = 1.0
    glare.size = 7
    glare.mix = -0.75
    ct.links.new(rl.outputs["Image"], glare.inputs["Image"])
    ct.links.new(glare.outputs["Image"], comp.inputs["Image"])


def px(cam, co):
    p = world_to_camera_view(scene, cam, Vector(co))
    return [round(p.x * W, 1), round((1 - p.y) * H, 1)]


def render_shot(sh, objs):
    rng = random.Random(sh.get("seed", 3))
    role_of = {n: r for r, names in ROLES.items() for n in names}
    lo, hi = box(list(objs), objs)
    unit = (hi - lo).length  # about 0.28 m: everything below scales with the model
    mid = (lo + hi) / 2
    lit = sh.get("lit", {})
    c = sh["cam"]
    where = lambda x: Vector(x) if isinstance(x, list) else centre(ROLES[x], objs)  # noqa: E731
    focus = where(c["focus"])
    d = Vector(c.get("dir", [-0.55, -1.0, 0.18])).normalized()
    eye = focus + d * unit * c.get("dist", 2.2)
    look_at = (mid if c.get("aim") == "all" else focus) + Vector(c.get("shift", [0, 0, 0])) * unit
    near = lambda x: Vector(x) if isinstance(x, list) else centre(  # noqa: E731  a paired structure: the nearer one
        [min(ROLES[x], key=lambda n: (centre([n], objs) - eye).length)], objs)
    win = sh.get("window", {})
    WINDOW.update(eye=eye, target=near(win.get("at", c["focus"])), radius=win.get("radius", 0.09) * unit,
                  soft=win.get("soft", 0.04) * unit)
    # the shell: hemispheres, cerebellum and brainstem as clean remeshed surfaces
    groups = {}
    for n, o in objs.items():
        r = role_of.get(n)
        if r in DEEP or r in HIDE or r in lit:
            continue
        if re.search(r"(Midbrain|Pons|Medulla|colliculus|Optic chiasm)", n):
            g = "stem"
        elif re.search(r"(lobule|vermis|Culmen|Declive|Flocculus|Tonsil)", n) and "parietal" not in n \
                and "Paracentral" not in n:
            g = "cerebellum"
        else:
            g = "hemisphere r" if n.endswith(".r") else "hemisphere l"
        groups.setdefault(g, []).append(o)
    shell_mat = tissue("tissue")
    for g, parts in groups.items():
        m = merged(g, parts, spec.get("voxel", 0.0007))
        m.data.materials.append(shell_mat)
        for o in parts:
            o.hide_render = True
    for n, o in objs.items():
        r = role_of.get(n)
        if r in HIDE:
            o.hide_render = True
        elif r in DEEP or r in lit:
            sub = o.modifiers.new("smooth", "SUBSURF")
            sub.levels = sub.render_levels = 2
            if r in lit:
                o.data.materials.append(glossy("lit " + r, lit[r][:3], lit[r][3]))
            else:
                o.data.materials.append(glossy("rest " + r, DEEP[r], sh.get("idle", 0.0)))
    for r, v in lit.items():  # a light inside each lit structure: its colour spills onto the tissue around it
        ld = bpy.data.lights.new("glow " + r, "POINT")
        ld.energy, ld.color, ld.shadow_soft_size = v[3] * 0.05, v[:3], 0.004
        link(bpy.data.objects.new("glow " + r, ld)).location = near(r)
    for i, f in enumerate(sh.get("flows", [])):
        flow(f"flow {i}", near(f["from"]), near(f["to"]), f, rng, unit)
    cam = link(bpy.data.objects.new("cam", bpy.data.cameras.new("cam")))
    scene.camera = cam
    cam.data.lens = c.get("lens", 50)
    cam.data.sensor_fit = "VERTICAL"
    cam.data.sensor_height = 24
    cam.data.clip_start = 0.001
    cam.location = eye
    cam.rotation_euler = (look_at - eye).to_track_quat("-Z", "Y").to_euler()
    cam.data.dof.use_dof = not spec.get("raw")
    cam.data.dof.focus_distance = (focus - eye).length
    cam.data.dof.aperture_fstop = c.get("fstop", 4.0)
    cam.data.dof.aperture_blades = 7
    # cinematic lighting: a warm key high on the camera side, cool rims behind, a soft warm bounce from below
    side = Vector((d.x, d.y, 0)).normalized()
    across = Vector((-side.y, side.x, 0))
    light("key", mid + (side * 1.1 + across * 0.7 + Vector((0, 0, 1.0))) * unit, mid, 30, unit * 0.6,
          (1.0, 0.9, 0.82))
    light("rim", mid + (-side * 1.2 - across * 0.6 + Vector((0, 0, 0.5))) * unit, mid, 45, unit * 0.6,
          (0.55, 0.72, 1.0))
    light("rim2", mid + (-side * 1.0 + across * 0.9 + Vector((0, 0, 0.2))) * unit, mid, 20, unit * 0.6,
          (0.6, 0.75, 1.0))
    light("bounce", mid + (side * 0.8 - Vector((0, 0, 1.1))) * unit, mid, 3, unit * 1.5, (1.0, 0.7, 0.6))
    if sh.get("dust", 120):
        dust(sh.get("dust", 120), rng, (eye + focus) / 2, (unit * 0.9, unit * 0.9, unit * 0.9))
    scene.render.filepath = str(OUT / f"{sh['name']}.png")
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    print("TIME", sh["name"], scene.render.engine, round(time.time() - t0, 1), "s")
    pins = {}
    for r in sh.get("pins", []):
        part = min(ROLES[r], key=lambda n: (centre([n], objs) - eye).length)  # a paired structure: the nearer one
        ctr = centre([part], objs)
        towards = (eye - ctr).normalized()
        best = max((objs[part].matrix_world @ v.co for v in objs[part].data.vertices),
                   key=lambda p: (p - ctr).dot(towards) - 2 * ((p - ctr) - towards * (p - ctr).dot(towards)).length)
        pins[r] = px(cam, ctr.lerp(best, 0.6))
    (OUT / f"{sh['name']}.json").write_text(json.dumps({"pins": pins}))
    print("SHOT", sh["name"], pins)


# --- animation (the deep dive): one session, the brain and adrenal models loaded once --------------------------
GLOW = {"amygdala": (1.0, 0.07, 0.04), "hippocampus": (1.0, 0.68, 0.12), "hypothalamus": (1.0, 0.42, 0.08),
        "pituitary": (0.55, 0.25, 1.0), "thalamus": (0.6, 0.65, 0.8)}


def ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def keyed(v, u):
    """A number; [a, b] (eased from a to b over the shot); or keys [[u, value], ...] eased between."""
    if isinstance(v, (int, float)):
        return v
    if v and isinstance(v[0], (int, float)):
        return v[0] + (v[1] - v[0]) * ease(u)
    if u <= v[0][0]:
        return v[0][1]
    for (u0, a), (u1, b) in zip(v, v[1:]):
        if u <= u1:
            return a + (b - a) * ease((u - u0) / max(1e-6, u1 - u0))
    return v[-1][1]


class Live:
    """The tissue material's window and glow region, and the deep structures' materials, updated every frame."""

    def __init__(self):
        self.tissue = bpy.data.materials.new("live tissue")
        self.tissue.use_nodes = True
        nt = self.tissue.node_tree
        b = nt.nodes["Principled BSDF"]
        rgb = (0.46, 0.29, 0.29)
        for k, v in (("Roughness", 0.42), ("Subsurface Weight", 0.35), ("Subsurface Scale", 0.0025),
                     ("Coat Weight", 0.35), ("Coat Roughness", 0.18)):
            b.inputs[k].default_value = v
        b.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.25)
        ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
        ao.inputs["Distance"].default_value = 0.004
        dark = nt.nodes.new("ShaderNodeMix")
        dark.data_type = "RGBA"
        dark.inputs["A"].default_value = (rgb[0] * 0.28, rgb[1] * 0.2, rgb[2] * 0.22, 1)
        dark.inputs["B"].default_value = (*rgb, 1)
        nt.links.new(_math(nt, "POWER", ao.outputs["AO"], 2.5), dark.inputs["Factor"])
        nt.links.new(dark.outputs["Result"], b.inputs["Base Color"])
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        self.n_eye = _vec(nt, "SUBTRACT", geo.outputs["Position"], (0, 0, 0))
        self.n_dot = _vec(nt, "DOT_PRODUCT", self.n_eye.outputs[0], (0, 0, 1))
        self.n_along = _vec(nt, "SCALE", (0, 0, 1))
        nt.links.new(self.n_dot.outputs["Value"], self.n_along.inputs["Scale"])
        perp = _vec(nt, "SUBTRACT", self.n_eye.outputs[0], self.n_along.outputs[0])
        dist = _vec(nt, "LENGTH", perp.outputs[0])
        self.n_r = nt.nodes.new("ShaderNodeMath")
        self.n_r.operation = "SUBTRACT"
        nt.links.new(dist.outputs["Value"], self.n_r.inputs[0])
        self.n_soft = nt.nodes.new("ShaderNodeMath")
        self.n_soft.operation = "DIVIDE"
        nt.links.new(self.n_r.outputs[0], self.n_soft.inputs[0])
        self.n_len = nt.nodes.new("ShaderNodeMath")
        self.n_len.operation = "SUBTRACT"
        nt.links.new(self.n_dot.outputs["Value"], self.n_len.inputs[0])
        behind = _math(nt, "DIVIDE", self.n_len.outputs[0], 0.004)
        solid = _math(nt, "MAXIMUM", _math(nt, "MAXIMUM", self.n_soft.outputs[0], 0.0, clamp=True),
                      _math(nt, "MAXIMUM", behind, 0.0, clamp=True))
        lw = nt.nodes.new("ShaderNodeLayerWeight")
        lw.inputs["Blend"].default_value = 0.3
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (0.55, 0.75, 1.0, 1)
        nt.links.new(_math(nt, "MULTIPLY", _math(nt, "POWER", lw.outputs["Facing"], 4.0), 0.25), em.inputs["Strength"])
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        glass = nt.nodes.new("ShaderNodeAddShader")
        nt.links.new(tr.outputs[0], glass.inputs[0])
        nt.links.new(em.outputs[0], glass.inputs[1])
        # the glow region (the prefrontal cortex lighting up): emission falling off from a point
        rc = _vec(nt, "DISTANCE", geo.outputs["Position"], (0, 0, 0))
        self.n_rc = rc
        self.n_rr = nt.nodes.new("ShaderNodeMath")
        self.n_rr.operation = "DIVIDE"
        nt.links.new(rc.outputs["Value"], self.n_rr.inputs[0])
        fall = _math(nt, "POWER", _math(nt, "SUBTRACT", 1.0, self.n_rr.outputs[0], clamp=True), 2.0)
        self.n_rs = nt.nodes.new("ShaderNodeMath")
        self.n_rs.operation = "MULTIPLY"
        nt.links.new(fall, self.n_rs.inputs[0])
        self.n_rem = nt.nodes.new("ShaderNodeEmission")
        nt.links.new(self.n_rs.outputs[0], self.n_rem.inputs["Strength"])
        lit = nt.nodes.new("ShaderNodeAddShader")
        nt.links.new(b.outputs[0], lit.inputs[0])
        nt.links.new(self.n_rem.outputs[0], lit.inputs[1])
        mix = nt.nodes.new("ShaderNodeMixShader")
        sm = _math(nt, "MULTIPLY", solid, 1.0)  # smoothstep the cut, so its edge is clean, not a dithered band
        sm = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", sm, sm), _math(nt, "SUBTRACT", 3.0, _math(nt, "MULTIPLY", sm, 2.0)))
        nt.links.new(sm, mix.inputs[0])
        nt.links.new(glass.outputs[0], mix.inputs[1])
        nt.links.new(lit.outputs[0], mix.inputs[2])
        # a thin cool line where the tissue meets the window, like the rim of a cutaway
        edge = _math(nt, "SUBTRACT", 1.0, _math(nt, "ABSOLUTE", _math(nt, "SUBTRACT", _math(nt, "MULTIPLY", sm, 2.0), 1.0)))
        cut = nt.nodes.new("ShaderNodeEmission")
        cut.inputs["Color"].default_value = (0.6, 0.78, 1.0, 1)
        nt.links.new(_math(nt, "MULTIPLY", _math(nt, "POWER", edge, 3.0), 1.4), cut.inputs["Strength"])
        final = nt.nodes.new("ShaderNodeAddShader")
        nt.links.new(mix.outputs[0], final.inputs[0])
        nt.links.new(cut.outputs[0], final.inputs[1])
        nt.links.new(final.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
        self.region(Vector(), 1.0, (0, 0, 0), 0.0)
        self.deep = {}

    def window(self, eye, target, radius, soft):
        u = (target - eye).normalized()
        self.n_eye.inputs[1].default_value = tuple(eye)
        self.n_dot.inputs[1].default_value = tuple(u)
        self.n_along.inputs[0].default_value = tuple(u)
        self.n_r.inputs[1].default_value = radius
        self.n_soft.inputs[1].default_value = soft
        self.n_len.inputs[1].default_value = (target - eye).length + 0.006

    def region(self, at, radius, colour, strength):
        self.n_rc.inputs[1].default_value = tuple(at)
        self.n_rr.inputs[1].default_value = radius
        self.n_rem.inputs["Color"].default_value = (*colour, 1)
        self.n_rs.inputs[1].default_value = strength

    def deep_mat(self, role):
        if role not in self.deep:
            self.deep[role] = glossy("deep " + role, DEEP.get(role, GLOW[role]))
        return self.deep[role]

    def glow(self, role, strength):
        b = self.deep_mat(role).node_tree.nodes["Principled BSDF"]
        b.inputs["Emission Color"].default_value = (*GLOW[role], 1)
        b.inputs["Emission Strength"].default_value = strength


class Stage:
    """Loaded once: the brain (remeshed shell + deep parts) and the adrenal glands on the kidneys."""

    def __init__(self):
        self.objs = load()
        self.live = Live()
        role_of = {n: r for r, names in ROLES.items() for n in names}
        lo, hi = box(list(self.objs), self.objs)
        self.unit, self.mid = (hi - lo).length, (lo + hi) / 2
        groups = {}
        self.deep = {}
        for n, o in self.objs.items():
            r = role_of.get(n)
            if r in HIDE:
                o.hide_render = True
                continue
            if r in DEEP or r in GLOW:
                if r == "hypothalamus":  # the atlas mesh is lumpy: relax it first, so its shape reads clearly
                    lap = o.modifiers.new("relax", "LAPLACIANSMOOTH")
                    lap.lambda_factor, lap.iterations, lap.use_volume_preserve = 0.8, 12, True
                sub = o.modifiers.new("smooth", "SUBSURF")
                sub.levels = sub.render_levels = 2
                o.data.materials.append(self.live.deep_mat(r))
                self.deep.setdefault(r, []).append(o)
                continue
            if re.search(r"(Midbrain|Pons|Medulla|colliculus|Optic chiasm)", n):
                g = "stem"
            elif re.search(r"(lobule|vermis|Culmen|Declive|Flocculus|Tonsil)", n) and "parietal" not in n \
                    and "Paracentral" not in n:
                g = "cerebellum"
            else:
                g = "hemisphere r" if n.endswith(".r") else "hemisphere l"
            groups.setdefault(g, []).append(o)
        self.shell = []
        for g, parts in groups.items():
            m = merged(g, parts, spec.get("voxel", 0.0007))
            m.data.materials.append(self.live.tissue)
            self.shell.append(m)
            for o in parts:
                o.hide_render = True
        self.brain = self.shell + [o for v in self.deep.values() for o in v]
        self.rest = {o: o.matrix_world.copy() for o in self.brain}
        self.centres = {r: [centre([o.name], self.objs) for o in v] for r, v in self.deep.items()}
        self.pfc = centre(ROLES["pfc"], self.objs) if "pfc" in ROLES else self.mid
        # adrenal glands on the kidneys
        with bpy.data.libraries.load(str(ROOT / "assets" / "models" / "adrenal.blend")) as (src, dst):
            dst.objects = [n for n in src.objects if not n.startswith("Cross Section")]
        self.adrenal = []
        kid = principled_mat("kidney", (0.085, 0.016, 0.011), 0.42, 0.15, coat=0.3)
        kn = kid.node_tree
        noise = kn.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 180.0
        bump = kn.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.12
        kn.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        kn.links.new(bump.outputs["Normal"], kn.nodes["Principled BSDF"].inputs["Normal"])
        self.kidney_mat = kid
        self.gland_mat = principled_mat("gland", (0.9, 0.62, 0.2), 0.3, 0.3, alpha=0.42)
        self.med_mat = principled_mat("medulla", (0.45, 0.14, 0.08), 0.3, 0.2)
        glands = []
        for o in dst.objects:
            if o is None or o.type != "MESH":
                continue
            scene.collection.objects.link(o)
            o.hide_render = o.hide_viewport = False
            o.data.materials.clear()
            sub = o.modifiers.new("smooth", "SUBSURF")
            sub.levels = sub.render_levels = 2
            for p in o.data.polygons:
                p.use_smooth = True
            if o.name.startswith("Kidney"):  # never shown (see scripts/extract_organ.py)
                o.hide_render = True
                continue
            o.data.materials.append(self.gland_mat)
            glands.append(o)
            self.adrenal.append(o)
        self.glands = {}
        for g in glands:  # each gland gets its medulla: a smaller copy inside, which glows when it releases
            c = sum((g.matrix_world @ v.co for v in g.data.vertices), Vector()) / len(g.data.vertices)
            med = g.copy()
            med.data = g.data.copy()
            med.data.materials.clear()
            med.data.materials.append(self.med_mat)
            scene.collection.objects.link(med)
            med.matrix_world = Matrix.Translation(c) @ Matrix.Scale(0.5, 4) @ Matrix.Translation(-c) @ g.matrix_world
            self.adrenal.append(med)
            self.glands[g.name] = (g, med, c)
            k = bean(g.name + " kidney", c, g, kid)
            self.adrenal.append(k)
            self.adrenal += [bpy.data.objects[n] for n in k.get("tubes", "").split(";") if n]

    def show(self, which):
        for o in self.brain:
            o.hide_render = which != "brain"
        for o in self.adrenal:
            o.hide_render = which != "adrenal"

    def near(self, role, eye):
        if role == "pfc":
            return self.pfc
        if isinstance(role, list):
            return Vector(role)
        return min(self.centres[role], key=lambda c: (c - eye).length)


def bean(name, gland_c, gland, mat):
    """A kidney under its gland, built here (the atlas kidney is adapted from a CC BY-NC model): a bean about 11 cm
    tall with a concave hilum facing the midline, a faint lobe texture, and the renal artery (red), the renal vein
    (blue) and the ureter (pale) leaving the hilum. Its top sits just under the gland, which caps it."""
    lo = min((gland.matrix_world @ v.co).z for v in gland.data.vertices)
    side = 1 if gland_c.x > 0 else -1  # +x is the body's left
    H, Wd, D = 0.055, 0.03, 0.02  # half height, half width, half depth (metres)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=96, v_segments=64, radius=1.0)
    for v in bm.verts:
        x, y, z = v.co
        inner = max(0.0, -x * side)  # the medial (midline) side
        dent = 0.55 * math.exp(-((z / 0.38) ** 2)) * inner ** 1.5  # the hilum: a deep notch on the medial side
        bulge = 1 + 0.08 * (1 - z * z)
        v.co = Vector((x * Wd * bulge * (1 - dent), y * D, z * H * (1 + 0.06 * x * side)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    top = lo + 0.006  # the gland's base rests on the kidney's upper pole
    cx = gland_c.x + side * 0.004
    o = link(bpy.data.objects.new(name, me))
    o.matrix_world = Matrix.Translation((cx, gland_c.y + 0.004, top - H)) @ Matrix.Rotation(math.radians(-10 * side), 4, "Y")
    hilum = o.matrix_world @ Vector((-side * Wd * 0.5, 0.0, 0.0))
    out = Vector((-side, 0.0, 0.0))
    tubes = [("artery", (0.75, 0.08, 0.06), 0.0032, Vector((0, -0.006, 0.006)), out * 0.06 + Vector((0, -0.01, 0.025))),
             ("vein", (0.1, 0.2, 0.6), 0.004, Vector((0, 0.002, 0.0)), out * 0.06 + Vector((0, 0.004, 0.012))),
             ("ureter", (0.88, 0.8, 0.62), 0.0024, Vector((0, 0.004, -0.009)), out * 0.012 + Vector((0, 0.006, -0.11)))]
    for tname, rgb, r, start_off, end_off in tubes:
        cu = bpy.data.curves.new(name + " " + tname, "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth, cu.bevel_resolution = r, 6
        sp = cu.splines.new("BEZIER")
        sp.bezier_points.add(1)
        a = hilum + start_off - out * 0.006
        b = hilum + start_off + end_off
        for bp, co, hd in ((sp.bezier_points[0], a, out * 0.02), (sp.bezier_points[1], b, (b - a).normalized() * 0.02)):
            bp.co = co
            bp.handle_left, bp.handle_right = co - hd, co + hd
        tm = principled_mat(name + " " + tname, rgb, 0.3, 0.4, coat=0.6)
        cu.materials.append(tm)
        t = link(bpy.data.objects.new(name + " " + tname, cu))
        o["tubes"] = o.get("tubes", "") + t.name + ";"
    return o


def principled_mat(name, rgb, rough, sss, alpha=1.0, coat=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Subsurface Weight"].default_value = sss
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.4, 0.25)
    b.inputs["Subsurface Scale"].default_value = 0.002
    if alpha < 1:
        b.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "BLENDED"
    return m


TEMP = []  # names of this shot's own objects (camera, lights, streams, dust)


def temp(o):
    TEMP.append(o.name)
    return link(o)


def drop(name):
    """Remove an object with its mesh and materials (streams are rebuilt every frame: nothing may pile up)."""
    o = bpy.data.objects.get(name)
    if o is None:
        return
    data = o.data
    mats = list(data.materials) if hasattr(data, "materials") else []
    bpy.data.objects.remove(o)
    if isinstance(data, bpy.types.Mesh) and data.users == 0:
        bpy.data.meshes.remove(data)
    for m in mats:
        if m and m.users == 0:
            bpy.data.materials.remove(m)


def lamp(name, kind, loc, target, power, size, colour):
    ld = bpy.data.lights.new(name, kind)
    ld.energy, ld.color = power, colour
    if kind == "AREA":
        ld.size = size
    else:
        ld.shadow_soft_size = size
    o = temp(bpy.data.objects.new(name, ld))
    o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return o


def stream(name, a, b, f, u, seed, unit, mats):
    """A flow at shot time u (head, strength and spread may be keyed), rebuilt each frame with the same particles."""
    g = dict(f)
    g["head"] = keyed(f.get("head", 0.8), u)
    g["spread"] = keyed(f.get("spread", 0.0), u)
    g["strength"] = keyed(f.get("strength", 30), u)
    drop(name)
    o = flow(name, a, b, {**g, "thread": False}, random.Random(seed), unit)
    em = o.data.materials[0].node_tree.nodes["Emission"]
    em.inputs["Strength"].default_value = keyed(f.get("strength", 30), u)
    return o


def burst(name, c, u, n, colour, strength, reach, seed, size):
    drop(name)
    rng = random.Random(seed)
    bm = bmesh.new()
    for i in range(n):
        d = Vector([rng.gauss(0, 1) for _ in range(3)]).normalized()
        t = (u * 1.4 - rng.random() * 0.4)
        if t <= 0:
            continue
        p = c + d * reach * ease(min(1.0, t)) * (0.4 + 0.6 * rng.random())
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=size * (0.6 + 0.8 * rng.random()),
                                   matrix=Matrix.Translation(p))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(emissive(name, colour, strength))
    return link(bpy.data.objects.new(name, me))


def shot_brain(st, sh):
    """A brain shot: update(u) moves the camera and window, lights parts, grows them, runs the streams."""
    st.show("brain")
    c = sh["cam"]
    unit, mid = st.unit, st.mid
    cam = temp(bpy.data.objects.new("cam", bpy.data.cameras.new("cam")))
    scene.camera = cam
    cam.data.lens = c.get("lens", 40 if c.get("aim") == "all" else 50)
    cam.data.sensor_fit, cam.data.sensor_height, cam.data.clip_start = "VERTICAL", 24, 0.001
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = c.get("fstop", 6)
    cam.data.dof.aperture_blades = 7
    tint = Vector(sh.get("tint", [1.0, 0.9, 0.82]))
    eye0 = mid + Vector(c.get("dir", [-0.55, -1, 0.2])).normalized() * unit * 1.8
    side = Vector((eye0.x - mid.x, eye0.y - mid.y, 0)).normalized()
    across = Vector((-side.y, side.x, 0))
    lamp("key", "AREA", mid + (side * 1.1 + across * 0.7 + Vector((0, 0, 1.0))) * unit, mid, 30, unit * 0.6, tuple(tint))
    lamp("rim", "AREA", mid + (-side * 1.2 - across * 0.6 + Vector((0, 0, 0.5))) * unit, mid, 45, unit * 0.6,
         (0.55, 0.72, 1.0))
    lamp("rim2", "AREA", mid + (-side * 1.0 + across * 0.9 + Vector((0, 0, 0.2))) * unit, mid, 20, unit * 0.6,
         (0.6, 0.75, 1.0))
    lamp("bounce", "AREA", mid + (side * 0.8 - Vector((0, 0, 1.1))) * unit, mid, 3, unit * 1.5, (1.0, 0.7, 0.6))
    glows = {r: lamp("glow " + r, "POINT", mid, mid, 0, 0.004, GLOW[r]) for r in sh.get("lit", {})}
    rng = random.Random(sh.get("seed", 3))
    dust_c = mid + side * unit * 0.8
    dust(110, rng, dust_c, (unit * 0.9, unit * 0.9, unit * 0.9))
    dobj = bpy.data.objects["dust"]
    TEMP.append("dust")
    for r in GLOW:
        if r in st.deep:
            st.live.glow(r, 0.0)
    flows = sh.get("flows", [])
    win = sh.get("window", {})
    reg = sh.get("region")

    def update(u):
        focus = st.near(c["focus"], mid + side * unit) if not isinstance(c["focus"], list) else Vector(c["focus"])
        d = Matrix.Rotation(math.radians(keyed(c.get("orbit", [0, 0]), u)), 3, "Z") @ Vector(
            c.get("dir", [-0.55, -1, 0.2])).normalized()
        eye = focus + d * unit * keyed(c.get("dist", 1.8), u)
        look = (mid if c.get("aim") == "all" else focus) + Vector(c.get("shift", [0, 0, 0])) * unit
        cam.location = eye
        cam.rotation_euler = (look - eye).to_track_quat("-Z", "Y").to_euler()
        cam.data.dof.focus_distance = (focus - eye).length
        st.live.window(eye, st.near(win.get("at", c["focus"]), eye), win.get("radius", 0.1) * unit,
                       win.get("soft", 0.045) * unit)
        if reg:
            st.live.region(st.pfc + Vector((0, -0.01, 0)), 0.055, reg["color"], keyed(reg["strength"], u))
        else:
            st.live.region(mid, 0.01, (0, 0, 0), 0.0)
        for r, keys in sh.get("lit", {}).items():
            v = keyed(keys, u)
            st.live.glow(r, v)
            glows[r].location = st.near(r, eye)
            glows[r].data.energy = v * 0.05
        for r, keys in sh.get("grow", {}).items():
            k = keyed(keys, u)
            for o, cc in zip(st.deep[r], st.centres[r]):
                o.matrix_world = Matrix.Translation(cc) @ Matrix.Scale(k, 4) @ Matrix.Translation(-cc) @ st.rest[o]
        pins = {}
        for i, f in enumerate(flows):
            a, b = st.near(f["from"], eye), st.near(f["to"], eye)
            stream(f"flow {i}", a, b, f, u, 100 + i, unit, None)
            TEMP.append(f"flow {i}")
            h = keyed(f.get("head", 0.8), u)
            pins["stream"] = px(cam, bezier(a, b, Vector(f.get("arc", [0, 0, 0])) * unit, max(0.0, h - 0.15)))
        dobj.location = (0, 0, u * 0.004)
        for r in ("amygdala", "hippocampus", "hypothalamus", "pituitary"):
            if r in st.deep:
                ctr = st.near(r, eye)
                towards = (eye - ctr).normalized()
                pins[r] = px(cam, ctr + towards * 0.004)
        pins["pfc"] = px(cam, st.pfc + Vector((0, -0.02, 0.01)))
        return pins

    return update


def shot_adrenal(st, sh):
    """The adrenal gland on its kidney: a nerve signal arrives, the medulla bursts out adrenaline (amber), or the
    cortex glows and releases cortisol (violet)."""
    st.show("adrenal")
    phase = sh.get("phase", "nerve")
    g, med, ctr = min(st.glands.values(), key=lambda x: x[2].x)  # the gland on the camera's side
    for o in st.adrenal:  # only this side's gland, medulla, kidney and vessels (the other kidney sat at the edge)
        if (o.matrix_world @ (sum((v.co for v in o.data.vertices), Vector()) / max(1, len(o.data.vertices)))
                if o.type == "MESH" else o.matrix_world.translation).x > ctr.x + 0.06:
            o.hide_render = True
    unit = 0.12
    base = Vector((-0.55, -1.0, 0.3)).normalized()
    cam = temp(bpy.data.objects.new("cam", bpy.data.cameras.new("cam")))
    scene.camera = cam
    cam.data.lens, cam.data.sensor_fit, cam.data.sensor_height, cam.data.clip_start = 50, "VERTICAL", 24, 0.001
    cam.data.dof.use_dof, cam.data.dof.aperture_fstop = True, 16  # close up: f/16 keeps the whole gland sharp
    look = ctr + Vector((0, 0, -0.03))  # the gland in the upper third, its kidney below
    lamp("key", "AREA", ctr + Vector((-0.12, -0.15, 0.15)), ctr, 6, 0.08, (1.0, 0.9, 0.82))
    lamp("rim", "AREA", ctr + Vector((0.12, 0.15, 0.08)), ctr, 10, 0.08, (0.55, 0.72, 1.0))
    lamp("bounce", "AREA", ctr + Vector((-0.05, -0.1, -0.15)), ctr, 1.5, 0.15, (1.0, 0.7, 0.6))
    lamp("fill", "AREA", ctr + Vector((-0.1, -0.14, -0.06)), ctr + Vector((0, 0, -0.05)), 4, 0.1, (1.0, 0.88, 0.8))
    gl = lamp("glow", "POINT", ctr, ctr, 0, 0.004, (1.0, 0.55, 0.1))
    rng = random.Random(9)
    dust(80, rng, ctr + base * 0.06, (0.08, 0.08, 0.08))
    dobj = bpy.data.objects["dust"]
    TEMP.append("dust")
    mb = st.med_mat.node_tree.nodes["Principled BSDF"]
    gb = st.gland_mat.node_tree.nodes["Principled BSDF"]
    amber, violet = (1.0, 0.55, 0.08), (0.62, 0.3, 1.0)
    orbit = {"nerve": [-8, 4], "adrenaline": [4, -6], "cortisol": [-6, 6]}[phase]
    dist = {"nerve": [0.36, 0.31], "adrenaline": [0.3, 0.27], "cortisol": [0.32, 0.28]}[phase]

    def update(u):
        d = Matrix.Rotation(math.radians(orbit[0] + (orbit[1] - orbit[0]) * ease(u)), 3, "Z") @ base
        eye = ctr + d * (dist[0] + (dist[1] - dist[0]) * ease(u))
        cam.location = eye
        cam.rotation_euler = (look - eye).to_track_quat("-Z", "Y").to_euler()
        cam.data.dof.focus_distance = (ctr - eye).length
        med_glow = cortex_glow = 0.0
        if phase == "nerve":
            top = ctr + Vector((0.01, 0.0, 0.075))
            o = stream("nerve", top, ctr, {"head": [0.0, 1.0], "n": 50, "color": [1.0, 0.25, 0.08], "strength": 12,
                                           "arc": [0.0, -0.05, 0.0], "size": 0.003}, u, 5, unit, None)
            TEMP.append(o.name)
            med_glow = 6.0 * ease((u - 0.75) / 0.25)
        elif phase == "adrenaline":
            med_glow = 5.0 + 4.0 * ease(u / 0.2)
            o = burst("adrenaline", ctr, u, 160, amber, 9.0, 0.05, 6, 0.0012)
            TEMP.append(o.name)
        else:
            cortex_glow = 2.5 * ease(u / 0.3)
            o = burst("cortisol", ctr, u * 0.8, 120, violet, 7.0, 0.045, 8, 0.0011)
            TEMP.append(o.name)
        mb.inputs["Emission Color"].default_value = (*amber, 1)
        mb.inputs["Emission Strength"].default_value = med_glow
        gb.inputs["Emission Color"].default_value = (*violet, 1)
        gb.inputs["Emission Strength"].default_value = cortex_glow
        gl.location = ctr
        gl.data.color = amber if phase != "cortisol" else violet
        gl.data.energy = 0.03 * (med_glow + cortex_glow)
        dobj.location = (0, 0, u * 0.003)
        towards = (eye - ctr).normalized()
        return {"gland": px(cam, ctr + towards * 0.008 + Vector((0, 0, 0.006))), "medulla": px(cam, ctr),
                "stream": px(cam, ctr + Vector((0.02, 0, 0.02)))}

    return update


def animate():
    for o in list(bpy.data.objects):  # the factory startup's cube, light and camera
        bpy.data.objects.remove(o)
    st = None
    for sh in spec["shots"]:
        if spec.get("only") and sh["name"] not in spec["only"]:
            continue
        if st is None:
            st = Stage()
        for name in set(TEMP):
            drop(name)
        TEMP.clear()
        update = (shot_adrenal if sh["kind"] == "adrenal" else shot_brain)(st, sh)
        if spec.get("debug"):
            for o in scene.objects:
                if o.type in ("MESH", "META") and not o.hide_render and max(o.dimensions) > 0.05:
                    print("BIG", o.name, [round(x, 3) for x in o.dimensions], [round(x, 3) for x in o.matrix_world.translation])
        d = OUT / sh["name"]
        d.mkdir(exist_ok=True)
        allpins, t0 = [], time.time()
        n = sh.get("frames", 1)
        for f in range(n):
            allpins.append(update(f / max(1, n - 1)))
            if (d / f"{f:05d}.png").exists() and not spec.get("redo"):
                continue
            if f % spec.get("step", 1):
                continue
            scene.render.filepath = str(d / f"{f:05d}.png")
            bpy.ops.render.render(write_still=True)
            if f % 30 == 0:
                print("FRAME", sh["name"], f, n, round((time.time() - t0) / (f + 1), 1), "s/frame", flush=True)
        (d / "pins.json").write_text(json.dumps(allpins))
        print("SHOT", sh["name"], n, "frames", flush=True)


OUT.mkdir(parents=True, exist_ok=True)
ANIMATED = any(sh.get("kind") in ("brain", "adrenal") for sh in spec["shots"])
if ANIMATED:
    setup(spec.get("samples", 64))
    animate()
for sh in ([] if ANIMATED else spec["shots"]):
    if spec.get("only") and sh["name"] not in spec["only"]:
        continue
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    for m in list(bpy.data.materials):
        bpy.data.materials.remove(m)
    setup(spec.get("samples", 64))
    render_shot(sh, load())
