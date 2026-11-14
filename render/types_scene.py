"""The 3D layer of a "types" video made of real anatomy parts (format "types", items with "scene": "parts"). Runs
inside Blender:

    blender -b --factory-startup --python render/types_scene.py -- '<json spec>'

The same studio, camera moves, timeline and label pins as render/fracture_scene.py (which still draws the fracture
video by itself), but each type is any set of Z-Anatomy parts with something happening to it: a joint moving through
its range, a ligament tearing, a kneecap sliding out. anatomy/types.py passes, per type, a "show" block:

  "model": "knee"                      assets/models/<model>.blend
  "parts": [names]                     what's on screen (default: every part in the model)
  "orient": [rx, ry, rz]               degrees, turns the body coordinates (z up, -y front) to face the camera
  "frame": [[x0, y0, z0], [x1, y1, z1]] body-coordinate box the wide shot fits (default: the parts' box)
  "smooth": [names]                    subdivided first (the atlas menisci are low-poly)
  "moves": [{"parts": [names], "pivot": P, "keys": [[t, rx, ry, rz, tx, ty, tz], ...]}]
                                       rigid groups turning (degrees, body axes) and sliding (metres) about a pivot;
                                       t is seconds after the event; before the first key the group holds that pose.
                                       Optional "axes": {"x": [P, P], "z": [P, P]}: turn and slide about these
                                       directions instead of the body's (the atlas hand is tilted and curled, so a
                                       finger bends toward the palm about the line across the knuckles)
  "bands": [{"name", "from": P, "to": P, "width", "thick", "kind"}]
                                       a strap (tendon, ligament) drawn between two points; it stretches between the
                                       groups its ends belong to
  "spans": [{"part", "from": P, "to": P}]  an atlas part hooked between two groups, so it stretches with them
  "tears": [{"part", "at": P, "normal": [x, y, z], "gap": m, "delay": s}]
                                       the part splits along a plane at the event (+ delay) and the halves pull apart
  "lit": [names]                       glow yellow for the whole type, so the eye finds them
  "hurt": [names]                      turn red at the event
  "ghost": [names]                     see-through (an X-ray look), so a ligament inside the joint shows
  "pin": P, "focus": P, "zoom": 0.5    the label's pin, the point the camera closes in on, close distance / wide
P (a point) is {"part": name, "at": [fx, fy, fz]}: fractions of that part's box in body coordinates, snapped to the
part's nearest vertex; or {"xyz": [x, y, z]} in body coordinates. A point's group is the group of its part.

spec: {"root", "out", "fps", "width", "height", "samples", "frames", "timeline", "shows": {name: show}, "only"}
"""

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Matrix, Vector, kdtree

spec = json.loads(sys.argv[sys.argv.index("--") + 1])
ROOT = Path(spec["root"])
FPS = spec.get("fps", 30)
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
SHOWS = spec["shows"]


# --- materials (the bone is the fracture video's) ----------------------------------------------------------------
def material(name, rgb, roughness, sss=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = roughness
    if sss:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = (0.004, 0.003, 0.002)
    return m


def bumped(m, scale, strength):
    nt = m.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    nt.links.new(tc.outputs["Object"], tex.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])


KINDS = {  # base colour, roughness, subsurface
    "bone": ((0.74, 0.69, 0.60), 0.5, 0.12),
    "ligament": ((0.86, 0.80, 0.66), 0.35, 0.2),   # glossy white-cream, a shade off the bone
    "cartilage": ((0.62, 0.76, 0.86), 0.3, 0.25),  # the menisci: pale blue, as atlases draw them
    "muscle": ((0.45, 0.07, 0.07), 0.45, 0.1),
}
LIT, HURT = (0.96, 0.82, 0.10), (0.85, 0.06, 0.05)


def kind_of(name):
    n = name.lower()
    if "menisc" in n or "labrum" in n:
        return "cartilage"
    if "ligament" in n or "tendon" in n:
        return "ligament"
    if "muscle" in n:
        return "muscle"
    return "bone"


