"""The 3D layer of the blood types rebuild (fmt-types-09b): a dark, cinematic vessel with real-shaped red cells.
Runs inside Blender:

    blender -b --factory-startup -t 4 --python render/blood_scene.py -- '<json spec>'

What's built (nothing comes from the atlas):
  red cells     biconcave discs (Evans and Fung's measured shape), deep red with subsurface glow and a wet coat
  antigens      ball-and-stick sugar chains standing on the membrane: the H chain every type has (a blue GlcNAc
                cube, a gold galactose ball, a red fucose branch), capped by one more sugar: A = a lime cube
                (N-acetylgalactosamine), B = a coral ball (galactose); O cells keep the bare H chain
  Rh (D)        a lumpy blue protein half sunk in the membrane
  antibodies    IgM pentamers (five Y-shaped units, ten arms: anti-A and anti-B are mostly IgM) as organic
                blobs, tinted the colour of the sugar they grab
  vessel        the inside of a vessel: an endothelial wall with elongated cell tiles, warm haze, drifting
                plasma specks, depth of field and bloom

spec: {"out": dir, "width", "height", "samples", "shots": [{"name", "kind": "hook" | "cell", "type": "A+" ...}]}
Writes <out>/<name>.png and <out>/<name>.json (label pins in pixels).
"""

import bisect
import time
import itertools
import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

spec = json.loads(sys.argv[sys.argv.index("--") + 1])
OUT = Path(spec["out"])
scene = bpy.context.scene
W, H = spec.get("width", 1080), spec.get("height", 1920)

# --- materials ------------------------------------------------------------------------------------------------
MATS = {}


def principled(name, rgb, rough=0.4, sss=0.0, sss_radius=(1, 0.2, 0.1), sss_scale=0.2, coat=0.0, emit=None,
               emit_strength=0.0, alpha=1.0, sheen=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    if sss:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = sss_radius
        b.inputs["Subsurface Scale"].default_value = sss_scale
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.15
    if sheen:
        b.inputs["Sheen Weight"].default_value = sheen
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = emit_strength
    if alpha < 1:
        b.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "BLENDED"
    MATS[name] = m
    return m


principled("cell", (0.36, 0.008, 0.012), rough=0.32, sss=0.85, sss_radius=(1.0, 0.12, 0.06), sss_scale=0.35,
           coat=0.45, emit=(0.5, 0.01, 0.01), emit_strength=0.08)
principled("glcnac", (0.78, 0.8, 0.86), rough=0.3, emit=(0.78, 0.8, 0.86), emit_strength=0.2)  # not blue: blue is Rh
principled("gal", (0.95, 0.72, 0.12), rough=0.3, emit=(0.95, 0.72, 0.12), emit_strength=0.4)
principled("fuc", (0.9, 0.08, 0.06), rough=0.3, emit=(0.9, 0.08, 0.06), emit_strength=0.3)
principled("tipA", (0.52, 0.95, 0.1), rough=0.25, emit=(0.52, 0.95, 0.1), emit_strength=2.2)
principled("tipB", (1.0, 0.36, 0.42), rough=0.25, emit=(1.0, 0.36, 0.42), emit_strength=2.2)
principled("stick", (0.85, 0.85, 0.88), rough=0.4, emit=(0.8, 0.8, 0.85), emit_strength=0.3)
principled("rh", (0.1, 0.32, 1.0), rough=0.45, sss=0.4, sss_radius=(0.2, 0.4, 1.0), sss_scale=0.05,
           emit=(0.1, 0.35, 1.0), emit_strength=0.9)
principled("igmA", (0.35, 0.75, 0.12), rough=0.35, sss=0.5, sss_radius=(0.6, 1, 0.5), sss_scale=0.05,
           emit=(0.45, 0.85, 0.2), emit_strength=0.35)
principled("igmB", (0.9, 0.3, 0.36), rough=0.35, sss=0.5, sss_radius=(1, 0.6, 0.6), sss_scale=0.05,
           emit=(0.9, 0.35, 0.4), emit_strength=0.35)
principled("speck", (1.0, 0.75, 0.6), rough=0.5, emit=(1.0, 0.55, 0.4), emit_strength=6.0)


def wall_material():
    """Endothelium: pink-red tissue with elongated cell tiles (Voronoi stretched along the flow)."""
    m = principled("wall", (0.16, 0.012, 0.018), rough=0.45, sss=0.6, sss_radius=(1, 0.2, 0.1), sss_scale=0.6,
                   coat=0.3, emit=(0.25, 0.01, 0.01), emit_strength=0.02)
    nt = m.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.4, 1.4, 0.35)  # tiles stretched along the vessel (z)
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = 1.2
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Max"].default_value = 0.08
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], vor.inputs["Vector"])
    nt.links.new(vor.outputs["Distance"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])
    return m


