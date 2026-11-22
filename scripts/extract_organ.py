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
    # the "types" videos (anatomy/types.py): the knee with its ligaments and menisci, the shoulder with the cuff
    "knee": ["Femur.r", "Tibia.r", "Fibula.r", "Patella.r", "Anterior cruciate ligament.r",
             "Posterior cruciate ligament.r", "Medial meniscus.r", "Lateral meniscus.r",
             "Superficial part of tibial collateral ligament.r", "Fibular collateral ligament.r"],
    "shoulder": ["Clavicle.r", "Scapula.r", "Humerus.r", "Supraspinatus muscle.r", "Infraspinatus muscle.r",
                 "Teres minor muscle.r", "Subscapularis muscle.r", "Glenoid labrum.r", "Acromioclavicular ligament.r",
                 "First rib.r", "Manubrium of sternum"],
    # fmt-types-05/06: the forearm and hand in place together (Colles', Smith's, nightstick, a child's forearm); the
    # old "arm" model predates the baked transforms, so each of its parts sits at the origin
    "forearm": ["Humerus.r", "Radius.r", "Ulna.r"],
    # fmt-types-07 (headaches): the skull with every bone in place (the old "skull" model has each at the origin)
    "head": ["Frontal bone", "Parietal bone.l", "Parietal bone.r", "Occipital bone", "Temporal bone.l",
             "Temporal bone.r", "Sphenoid bone", "Zygomatic bone.l", "Zygomatic bone.r", "Maxilla.l", "Maxilla.r",
             "Nasal bone.l", "Nasal bone.r", "Mandible", "Vomer", "Ethmoid bone", "Lacrimal bone.l", "Lacrimal bone.r",
             "Palatine bone.l", "Palatine bone.r"],
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
    # dd-brain-anger (anatomy/cinematic.py): every gyrus of the cortex, the cerebellum and brainstem as the glass
    # shell, and the deep structures that light up inside it
    "brain": r"^(?!.*(artery|vein|nerve|auricle|Tentorium|[Bb]ranch|bronch|palate|eyeball|kidney|testis))"
             r"([^.]*(gyrus|gyri|lobule|pole)\b[^.]*|Cuneus|Precuneus|Insula \(.*|Amygdaloid body|Hippocampus|Hypothalamus|"
             r"Adenohypophysis|Neurohypophysis|Thalamus|Corpus callosum|Caudate nucleus|Putamen|Fornix|Midbrain|Pons|"
             r"Medulla oblongata|Optic chiasm|Culmen|Declive|Folium of vermis|Tuber of vermis|Pyramis of vermis|"
             r"Uvula of vermis|Nodule of vermis|Lingula of cerebellum|Central lobule|Flocculus|Tonsil of cerebellum|"
             r"(Inferior|Superior) colliculus)(\.[lr])?$",
    # its stress-response shot: the adrenal glands (the atlas kidney is adapted from Lissie Cowley's CC BY-NC model,
    # so it's never extracted; render/brain_scene.py builds a plain kidney shape under each gland instead)
    "adrenal": r"^Suprarenal gland\.[lr]$",
}
# "Diagnose this" in the gray studio (anatomy/diagnose.py, fmt-diagnose-09 on): the bones of a region with the muscles
# and tendons its cases ask about. Atlas names without "muscle"/"ligament" are renamed (RENAME) so the scenes' kind_of
# gives them the right material; the parts keep the same meshes and places.
DIAGNOSE = {
    "elbow": ["Humerus.r", "Radius.r", "Ulna.r", "Extensor carpi radialis brevis.r", "Extensor carpi radialis longus.r",
              "Flexor carpi radialis.r", "Brachioradialis muscle.r"],
    "foot": ["Tibia.r", "Fibula.r", "Plantar aponeurosis.r", "Calcaneal tendon.r"],
    "hamstring": ["Hip bone.r", "Femur.r", "Patella.r", "Tibia.r", "Fibula.r", "Semitendinosus muscle.r",
                  "Semimembranosus muscle.r", "Long head of biceps femoris.r", "Short head of biceps femoris.r",
                  "Rectus femoris muscle.r", "Medial head of gastrocnemius.r", "Lateral head of gastrocnemius.r"],
    "neck": ["Clavicle.r", "Scapula.r", "Humerus.r", "First rib.r", "Manubrium of sternum",
             "Ascending part of trapezius muscle.r", "Transverse part of trapezius muscle.r",
             "Descending part of trapezius muscle.r", "Supraspinatus muscle.r", "Acromial part of deltoid muscle.r",
             "Clavicular part of deltoid muscle.r", "Scapular spinal part of deltoid muscle.r"],
}
# Z-Anatomy swaps the trapezius's parts: its "Ascending part" is the one from the skull to the collarbone (the upper,
# descending fibres) and its "Descending part" is the lower one, so they get plain names here
RENAME = {"Ascending part of trapezius muscle.r": "Upper trapezius muscle.r",
          "Transverse part of trapezius muscle.r": "Middle trapezius muscle.r",
          "Descending part of trapezius muscle.r": "Lower trapezius muscle.r",
          "Extensor carpi radialis brevis.r": "Extensor carpi radialis brevis muscle.r",
          "Extensor carpi radialis longus.r": "Extensor carpi radialis longus muscle.r",
          "Flexor carpi radialis.r": "Flexor carpi radialis muscle.r",
          "Plantar aponeurosis.r": "Plantar aponeurosis ligament.r",
          "Calcaneal tendon.r": "Calcaneal tendon.r",
          "Long head of biceps femoris.r": "Long head of biceps femoris muscle.r",
          "Short head of biceps femoris.r": "Short head of biceps femoris muscle.r",
          "Medial head of gastrocnemius.r": "Medial head of gastrocnemius muscle.r",
          "Lateral head of gastrocnemius.r": "Lateral head of gastrocnemius muscle.r"}
MODELS.update(DIAGNOSE)

import re
for name, pat in PATTERNS.items():
    MODELS[name] = sorted(o.name for o in bpy.data.objects if o.type == "MESH" and re.match(pat, o.name)
                          and max(o.dimensions) > 0.005)
MODELS["forearm"] += MODELS["hand"]
MODELS["elbow"] += MODELS["hand"]
FOOT = [n for n in MODELS["leg"] if n not in ("Femur.r", "Patella.r", "Tibia.r", "Fibula.r")]
MODELS["foot"] += FOOT
MODELS["hamstring"] += FOOT
MODELS["neck"] += MODELS["head"] + [n for n in MODELS["spine"] if re.match(r"^(Atlas|Axis|Vertebra C|Vertebra T[1-6]$)", n)]

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
        if name in DIAGNOSE and o.name in RENAME:
            o.name = RENAME[o.name]
    # (the atlas's "Cross Section X/Y/Z" cutting planes come along into some files; scenes skip them by name)
    bpy.data.libraries.write(os.path.join(OUT, name + ".blend"), set(keep) | {o.data for o in keep},
                             fake_user=True, compress=True)
    sys.stderr.write("SAVED %s %d parts\n" % (name, len(keep)))
