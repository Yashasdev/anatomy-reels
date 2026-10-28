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

# larger regions, picked by name pattern (right side unless both sides read better); never ligaments or markers
PATTERNS = {
    "leg": r"^(Femur|Patella|Tibia|Fibula|Talus|Calcaneus|Navicular bone|Cuboid bone|(Medial|Intermediate|Lateral) cuneiform bone|(First|Second|Third|Fourth|Fifth) metatarsal bone|(Proximal|Middle|Distal) phalanx of \w+ finger of foot)\.r$",
    "pelvis": r"^(Hip bone\.[lr]|Sacrum|Coccyx|Vertebra L5)$",
    "spine": r"^(Atlas \(C1\)|Axis \(C2\)|Vertebra [CTL]\d+|Sacrum|Coccyx)$",
    "chest": r"^(Manubrium of sternum|Body of sternum|Xiphoid process|(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth) rib\.[lr]|Costal cartilage of \w+ rib\.[lr])$",
    "hand": r"^((Scaphoid|Lunate|Triquetrum|Pisiform|Trapezium|Trapezoid|Capitate|Hamate) bone|(First|Second|Third|Fourth|Fifth) metacarpal bone|(Proximal|Middle|Distal) phalanx of \w+ finger of hand)\.r$",
    "eye": r"^(Sclera|Cornea|Iris|Lens|(Superior|Inferior|Medial|Lateral) rectus muscle|(Superior|Inferior) oblique muscle)\.r$",
    "thigh": r"^((Gluteus maximus|Gluteus medius|Rectus femoris|Vastus lateralis|Vastus medialis|Sartorius|Gracilis|Semimembranosus|Semitendinosus|Soleus|Tibialis anterior) muscle|Adductor longus|Tensor fasciae latae|Femur|Patella|Tibia|Fibula|Hip bone)\.r$",
    "teeth": r"^(Upper|Lower) (medial incisor|lateral incisor|canine|first premolar|second premolar|first molar tooth|second molar tooth)\.[lr]$",
}
import re
for name, pat in PATTERNS.items():
    MODELS[name] = sorted(o.name for o in bpy.data.objects if o.type == "MESH" and re.match(pat, o.name)
                          and max(o.dimensions) > 0.005)

only = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
bpy.context.view_layer.update()
for name, wanted in MODELS.items():
    if only and name not in only:
        continue
    keep = []
    for n in wanted:
        o = bpy.data.objects.get(n)
        if o is None or o.type != "MESH":
            sys.stderr.write("MISSING %s/%s\n" % (name, n))
            continue
        keep.append(o)
    for o in keep:
        # bake the full world transform into the mesh: some atlas parts carry a hidden delta scale (x10) that a
        # plain copy of the object transform loses, shrinking them to a tenth of their size
        mw = o.matrix_world.copy()
        o.parent = None
        o.constraints.clear()
        o.modifiers.clear()
        o.data = o.data.copy()
        o.data.transform(mw)
        o.delta_location, o.delta_rotation_euler, o.delta_scale = (0, 0, 0), (0, 0, 0), (1, 1, 1)
        o.matrix_world = mw.Identity(4)
    bpy.data.libraries.write(os.path.join(OUT, name + ".blend"), set(keep) | {o.data for o in keep},
                             fake_user=True, compress=True)
    sys.stderr.write("SAVED %s %d parts\n" % (name, len(keep)))