wall_material()

# --- geometry helpers -----------------------------------------------------------------------------------------
C0, C2, C4, R_UM = 0.81, 7.83, -4.39, 3.91  # Evans and Fung (1972), micrometres


def half_thick(rho):
    return 0.5 * math.sqrt(max(0.0, 1 - rho * rho)) * (C0 + C2 * rho ** 2 + C4 * rho ** 4) / R_UM


def rbc_mesh(name, seg=72, steps=28):
    """A red cell of radius 1, axis z: the profile revolved, denser toward the rim."""
    prof = []
    for i in range(steps + 1):  # top, centre to rim
        rho = math.sin(i / steps * math.pi / 2)
        prof.append((rho, half_thick(rho)))
    prof += [(r, -z) for r, z in reversed(prof[:-1])]  # bottom, rim back to centre
    verts, faces = [], []
    n = len(prof)
    for j in range(seg):
        a = 2 * math.pi * j / seg
        for r, z in prof:
            verts.append((r * math.cos(a), r * math.sin(a), z))
    for j in range(seg):
        k = (j + 1) % seg
        for i in range(n - 1):
            faces.append((j * n + i, k * n + i, k * n + i + 1, j * n + i + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return me


CELL_ME = rbc_mesh("rbc")


def surface_points(me, n, rng, rim_bias=0.0):
    """n random points on a mesh (area-weighted), with their face normals."""
    polys = list(me.polygons)
    cum = list(itertools.accumulate(p.area * (1 + rim_bias * math.hypot(*p.center[:2])) for p in polys))
    out = []
    for _ in range(n):
        p = polys[min(len(polys) - 1, bisect.bisect(cum, rng.random() * cum[-1]))]
        vs = [me.vertices[v].co for v in p.vertices]
        a, b = rng.random(), rng.random()
        if a + b > 1:
            a, b = 1 - a, 1 - b
        co = vs[0] + (vs[1] - vs[0]) * a + (vs[2] - vs[0]) * b
        out.append((co, p.normal.copy()))
    return out


def frame_to(co, normal, spin):
    q = normal.to_track_quat("Z", "Y")
    return Matrix.Translation(co) @ q.to_matrix().to_4x4() @ Matrix.Rotation(spin, 4, "Z")


def bm_sphere(bm, m, r, mat, sub=1):
    res = bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r, matrix=m)
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat
        f.smooth = True


def bm_cube(bm, m, s, mat):
    res = bmesh.ops.create_cube(bm, size=s, matrix=m)
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat


def bm_cone(bm, m, r, mat):  # fucose: a small triangle-ish pyramid, as in the symbol nomenclature for glycans
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=3, radius1=r, radius2=0, depth=r * 1.6, matrix=m)
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat


def bm_stick(bm, a, b, r, mat):
    d = b - a
    m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    res = bmesh.ops.create_cone(bm, cap_ends=False, segments=6, radius1=r, radius2=r, depth=d.length, matrix=m)
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat
        f.smooth = True


SLOTS = ["glcnac", "gal", "fuc", "tipA", "tipB", "stick", "rh"]
GLC, GAL, FUC, TIPA, TIPB, STK, RH = range(7)


def chain(bm, m, s, tip):
    """One antigen: GlcNAc (cube) - Gal (ball) with a fucose branch, then the A or B sugar (or nothing: O)."""
    p = [Vector((0, 0, 0)), Vector((0, 0, 1.0)), Vector((0, 0, 2.0)), Vector((0.75, 0, 2.55)), Vector((-0.6, 0, 2.9))]
    p = [m @ (v * s) for v in p]
    for a, b in [(p[0], p[1]), (p[1], p[2]), (p[2], p[3])] + ([(p[2], p[4])] if tip else []):
        bm_stick(bm, a, b, 0.09 * s, STK)
    rot = m.to_3x3().to_4x4()
    bm_cube(bm, Matrix.Translation(p[1]) @ rot, 0.62 * s, GLC)
    bm_sphere(bm, Matrix.Translation(p[2]) @ rot, 0.36 * s, GAL)
    bm_cone(bm, Matrix.Translation(p[3]) @ rot, 0.34 * s, FUC)
    if tip == "A":
        bm_cube(bm, Matrix.Translation(p[4]) @ rot, 0.62 * s, TIPA)
    elif tip == "B":
        bm_sphere(bm, Matrix.Translation(p[4]) @ rot, 0.38 * s, TIPB, sub=2)


