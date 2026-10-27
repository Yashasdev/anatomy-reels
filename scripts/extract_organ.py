"""Pull named parts out of the Z-Anatomy atlas into small model files (assets/models/<name>.blend).

    blender -b Z-Anatomy/Startup.blend --python scripts/extract_organ.py

Each part keeps its true position (parents, modifiers and constraints from the atlas are baked in or dropped).
Never add the parts Z-Anatomy marks non-commercial (the inner ear models and the Lissie Cowley kidney).
"""
import os
import sys

import bpy

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "models")
MODELS = {
    "lungs": ["Superior lobe of right lung", "Middle lobe of right lung", "Inferior lobe of right lung",
              "Superior lobe of left lung", "Inferior lobe of left lung", "Trachea"],
    "skull": ["Frontal bone", "Parietal bone.l", "Parietal bone.r", "Occipital bone", "Temporal bone.l",
              "Temporal bone.r", "Sphenoid bone", "Zygomatic bone.l", "Zygomatic bone.r", "Maxilla.l", "Maxilla.r",
              "Nasal bone.l", "Nasal bone.r", "Mandible", "Vomer", "Ethmoid bone", "Lacrimal bone.l", "Lacrimal bone.r",
              "Palatine bone.l", "Palatine bone.r", "Inferior nasal concha bone.l", "Inferior nasal concha bone.r"],
    "abdomen": ["Liver", "Gallbladder", "Stomach", "Pancreas", "Spleen", "Duodenum", "Ascending colon",
                "Transverse colon", "Descending colon", "Sigmoid colon"],
    "arm": ["Clavicle.r", "Scapula.r", "Humerus.r", "Radius.r", "Ulna.r"],
}

bpy.context.view_layer.update()
for name, wanted in MODELS.items():
    keep = []
    for n in wanted:
        o = bpy.data.objects.get(n)
        if o is None or o.type != "MESH":
            sys.stderr.write("MISSING %s/%s\n" % (name, n))
            continue
        keep.append(o)
    for o in keep:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        o.constraints.clear()
        o.modifiers.clear()
    bpy.data.libraries.write(os.path.join(OUT, name + ".blend"), set(keep) | {o.data for o in keep},
                             fake_user=True, compress=True)
    sys.stderr.write("SAVED %s %d parts\n" % (name, len(keep)))