def part_material(tag, kind, lit=False, hurt=False):
    """A material of its own (so its colour can be keyed): the kind's colour mixed toward yellow or red."""
    rgb, rough, sss = KINDS[kind]
    m = material(tag, rgb, rough, sss)
    if kind == "bone":
        bumped(m, 260, 0.06)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    if lit or hurt:
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["A"].default_value = (*rgb, 1)
        mix.inputs["B"].default_value = (*(HURT if hurt else LIT), 1)
        mix.inputs["Factor"].default_value = 1.0 if lit and not hurt else 0.0
        nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
        nt.links.new(mix.outputs["Result"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = 0.35 if lit and not hurt else 0.0
        if lit and hurt:  # yellow first, then red at the event
            mix.inputs["A"].default_value = (*LIT, 1)
            b.inputs["Emission Strength"].default_value = 0.35
        m["mix"] = mix.name
    return m


def ghost(m, alpha=0.22):
    m.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = alpha
    m.surface_render_method = "BLENDED"
    m.use_transparency_overlap = False


# --- loading -------------------------------------------------------------------------------------------------
LIB = {}


def library(model):
    if model not in LIB:
        with bpy.data.libraries.load(str(ROOT / "assets" / "models" / f"{model}.blend")) as (src, dst):
            dst.objects = src.objects
        LIB[model] = {o.name.split(".0")[0] if o.name[-4:-3] == "." and o.name[-3:].isdigit() else o.name: o
                      for o in dst.objects if o and o.type == "MESH" and not o.name.startswith("Cross Section")}
    return LIB[model]


def bake(o):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
    o.modifiers.clear()
    o.data = me


def fresh(src, tag, smooth=False):
    """A copy of an atlas part, in body coordinates, unhidden, normals outward, smooth shaded."""
    o = bpy.data.objects.new(f"{tag}:{src.name}", src.data.copy())
    scene.collection.objects.link(o)
    o.matrix_world = src.matrix_world.copy()
    o.data.transform(o.matrix_world)
    o.matrix_world = Matrix()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(o.data)
    bm.free()
    if smooth:
        m = o.modifiers.new("smooth", "SUBSURF")
        m.levels = m.render_levels = 2
        bake(o)
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def box(objs):
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    return (Vector([min(p[i] for p in pts) for i in range(3)]), Vector([max(p[i] for p in pts) for i in range(3)]))


def band_mesh(name, a, b, width, thick, n=24):
    """A rounded strap from a to b (body coordinates), widest in the middle like a real ligament."""
    axis = (b - a)
    length = axis.length
    d = axis.normalized()
    side = d.cross(Vector((0, -1, 0)))
    side = side.normalized() if side.length > 1e-6 else Vector((1, 0, 0))
    up = side.cross(d).normalized()
    bm = bmesh.new()
    rings, m = [], 10
    for i in range(n + 1):
        s = i / n
        c = a + axis * s
        w = width * (0.75 + 0.25 * math.sin(math.pi * s))
        ring = []
        for j in range(m):
            ang = 2 * math.pi * j / m
            ring.append(bm.verts.new(c + side * math.cos(ang) * w / 2 + up * math.sin(ang) * thick / 2))
        rings.append(ring)
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(m):
            bm.faces.new((r0[j], r0[(j + 1) % m], r1[(j + 1) % m], r1[j]))
    bm.faces.new(rings[0][::-1])
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    for p in o.data.polygons:
        p.use_smooth = True
    return o, length


def split(o, point, normal):
    """Two halves of o on either side of a plane, each closed over the cut."""
    halves = []
    for keep_pos in (True, False):
        h = bpy.data.objects.new(o.name + ("+" if keep_pos else "-"), o.data.copy())
        scene.collection.objects.link(h)
        bm = bmesh.new()
        bm.from_mesh(h.data)
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=point, plane_no=normal,
                                     clear_inner=keep_pos, clear_outer=not keep_pos)
        cut = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
        if cut:
            bmesh.ops.holes_fill(bm, edges=cut, sides=0)
        bm.to_mesh(h.data)
        bm.free()
        for p in h.data.polygons:
            p.use_smooth = True
        halves.append(h)
    return halves


# --- one type's assembly --------------------------------------------------------------------------------------
H0 = 0.42  # every assembly's wide shot is this tall (the femur in the fracture video is 0.45)


class Show:
    def __init__(self, name, s, tag):
        s = json.loads(json.dumps(s))  # a copy: the moves get their pivots filled in
        self.name, self.s = name, s
        lib = library(s["model"])
        wanted = s.get("parts") or list(lib)
        self.parts = {n: fresh(lib[n], tag, n in s.get("smooth", [])) for n in wanted}
        self.lit, self.hurt = set(s.get("lit", [])), set(s.get("hurt", []))
        self.mats = {}
        for n, o in self.parts.items():
            m = part_material(f"{tag}:{n}", kind_of(n), n in self.lit, n in self.hurt)
            if n in s.get("ghost", []):
                ghost(m)
            o.data.materials.clear()
            o.data.materials.append(m)
            self.mats[n] = m
        # the root: body coordinates -> centred, turned and scaled to the standard height
        lo, hi = (Vector(s["frame"][0]), Vector(s["frame"][1])) if s.get("frame") else box(self.parts.values())
        centre = (lo + hi) / 2
        rot = Euler([math.radians(a) for a in s.get("orient", [0, 0, 0])]).to_matrix().to_4x4()
        corners = [rot @ Vector((x, y, z)) - rot @ centre for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
        h = max(c.z for c in corners) - min(c.z for c in corners)
        w = max(c.x for c in corners) - min(c.x for c in corners)
        self.scale = min(H0 / h, H0 * 0.5625 * 0.92 / w)
        self.root = bpy.data.objects.new(f"{tag}:root", None)
        scene.collection.objects.link(self.root)
        self.root_rest = Matrix.Diagonal((self.scale,) * 3 + (1,)) @ rot @ Matrix.Translation(-centre)
        self.root.matrix_basis = self.root_rest
        # groups: 0 is the still part, then one per move
        self.group_of = {n: 0 for n in self.parts}
        self.groups = [self.root]
        self.moves = s.get("moves", [])
        for k, mv in enumerate(self.moves):
            g = bpy.data.objects.new(f"{tag}:g{k + 1}", None)
            scene.collection.objects.link(g)
            g.parent = self.root
            mv["_pivot"] = self.point(mv["pivot"])[0]
            mv["_axes"] = self.axes(mv["axes"]) if mv.get("axes") else Matrix.Identity(3)
            g.location = mv["_pivot"]
            self.groups.append(g)
            for n in mv["parts"]:
                self.group_of[n] = k + 1
        for n, o in self.parts.items():
            self.attach(o, self.group_of[n])
        # straps between two points (and atlas parts hooked the same way)
        self.objs = list(self.parts.values())
        for b in s.get("bands", []):
            (pa, ga), (pb, gb) = self.point(b["from"]), self.point(b["to"])
            o, _ = band_mesh(f"{tag}:{b['name']}", pa, pb, b.get("width", 0.02), b.get("thick", 0.005))
            n = b["name"]
            m = part_material(f"{tag}:{n}", b.get("kind", "ligament"), n in self.lit, n in self.hurt)
            o.data.materials.append(m)
            self.mats[n] = m
            self.parts[n] = o
            self.group_of[n] = ga
            self.attach(o, 0)
            self.hook(o, pa, pb, ga, gb)
            self.objs.append(o)
        for sp in s.get("spans", []):
            o = self.parts[sp["part"]]
            (pa, ga), (pb, gb) = self.point(sp["from"]), self.point(sp["to"])
            o.parent = None
            self.attach(o, 0)
            self.hook(o, pa, pb, ga, gb)
        # tears: the intact part shows until the event, then its two halves
        self.tears = []
        for t in s.get("tears", []):
            o = self.parts[t["part"]]
            p = self.point(t["at"])[0]
            nrm = Vector(t["normal"]).normalized()
            halves = split(o, p, nrm)
            ga, gb = t.get("groups", [self.group_of[t["part"]]] * 2)
            pieces = []
            for h, sign, g in zip(halves, (1, -1), (ga, gb)):
                h.data.materials.clear()
                h.data.materials.append(self.mats[t["part"]])
                rec = bpy.data.objects.new(h.name + ":recoil", None)
                scene.collection.objects.link(rec)
                rec.parent = self.groups[g]
                rec.matrix_parent_inverse = self.inverse(g)
                h.parent = rec
                pieces.append((h, rec, nrm * sign * t.get("gap", 0.004)))
                self.objs.append(h)
            self.tears.append({"part": t["part"], "obj": o, "pieces": pieces, "delay": t.get("delay", 0.0)})
        self.pin_obj, self.pin_co = self.anchor(s["pin"])
        self.focus = self.point(s.get("focus", s["pin"]))[0]
        self.zoom = s.get("zoom", 0.5)

    # where things sit
    def inverse(self, g):
        return Matrix() if g == 0 else Matrix.Translation(-self.moves[g - 1]["_pivot"])

    def attach(self, o, g):
        o.parent = self.groups[g]
        o.matrix_parent_inverse = self.inverse(g)

    def point(self, p):
        """(body-coordinate point, its group) for a point spec."""
        if "xyz" in p:
            return Vector(p["xyz"]), p.get("group", 0)
        if "fit" in p:  # the centre of the sphere that best fits a part's surface near a point (a joint's ball)
            near = self.point({"part": p["fit"], "at": p["at"]})[0]
            vs = [v.co for v in self.parts[p["fit"]].data.vertices if (v.co - near).length < p.get("r", 0.02)]
            return sphere(vs), p.get("group", self.group_of.get(p["fit"], 0))
        o = self.parts[p["part"]]
        vs = [v.co for v in o.data.vertices]
        lo = Vector([min(v[i] for v in vs) for i in range(3)])
        hi = Vector([max(v[i] for v in vs) for i in range(3)])
        want = Vector([lo[i] + (hi[i] - lo[i]) * p["at"][i] for i in range(3)])
        best = min(vs, key=lambda v: (v - want).length) if p.get("snap", True) else want
        return best.copy(), p.get("group", self.group_of.get(p["part"], 0))

    def axes(self, a):
        """A rotation whose columns are the move's own x, y, z (x and z from pairs of points, made square)."""
        x = (self.point(a["x"][1])[0] - self.point(a["x"][0])[0]).normalized()
        z = (self.point(a["z"][1])[0] - self.point(a["z"][0])[0]).normalized()
        y = z.cross(x).normalized()
        z = x.cross(y).normalized()
        return Matrix((x, y, z)).transposed()

    def anchor(self, p):
        """The object a label pin rides on, and the pin in that object's mesh coordinates."""
        co, _ = self.point(p)
        name = p.get("part")
        for t in getattr(self, "tears", []):
            if t["part"] == name:  # pin the half nearest the point
                h = min((h for h, _, _ in t["pieces"]), key=lambda h: min((v.co - co).length for v in h.data.vertices))
                return h, co
        if name in self.parts:
            return self.parts[name], co
        return self.root, co

    def hook(self, o, pa, pb, ga, gb):
        """Vertices follow group ga near pa and gb near pb, blended in between."""
        d = pb - pa
        for g, name, w in ((ga, "A", lambda s: 1 - s), (gb, "B", lambda s: s)):
            vg = o.vertex_groups.new(name=name)
            for v in o.data.vertices:
                s = min(1.0, max(0.0, (v.co - pa).dot(d) / d.length_squared))
                s = s * s * (3 - 2 * s)
                vg.add([v.index], w(s), "REPLACE")
            if g == 0:
                continue  # the still part needs no hook: those vertices stay put
            e = bpy.data.objects.new(o.name + ":hook" + name, None)
            scene.collection.objects.link(e)
            e.parent = self.groups[g]
            e.matrix_parent_inverse = self.inverse(g)
            m = o.modifiers.new("hook" + name, "HOOK")
            m.object, m.vertex_group = e, name
            m.falloff_type = "NONE"
        bpy.context.view_layer.update()
        for m in o.modifiers:
            if m.type == "HOOK":
                m.matrix_inverse = m.object.matrix_world.inverted() @ o.matrix_world

    def all_objects(self):
        return self.objs

    def visible(self, t_event):
        """What's on screen t_event seconds after the event (negative: before it)."""
        out = []
        torn = {t["part"]: t for t in self.tears}
        for n, o in self.parts.items():
            t = torn.get(n)
            if t and t_event >= t["delay"]:
                out += [h for h, _, _ in t["pieces"]]
            else:
                out.append(o)
        return out

    def pose(self, t_event, k=None):
        """Key every moving thing for time t_event at frame k (or just set it, for the chart)."""
        for g, mv in zip(self.groups[1:], self.moves):
            r, tr = sample(mv["keys"], t_event)
            f = mv["_axes"]
            rot = f @ Euler([math.radians(a) for a in r]).to_matrix() @ f.transposed()
            g.rotation_euler = rot.to_euler("XYZ", g.rotation_euler)
            g.location = mv["_pivot"] + f @ Vector(tr)
            if k is not None:
                g.keyframe_insert("rotation_euler", frame=k)
                g.keyframe_insert("location", frame=k)
        for t in self.tears:
            a = ease((t_event - t["delay"]) / 0.35) if t_event >= t["delay"] else 0.0
            for _, rec, off in t["pieces"]:
                rec.location = off * a
                if k is not None:
                    rec.keyframe_insert("location", frame=k)
        for n in self.hurt:
            m = self.mats[n]
            mix = m.node_tree.nodes[m["mix"]]
            b = m.node_tree.nodes["Principled BSDF"]
            f = min(1.0, max(0.0, (t_event - 0.05) / 0.3))
            mix.inputs["Factor"].default_value = f
            b.inputs["Emission Strength"].default_value = (0.35 if n in self.lit else 0.0) * (1 - f) + 0.6 * f
            if k is not None:
                mix.inputs["Factor"].keyframe_insert("default_value", frame=k)
                b.inputs["Emission Strength"].keyframe_insert("default_value", frame=k)


def sphere(vs):
    """Least-squares sphere centre through points (|p|^2 = 2 c.p + k)."""
    import numpy as np
    a = np.array([[2 * v.x, 2 * v.y, 2 * v.z, 1.0] for v in vs])
    b = np.array([v.length_squared for v in vs])
    c = np.linalg.lstsq(a, b, rcond=None)[0]
    return Vector(c[:3])


def ease(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def sample(keys, t):
    """Rotation and slide at time t from [[t, rx, ry, rz, (tx, ty, tz)], ...], eased between keys."""
    full = [list(k) + [0.0] * (7 - len(k)) for k in keys]
    if t <= full[0][0]:
        k = full[0]
    elif t >= full[-1][0]:
        k = full[-1]
    else:
        i = next(i for i in range(len(full) - 1) if full[i][0] <= t < full[i + 1][0])
        a, b = full[i], full[i + 1]
        f = smooth((t - a[0]) / (b[0] - a[0]))
        k = [a[j] + (b[j] - a[j]) * f for j in range(7)]
    return k[1:4], k[4:7]


SHOWN = {n: Show(n, s, n) for n, s in SHOWS.items()}


# --- stage: the fracture video's lights, render settings and camera ------------------------------------------------
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

ELEV = math.radians(4)
TAN = 12 / cam.data.lens
ASPECT = scene.render.resolution_x / scene.render.resolution_y
WIDE_D = H0 / 0.78 / (2 * TAN)


def frame_h(d):
    return 2 * d * TAN


def look(target, d, slide=0.0):
    back = Vector((0, -math.cos(ELEV), math.sin(ELEV)))
    pos = Vector(target) + back * d + Vector((slide * frame_h(d) * ASPECT, 0, 0))
    rot = (-back).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    return Matrix.Translation(pos) @ rot


def aim(point, d, ox=-0.06, oy=0.07):
    return Vector(point) - Vector((ox * frame_h(d) * ASPECT, 0, oy * frame_h(d)))


pivot = bpy.data.objects.new("pivot", None)
scene.collection.objects.link(pivot)
for sh in SHOWN.values():
    sh.root.parent = pivot


def world_focus(sh):
    """The focus point in pivot space (before the pivot turns), at rest."""
    return sh.root_rest @ sh.focus


TL = spec.get("timeline", [])
TOTAL = spec.get("frames", 1)
F = lambda t: int(round(t * FPS))  # noqa: E731
shown: dict[int, set] = {}
poses: dict = {}  # (show name) -> {frame: t_event}


def show(objs, a, b):
    for k in range(a, b):
        shown.setdefault(k, set()).update(objs)


def act(sh, a, b, event, speed=1.0):
    """Show sh from frame a to b with its event at frame `event`, playing `speed` times faster."""
    for k in range(a, b):
        te = (k - event) / FPS * speed
        show(sh.visible(te), k, k + 1)
        poses.setdefault(sh.name, {})[k] = te


cams, pivots, pins = {}, {}, {}
for seg in TL:
    a, b = F(seg["start"]), F(seg["end"])
    if seg["kind"] == "flash":  # the hook: every type's event, fast, one after another
        names = seg["types"]
        step = (b - a) / len(names)
        for i, n in enumerate(names):
            fa, fb = a + int(i * step), a + int((i + 1) * step)
            sh = SHOWN[n]
            last = max((mv["keys"][-1][0] for mv in sh.moves), default=0.4)
            last = max([last] + [t["delay"] + 0.35 for t in sh.tears])
            act(sh, fa, fb, fa + 1, speed=max(1.0, last / ((fb - fa - 3) / FPS)))
            for k in range(fa, fb):
                pins[k] = {"show": n, "small": True}
                cams[k] = look(Vector((0, 0, 0)), WIDE_D * (1.02 - 0.04 * (k - a) / max(1, b - a)))
                pivots[k] = 0.0
    elif seg["kind"] == "intro":  # an extreme close-up on the first type, pulling back to the whole thing
        first = SHOWN[next(s["name"] for s in TL if s["kind"] == "type")]
        act(first, a, b, b + 10 ** 6)
        f = world_focus(first)
        for k in range(a, b):
            t = smooth((k - a) / max(1, b - a - 6))
            d = WIDE_D * (0.32 + 0.68 * t)
            cams[k] = look(f.lerp(Vector((0, 0, 0)), t), d)
            pivots[k] = math.radians(-25 * (1 - t))
    elif seg["kind"] == "type":
        sh = SHOWN[seg["name"]]
        event = a + F(seg.get("crack", 0.45))
        act(sh, a, b, event)
        whip = F(0.27)
        close = WIDE_D * sh.zoom
        for k in range(a, b):
            t = smooth((k - a - F(0.3)) / max(1, b - a - F(0.6)))
            ang = math.radians(-10 + 22 * (k - a) / max(1, b - a))
            rotz = Matrix.Rotation(ang, 4, "Z")
            d = WIDE_D + (close - WIDE_D) * t
            tgt = Vector((0, 0, 0)).lerp(aim(rotz @ world_focus(sh), close), t)
            slide = 0.0
            if seg.get("whip_in", True) and k < a + whip:
                slide = -1.3 * (1 - smooth((k - a) / whip)) ** 2
            if k >= b - whip:
                slide = 1.3 * smooth((k - (b - whip)) / whip) ** 2
            cams[k] = look(tgt, d, slide)
            pivots[k] = ang
            if k >= event:
                pins[k] = {"show": seg["name"]}
    elif seg["kind"] == "outro":  # pull far back from the last type
        last = cams.get(a - 1, look(Vector(), WIDE_D))
        lastp = pivots.get(a - 1, 0.0)
        name = TL[TL.index(seg) - 1].get("name")
        if name and poses.get(name):
            sh = SHOWN[name]
            te = poses[name][max(poses[name])]
            for k in range(a, b):
                show(sh.visible(te + (k - a) / FPS), k, k + 1)
                poses[name][k] = te + (k - a) / FPS
        for k in range(a, b):
            t = smooth((k - a) / max(1, b - a))
            cams[k] = look(Vector((0, 0, 0)), WIDE_D * (1 + 3.5 * t)) if t > 0 else last
            pivots[k] = lastp

# the closing chart: anatomy/types.py lays it out in 2D from one still per type (thumb_<name>.png: a second copy of
# the type after its event, alone, in its wide shot), so long bones are cropped the way the wide shot crops them
grid = next((s for s in TL if s["kind"] == "grid"), None)
if grid:
    a, b = F(grid["start"]), F(grid["end"])
    out_dir = Path(spec["out"])
    out_dir.mkdir(parents=True, exist_ok=True)
    thumbs = [Show(n, SHOWS[n], n + "_grid") for n in SHOWS]
    keep = (scene.render.resolution_x, scene.render.resolution_y, scene.render.use_motion_blur)
    scene.render.resolution_x, scene.render.resolution_y = int(keep[0] * 0.6), int(keep[1] * 0.6)
    scene.render.use_motion_blur = False
    cam.matrix_world = look(Vector((0, 0, 0)), WIDE_D)
    pivot.rotation_euler = (0, 0, math.radians(spec.get("chart_turn", 8)))
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = True
    for g in thumbs:
        g.root.parent = pivot
        hold = SHOWS[g.name].get("chart_t", 3.0)
        g.pose(hold)
        vis = g.visible(hold)
        for o in vis:
            o.hide_render = False
        scene.render.filepath = str(out_dir / f"thumb_{g.name}.png")
        bpy.ops.render.render(write_still=True)
        for o in vis:
            o.hide_render = True
    scene.render.resolution_x, scene.render.resolution_y, scene.render.use_motion_blur = keep
    pivot.rotation_euler = (0, 0, 0)
    for k in range(a, b):
        cams[k] = look(Vector((0, 0, 0)), WIDE_D * 50)  # nothing of the 3D layer shows during the chart
        pivots[k] = 0.0
        pins[k] = {"grid": []}

# --- chips (fmt-types-05 on): a tear with "chips": n bursts bone chips from its point, as in the fracture video.
# anatomy/types.py leaves this block out of the 3D cache key when no tear asks for chips, so 02-04 keep their cache.
import random  # noqa: E402

CHIPS = [material("chip_marrow", (0.55, 0.16, 0.10), 0.6), material("chip_ivory", KINDS["bone"][0], 0.5)]


def burst(sh, t, at, rng, n):
    """n chips flying out of tear t's point from frame `at` for ~0.7 s, in the show's body coordinates."""
    p0 = sh.point(t["at"])[0]
    rot = Euler([math.radians(a) for a in sh.s.get("orient", [0, 0, 0])]).to_matrix()
    down = rot.inverted() @ Vector((0, 0, -1))  # the screen's down, in body coordinates
    unit = 1 / sh.scale  # one metre of the fracture video's 0.45 m femur, in body units
    for i in range(n):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
        for v in bm.verts:
            v.co *= rng.uniform(0.6, 1.3)
        me = bpy.data.meshes.new("chip")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(CHIPS[0] if rng.random() < 0.55 else CHIPS[1])
        o = bpy.data.objects.new("chip", me)
        scene.collection.objects.link(o)
        o.parent = sh.root
        d = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))).normalized()
        v0 = d * rng.uniform(0.05, 0.2) * unit
        size = rng.uniform(0.0016, 0.0045) * unit  # bigger than the fracture video's: these are seen wide
        spin = Vector((rng.uniform(-20, 20), rng.uniform(-20, 20), rng.uniform(-20, 20)))
        life = rng.uniform(0.5, 0.9)
        o.hide_render = True
        o.keyframe_insert("hide_render", frame=0)
        for k in range(0, int(life * FPS) + 2, 2):
            s_ = k / FPS
            o.location = p0 + v0 * (1 - math.exp(-2.2 * s_)) / 2.2 + down * 0.08 * unit * s_ * s_
            o.rotation_euler = spin * s_
            o.scale = Vector((1, 1, 1)) * size * max(0.0, 1 - (s_ / life) ** 2)
            o.keyframe_insert("location", frame=at + k)
            o.keyframe_insert("rotation_euler", frame=at + k)
            o.keyframe_insert("scale", frame=at + k)
        show([o], at, at + int(life * FPS) + 2)