def rh_blob(bm, m, s, rng):
    res = bmesh.ops.create_icosphere(bm, subdivisions=3, radius=s, matrix=m)
    for v in res["verts"]:
        d = v.co - m.translation
        k = 1 + 0.22 * math.sin(d.x * 9 / s + rng.random()) * math.sin(d.y * 7 / s) + 0.12 * math.sin(d.z * 13 / s)
        v.co = m.translation + d * k
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = RH
        f.smooth = True


def link(obj):
    scene.collection.objects.link(obj)
    return obj


def red_cell(name, mat_world, ctype, rng, n_antigens=220, sugar=0.022):
    """A red cell of blood type ctype ("A+", "O-"...), with its markers as one mesh riding on it."""
    cell = link(bpy.data.objects.new(name, CELL_ME))
    cell.data.materials.append(MATS["cell"]) if not cell.data.materials else None
    cell.matrix_world = mat_world
    marks = {"sugar": [], "rh": []}
    if n_antigens <= 0:
        return cell, marks
    tips = [t for t in ("A", "B") if t in ctype.rstrip("+-").replace("O", "")]
    bm = bmesh.new()
    rot = mat_world.to_3x3()
    for co, nrm in surface_points(CELL_ME, n_antigens, rng, rim_bias=0.6):
        tip = rng.choice(tips) if tips else None
        s = sugar * (0.85 + 0.3 * rng.random())
        chain(bm, frame_to(co, nrm, rng.random() * 6.28), s, tip)
        marks["sugar"].append((mat_world @ (co + nrm * s * 2.6), (rot @ nrm).normalized()))
    if ctype.endswith("+"):
        for co, nrm in surface_points(CELL_ME, max(6, n_antigens // 14), rng, rim_bias=0.4):
            rh_blob(bm, frame_to(co - nrm * 0.01, nrm, rng.random() * 6.28), 0.045, rng)
            marks["rh"].append((mat_world @ (co + nrm * 0.03), (rot @ nrm).normalized()))
    me = bpy.data.meshes.new(name + " markers")
    bm.to_mesh(me)
    bm.free()
    for s in SLOTS:
        me.materials.append(MATS[s])
    mk = link(bpy.data.objects.new(name + " markers", me))
    mk.matrix_world = mat_world
    return cell, marks


def igm(name, m, s, mat):
    """An IgM pentamer: five Y units, Fc toward the centre, two Fab arms each pointing out (ten binding sites)."""
    mb = bpy.data.metaballs.new(name)
    mb.resolution = 0.011 * s
    mb.render_resolution = mb.resolution
    mb.threshold = 0.6
    for k in range(5):
        a = 2 * math.pi * k / 5
        out = Vector((math.cos(a), math.sin(a), 0))
        side = Vector((-math.sin(a), math.cos(a), 0))
        for d, r in [(0.16, 0.095), (0.27, 0.1), (0.38, 0.1)]:  # Fc domains (CH4, CH3, CH2), paired chains
            for o in (-1, 1):
                el = mb.elements.new()
                el.co = (out * d + side * o * 0.035) * s
                el.radius = r * s
                el.stiffness = 2.2
        hinge = out * 0.46
        for o in (-1, 1):  # the two Fab arms, opening like a Y
            arm = (out * math.cos(0.75) + side * o * math.sin(0.75)).normalized()
            for d in (0.10, 0.22, 0.32):
                for lo in (-1, 1):  # heavy and light chain side by side
                    el = mb.elements.new()
                    el.co = (hinge + arm * d + Vector((0, 0, lo * 0.035))) * s
                    el.radius = 0.085 * s
                    el.stiffness = 2.0
    el = mb.elements.new()  # the J chain
    el.co = (0.0, 0.0, 0.03 * s)
    el.radius = 0.09 * s
    o = link(bpy.data.objects.new(name, mb))
    o.matrix_world = m
    mb.materials.append(MATS[mat])
    return o


def vessel(radius=7.0, length=80.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=radius, depth=length, end_fill_type="NOTHING",
                                        location=(0, 0, -length / 2 + 6))
    o = bpy.context.active_object
    o.name = "vessel"
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 1],
                              cuts=40, use_grid_fill=True)
    rng = random.Random(9)
    for v in bm.verts:  # gentle folds in the wall
        r = Vector((v.co.x, v.co.y, 0))
        k = 1 + 0.05 * math.sin(v.co.z * 0.5 + math.atan2(v.co.y, v.co.x) * 3) + 0.02 * rng.random()
        v.co.x, v.co.y = r.x * k, r.y * k
    bm.to_mesh(o.data)
    bm.free()
    for p in o.data.polygons:
        p.use_smooth = True
    o.data.materials.append(MATS["wall"])
    return o


def specks(n, rng, box):
    bm = bmesh.new()
    for _ in range(n):
        c = Vector([rng.uniform(lo, hi) for lo, hi in box])
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=rng.uniform(0.02, 0.06), matrix=Matrix.Translation(c))
    me = bpy.data.meshes.new("specks")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(MATS["speck"])
    return link(bpy.data.objects.new("specks", me))


def rand_rot(rng):
    return (Matrix.Rotation(rng.uniform(0, 6.28), 4, "Z") @ Matrix.Rotation(rng.uniform(0, 6.28), 4, "X")
            @ Matrix.Rotation(rng.uniform(0, 6.28), 4, "Y"))


# --- stage -----------------------------------------------------------------------------------------------------
def light(name, kind, loc, target, power, size=1.0, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, kind)
    ld.energy, ld.color = power, color
    if kind == "AREA":
        ld.size = size
    else:
        ld.shadow_soft_size = size
    o = link(bpy.data.objects.new(name, ld))
    o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return o


def setup(samples):
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y = W, H
    scene.eevee.taa_render_samples = samples
    scene.eevee.volumetric_samples = 48
    scene.eevee.volumetric_end = 60
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
    scene.view_settings.exposure = spec.get("exposure", -0.6)
    w = bpy.data.worlds.new("world")
    scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes["Background"].inputs[0].default_value = (0.02, 0.0, 0.002, 1)
    nt.nodes["Background"].inputs[1].default_value = 1.0
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")  # warm plasma haze, so depth reads
    vol.inputs["Color"].default_value = (1.0, 0.35, 0.25, 1)
    vol.inputs["Density"].default_value = spec.get("haze", 0.004)
    vol.inputs["Anisotropy"].default_value = 0.5
    nt.links.new(vol.outputs["Volume"], nt.nodes["World Output"].inputs["Volume"])
    # bloom and a soft vignette in the compositor
    scene.use_nodes = True
    ct = scene.node_tree
    for n in list(ct.nodes):
        ct.nodes.remove(n)
    rl = ct.nodes.new("CompositorNodeRLayers")
    glare = ct.nodes.new("CompositorNodeGlare")
    try:
        glare.glare_type = "BLOOM"
    except TypeError:
        glare.glare_type = "FOG_GLOW"
    glare.quality = "HIGH"
    glare.threshold = 0.75
    glare.size = 8
    glare.mix = -0.55
    comp = ct.nodes.new("CompositorNodeComposite")
    ct.links.new(rl.outputs["Image"], glare.inputs["Image"])
    ct.links.new(glare.outputs["Image"], comp.inputs["Image"])


def camera(loc, target, lens, focus, fstop):
    cam = link(bpy.data.objects.new("cam", bpy.data.cameras.new("cam")))
    scene.camera = cam
    cam.data.lens = lens
    cam.data.sensor_fit = "VERTICAL"
    cam.data.sensor_height = 24
    cam.data.clip_start = 0.01
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.dof.use_dof = True
    cam.data.dof.focus_distance = focus
    cam.data.dof.aperture_fstop = fstop
    cam.data.dof.aperture_blades = 7
    return cam


def px(cam, co):
    p = world_to_camera_view(scene, cam, Vector(co))
    return [round(p.x * W, 1), round((1 - p.y) * H, 1)]


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


# --- shots -----------------------------------------------------------------------------------------------------
# Each shot builds its set once and returns update(u) for u in [0, 1] across the shot: it moves the camera, cells,
# antibodies and plasma specks, and returns the label pins in pixels for that frame. A still is update(0.5).
def ease(u):
    return u * u * (3 - 2 * u)


def orbit_cam(target, base_dir, deg, dist, lens, fstop, roll_up=Vector((0, 0, 1))):
    """A camera dist from target along base_dir turned deg degrees about the vertical axis (z)."""
    d = Matrix.Rotation(math.radians(deg), 3, "Z") @ Vector(base_dir).normalized()
    return target + d * dist