rng = random.Random(9)
for seg in TL:
    a, b = F(seg["start"]), F(seg["end"])
    if seg["kind"] == "flash":
        step = (b - a) / len(seg["types"])
        for i, n in enumerate(seg["types"]):
            sh = SHOWN[n]
            fa, fb = a + int(i * step), a + int((i + 1) * step)
            last = max((mv["keys"][-1][0] for mv in sh.moves), default=0.4)
            last = max([last] + [t["delay"] + 0.35 for t in sh.tears])
            speed = max(1.0, last / ((fb - fa - 3) / FPS))
            for t, spec_t in zip(sh.tears, sh.s.get("tears", [])):
                if spec_t.get("chips"):
                    burst(sh, spec_t, fa + 1 + int(round(t["delay"] * FPS / speed)), rng, max(6, spec_t["chips"] * 2 // 3))
    elif seg["kind"] == "type":
        sh = SHOWN[seg["name"]]
        for t, spec_t in zip(sh.tears, sh.s.get("tears", [])):
            if spec_t.get("chips"):
                burst(sh, spec_t, a + F(seg.get("crack", 0.45)) + F(t["delay"]), rng, spec_t["chips"])
# --- end chips

# key everything frame by frame
everything = [o for sh in SHOWN.values() for o in sh.all_objects()]
for o in everything:
    o.hide_render = True
    o.keyframe_insert("hide_render", frame=0)
for name, frames in poses.items():
    sh = SHOWN[name]
    ks = sorted(frames)
    for k in ks:
        sh.pose(frames[k], k)
# --- pulse (fmt-types-07 on): a show with "pulse": hz throbs its red glow that many times a second once it is hurt
# (a headache, where nothing breaks). anatomy/types.py leaves this block out of the 3D cache key when no show pulses.
for name, frames in poses.items():
    sh = SHOWN[name]
    hz = sh.s.get("pulse")
    if not hz:
        continue
    for k in sorted(frames):
        te = frames[k]
        if te < 0.35:
            continue
        beat = 0.5 + 0.5 * math.cos(2 * math.pi * hz * (te - 0.35))
        for n in sh.hurt:
            b = sh.mats[n].node_tree.nodes["Principled BSDF"]
            b.inputs["Emission Strength"].default_value = 0.2 + 1.1 * beat
            b.inputs["Emission Strength"].keyframe_insert("default_value", frame=k)
# --- end pulse

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
for o in bpy.data.objects:
    ad = o.animation_data
    if ad and ad.action:
        for fc in ad.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR" if not fc.data_path == "hide_render" else "CONSTANT"
for m in bpy.data.materials:
    ad = m.node_tree.animation_data if m.node_tree else None
    if ad and ad.action:
        for fc in ad.action.fcurves:
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
    sh = SHOWN[item["show"]]
    p = world_to_camera_view(scene, cam, sh.pin_obj.matrix_world @ sh.pin_co)
    anchors[k] = {"label": item["show"], "xy": [p.x * W_, (1 - p.y) * H_], "small": item.get("small", False)}
(out / "anchors.json").write_text(json.dumps(anchors))

frames = spec.get("only") or list(range(TOTAL))
if spec.get("only"):
    for k in frames:
        scene.frame_set(k)
        scene.render.filepath = str(out / f"{k:05d}.png")
        bpy.ops.render.render(write_still=True)
else:
    scene.render.filepath = str(out / "#####")
    bpy.ops.render.render(animation=True)