def set_glow(mode):
    """Which markers light up: "A", "B", "AB" (both sugars), "Rh", "sugar" (the bare chains), "all", "none"."""
    em = lambda n, v: MATS[n].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].__setattr__(  # noqa: E731
        "default_value", v)
    em("tipA", 4.0 if mode in ("A", "AB", "all") else 1.2)
    em("tipB", 4.0 if mode in ("B", "AB", "all") else 1.2)
    em("rh", 3.5 if mode in ("Rh", "all") else 0.6)
    for n in ("glcnac", "gal", "fuc"):
        em(n, 1.6 if mode == "sugar" else 0.35)


def shot_hook(sh):
    """Inside a vessel, looking downstream: donor A cells pulled into a clump by the patient's anti-A IgM, which
    converge on them; the patient's own cells drift past untouched. Clumped cells darken."""
    rng = random.Random(sh.get("seed", 4))
    set_glow("A")
    vessel()
    focus = Vector((0.4, 0.0, -10.0))
    clumped = MATS["cell"].copy()
    clumped.name = "cell clumped"
    cb = clumped.node_tree.nodes["Principled BSDF"]
    cells, abs_ = [], []
    for i in range(sh.get("clump", 13)):
        a = rng.uniform(0, 6.28)
        r = rng.uniform(0.0, 2.1) * (0.4 + 0.6 * i / 13)
        end = focus + Vector((r * math.cos(a), r * math.sin(a) * 0.9, rng.uniform(-1.6, 1.6)))
        start = focus + (end - focus) * 2.4 + Vector((0, 0, rng.uniform(1.5, 4.0)))
        rot = rand_rot(rng)
        cell, _ = red_cell(f"clump {i}", Matrix.Translation(end) @ rot, "A+", rng, n_antigens=140, sugar=0.02)
        cell.data = cell.data.copy()
        cell.data.materials.clear()
        cell.data.materials.append(clumped)
        cells.append((cell, bpy.data.objects[f"clump {i} markers"], start, end, rot, rng.uniform(-0.4, 0.4)))
    ends = [c[3] for c in cells]
    for i in range(sh.get("bridges", 16)):
        a, b = rng.sample(ends, 2)
        mid = (a + b) / 2 + Vector([rng.uniform(-0.3, 0.3) for _ in range(3)])
        start = mid + Vector([rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(2, 6)])
        rot = rand_rot(rng)
        abs_.append((igm(f"igm {i}", Matrix.Translation(start) @ rot, rng.uniform(0.55, 0.7), "igmA"), start, mid, rot,
                     rng.uniform(0.15, 0.45)))
    free = []
    for i in range(sh.get("free", 46)):
        z = rng.uniform(-32, 3.5)
        rad = rng.uniform(1.2, 6.0)
        a = rng.uniform(0, 6.28)
        c = Vector((rad * math.cos(a), rad * math.sin(a), z))
        if (c - focus).length < 3.3:
            continue
        rot = rand_rot(rng)
        o, _ = red_cell(f"free {i}", Matrix.Translation(c) @ rot, "B+", rng, n_antigens=0)
        free.append((o, c, rot, rng.uniform(0.6, 1.4)))
    sp = specks(260, rng, [(-6, 6), (-6, 6), (-34, 5)])
    eye0 = Vector((0.0, -0.4, 7.5))
    cam = camera(eye0, focus + Vector((0, 0.3, 0)), 32, (focus - eye0).length, sh.get("fstop", 0.6))
    light("rim", "AREA", (0, 4, -24), focus, 7000, 10, (1.0, 0.45, 0.3))
    light("key", "AREA", (-3, -4, -3), focus, 1400, 3, (1.0, 0.85, 0.8))
    light("glow", "POINT", tuple(focus + Vector((0, 0, -1.5))), focus, 500, 1.5, (1.0, 0.3, 0.2))
    light("fill", "AREA", (5, 3, -6), focus, 300, 6, (0.6, 0.7, 1.0))
    T = sh.get("seconds", 6.0)
    base = (0.36, 0.008, 0.012)

    def update(u):
        # the clump is already forming at frame 0 (the hook needs it in the first second) and tightens by ~60%
        k = ease(min(1.0, 0.35 + u / 0.6 * 0.65))
        for cell, mk, start, end, rot, spin in cells:
            m = Matrix.Translation(start.lerp(end, k)) @ rot @ Matrix.Rotation(spin * (1 - k), 4, "Z")
            cell.matrix_world = m
            mk.matrix_world = m
        for ab, start, mid, rot, lag in abs_:
            kk = ease(min(1.0, max(0.0, (0.35 + u * 1.1 - lag) / 0.7)))
            ab.matrix_world = Matrix.Translation(start.lerp(mid, kk)) @ rot @ Matrix.Rotation(u * 1.5, 4, "Y")
        dark = ease(min(1.0, max(0.0, (u - 0.35) / 0.65)))  # agglutinated cells darken (they're being destroyed)
        cb.inputs["Base Color"].default_value = (*(b * (1 - 0.55 * dark) for b in base), 1)
        for o, c, rot, speed in free:  # the patient's own cells flow on past
            o.matrix_world = Matrix.Translation(c + Vector((0, 0, u * T * speed))) @ rot @ Matrix.Rotation(u * speed, 4, "X")
        sp.location = (0, 0, u * T * 0.8)
        eye = eye0.lerp(Vector((0.3, -0.2, 4.2)), ease(u))
        cam.location = eye
        cam.rotation_euler = (focus + Vector((0, 0.3, 0)) - eye).to_track_quat("-Z", "Y").to_euler()
        cam.data.dof.focus_distance = (focus - eye).length
        return {"clump": px(cam, focus + Vector((0.5, 0.2, 0.8)))}

    return update


def cell_set(sh, ctype, n_antigens, sugar, hero_at, hero_rot, bg_type=None):
    rng = random.Random(sh.get("seed", 7))
    vessel(radius=9.0, length=90)
    m = Matrix.Translation(hero_at) @ hero_rot
    hero, marks = red_cell("hero", m, ctype, rng, n_antigens=n_antigens, sugar=sugar)
    bg = []
    for i in range(16):
        c = Vector((rng.uniform(-7, 7), rng.uniform(-7, 7), rng.uniform(-40, -14)))
        rot = rand_rot(rng)
        o, _ = red_cell(f"bg {i}", Matrix.Translation(c) @ rot, bg_type or ctype, rng, n_antigens=0)
        bg.append((o, c, rot))
    sp = specks(160, rng, [(-5, 5), (-5, 5), (-30, 0)])
    return rng, hero, marks, bg, sp


def pick_mark(marks, eye, cam, want, kinds):
    best = None
    for k in kinds:
        for w, n in marks[k]:
            if n.dot((eye - w).normalized()) < 0.35:
                continue
            d = math.dist(px(cam, w), want)
            if best is None or d < best[0]:
                best = (d, w)
    return best[1] if best else None


def shot_cell(sh):
    """One cell, whole, slowly orbited: its sugar chains and Rh proteins; sh["glow"] lights the marker in question."""
    ctype = sh.get("type", "A+")
    set_glow(sh.get("glow", "none"))
    target = Vector((0.0, 0.0, -6.15))
    rng, hero, marks, bg, sp = cell_set(sh, ctype, sh.get("antigens", 1300), 0.018, Vector((0, 0, -6)),
                                        Matrix.Rotation(math.radians(90), 4, "X"))
    base = Vector((0.0, -0.6, 0.8))
    dist = 5.0 * sh.get("close", 1.0)
    a0, a1 = sh.get("orbit", [-10, 10])
    eye = orbit_cam(target, base, a0, dist, 35, 1.8)
    cam = camera(eye, target, 35, dist, sh.get("fstop", 1.8))
    light("rim", "AREA", (0.3, 2.5, -10), target, 2600, 3, (1.0, 0.5, 0.35))
    light("key", "AREA", (-2.5, -3, -3), target, 500, 2, (1.0, 0.92, 0.88))
    light("fill", "AREA", (3, -1, -6), target, 200, 3, (0.6, 0.75, 1.0))
    kinds = ["rh"] if sh.get("glow") == "Rh" else ["sugar"]
    mid_eye = orbit_cam(target, base, (a0 + a1) / 2, dist * 0.94, 35, 1.8)
    cam.location = mid_eye
    cam.rotation_euler = (target - mid_eye).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()
    pin_at = pick_mark(marks, mid_eye, cam, (0.42 * W, 0.48 * H), kinds) or target
    T = sh.get("seconds", 3.0)

    def update(u):
        e = orbit_cam(target, base, a0 + (a1 - a0) * ease(u), dist * (1 - 0.06 * ease(u)), 35, 1.8)
        cam.location = e
        cam.rotation_euler = (target - e).to_track_quat("-Z", "Y").to_euler()
        cam.data.dof.focus_distance = (target - e).length
        for o, c, rot in bg:
            o.matrix_world = Matrix.Translation(c + Vector((0, 0, u * T * 0.6))) @ rot
        sp.location = (0, 0, u * T * 0.5)
        return {"sugar": px(cam, pin_at), "rh": px(cam, pin_at), "hero": px(cam, target)}

    return update


def shot_plasma(sh):
    """The plasma beside a cell: IgM antibodies drifting free (anti-B tinted coral, anti-A lime). They never touch a
    cell carrying their target is never in the shot; with no antibodies (AB plasma), cells of every type pass by."""
    ctype = sh.get("type", "A-")
    set_glow("none")
    rng, hero, marks, bg, sp = cell_set(sh, ctype, 900, 0.018, Vector((-1.6, 1.2, -9.5)),
                                        Matrix.Rotation(math.radians(70), 4, "X") @ Matrix.Rotation(0.4, 4, "Y"))
    target = Vector((0.2, 0.0, -6.2))
    crowd = []
    if sh.get("crowd"):  # cells of every type passing through: AB plasma meets all of them
        for i in range(14):
            c = Vector((rng.uniform(-3.5, 3.5), rng.uniform(-1.5, 3.0), rng.uniform(-14, 2)))
            rot = rand_rot(rng)
            o, _ = red_cell(f"pass {i}", Matrix.Translation(c) @ rot, rng.choice(["A+", "B+", "O+", "AB+"]), rng,
                            n_antigens=0)
            crowd.append((o, c, rot))
    abs_ = []
    for i, kind in enumerate(sh.get("antibodies", [])):
        c = target + Vector((rng.uniform(-0.9, 1.1), rng.uniform(-0.6, 0.6), rng.uniform(-0.9, 1.3)))
        abs_.append((igm(f"ab{i}", Matrix.Translation(c), 0.42 if i == 0 else 0.34, "igmB" if kind == "B" else "igmA"),
                     c, rand_rot(rng), Vector([rng.uniform(-0.25, 0.25) for _ in range(3)]), rng.uniform(0.3, 0.8)))
    base = Vector((0.15, -0.6, 0.75))
    a0, a1 = sh.get("orbit", [-6, 6])
    eye = orbit_cam(target, base, a0, 4.2, 35, 2.2)
    cam = camera(eye, target, 35, 4.2, sh.get("fstop", 2.2))
    light("rim", "AREA", (0.3, 2.5, -12), target, 2600, 3, (1.0, 0.5, 0.35))
    light("key", "AREA", (-2.5, -3, -3), target, 600, 2, (1.0, 0.92, 0.88))
    light("fill", "AREA", (3, -1, -6), target, 250, 3, (0.6, 0.75, 1.0))
    T = sh.get("seconds", 3.0)

    def update(u):
        e = orbit_cam(target, base, a0 + (a1 - a0) * ease(u), 4.2 * (1 - 0.05 * ease(u)), 35, 2.2)
        cam.location = e
        cam.rotation_euler = (target - e).to_track_quat("-Z", "Y").to_euler()
        for ab, c, rot, drift, spin in abs_:
            ab.matrix_world = Matrix.Translation(c + drift * u * T) @ rot @ Matrix.Rotation(u * spin * T, 4, "Z")
        for o, c, rot in bg:
            o.matrix_world = Matrix.Translation(c + Vector((0, 0, u * T * 0.6))) @ rot
        for o, c, rot in crowd:
            o.matrix_world = Matrix.Translation(c + Vector((0, 0, u * T * 1.2))) @ rot @ Matrix.Rotation(u * 1.5, 4, "X")
        sp.location = (0, 0, u * T * 0.5)
        pins = {"plasma": px(cam, target + Vector((0.3, 0.1, 0.2))), "hero": px(cam, Vector((-1.6, 1.2, -9.5)))}
        if abs_:  # the label goes on an antibody that's on screen and well clear of the cell (never looks bound)
            hero_px = pins["hero"]
            seen = [px(cam, a[0].matrix_world.translation) for a in abs_]
            inside = [p for p in seen if 150 < p[0] < W - 180 and 0.22 * H < p[1] < 0.66 * H] or seen
            pins["antibody"] = max(inside, key=lambda p: math.dist(p, hero_px))
        return pins

    return update


def shot_donor(sh):
    """An O negative cell (no A, no B, no Rh) sailing through a crowd of every type, past antibodies of both kinds,
    and nothing grabs it; the camera rides along beside it."""
    rng = random.Random(sh.get("seed", 11))
    set_glow("sugar")
    vessel(radius=8.0, length=120)
    hero, _ = red_cell("hero", Matrix.Rotation(math.radians(80), 4, "X"), "O-", rng, n_antigens=700, sugar=0.02)
    hmk = bpy.data.objects["hero markers"]
    crowd = []
    for i in range(40):
        c = Vector((rng.uniform(-6, 6), rng.uniform(-6, 6), rng.uniform(-60, 10)))
        if abs(c.x) < 1.8 and abs(c.y) < 1.8:
            c.x += 3.0 * (1 if c.x >= 0 else -1)
        rot = rand_rot(rng)
        o, _ = red_cell(f"crowd {i}", Matrix.Translation(c) @ rot, rng.choice(["A+", "B+", "AB+", "O+"]), rng,
                        n_antigens=0)
        crowd.append((o, c, rot))
    abs_ = []
    for i in range(8):
        c = Vector((rng.choice([-1, 1]) * rng.uniform(1.6, 3.5), rng.uniform(-2.5, 2.5), rng.uniform(-40, 4)))
        abs_.append((igm(f"free ab {i}", Matrix.Translation(c), 0.6, "igmA" if i % 2 else "igmB"), c, rand_rot(rng)))
    sp = specks(300, rng, [(-6, 6), (-6, 6), (-60, 10)])
    T = sh.get("seconds", 4.0)
    z0, z1 = 0.0, -T * 2.2
    cam = camera(Vector((0, -7.5, 2.4)), Vector((0, 0, 0)), 35, 7.9, sh.get("fstop", 2.8))
    light("rim", "AREA", (0, 4, -14), (0, 0, -10), 5000, 8, (1.0, 0.45, 0.3))
    light("key", "AREA", (-3, -4, 2), (0, 0, -6), 1200, 3, (1.0, 0.88, 0.82))

    def update(u):
        z = z0 + (z1 - z0) * u
        m = Matrix.Translation((0, 0, z)) @ Matrix.Rotation(math.radians(80), 4, "X") @ Matrix.Rotation(u * 1.2, 4, "Z")
        hero.matrix_world = m
        hmk.matrix_world = m
        for o, c, rot in crowd:
            o.matrix_world = Matrix.Translation(c + Vector((0, 0, -u * T * 0.8))) @ rot
        for ab, c, rot in abs_:
            ab.matrix_world = Matrix.Translation(c) @ rot @ Matrix.Rotation(u * 2, 4, "Y")
        e = Vector((1.2 * math.sin(u * 1.5), -7.5, z + 2.4))
        cam.location = e
        cam.rotation_euler = (Vector((0, 0, z - 0.6)) - e).to_track_quat("-Z", "Y").to_euler()
        cam.data.dof.focus_distance = (Vector((0, 0, z)) - e).length
        return {"hero": px(cam, Vector((0, 0, z)))}

    return update


SHOTS = {"hook": shot_hook, "cell": shot_cell, "plasma": shot_plasma, "donor": shot_donor}

OUT.mkdir(parents=True, exist_ok=True)
setup(spec.get("samples", 64))
for sh in spec["shots"]:
    if spec.get("only") and sh["name"] not in spec["only"]:
        continue
    clear()
    update = SHOTS[sh["kind"]](sh)
    n = sh.get("frames")
    if not n:  # a still
        pins = update(sh.get("u", 0.5))
        scene.render.filepath = str(OUT / f"{sh['name']}.png")
        bpy.ops.render.render(write_still=True)
        (OUT / f"{sh['name']}.json").write_text(json.dumps({"pins": pins}))
        print("SHOT", sh["name"], pins, flush=True)
        continue
    d = OUT / sh["name"]
    d.mkdir(exist_ok=True)
    allpins = []
    t0 = time.time()
    for f in range(n):
        pins = update(f / max(1, n - 1))
        allpins.append(pins)
        if (d / f"{f:05d}.png").exists() and not spec.get("redo"):  # resume after a stop
            continue
        if f % spec.get("step", 1):  # previews: every few frames only (the builder holds the last one)
            continue
        scene.render.filepath = str(d / f"{f:05d}.png")
        bpy.ops.render.render(write_still=True)
        if f % 30 == 0:
            print("FRAME", sh["name"], f, n, round((time.time() - t0) / (f + 1), 1), "s/frame", flush=True)
    (d / "pins.json").write_text(json.dumps(allpins))
    print("SHOT", sh["name"], n, "frames", flush=True)
