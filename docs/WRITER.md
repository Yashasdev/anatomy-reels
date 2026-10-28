# Writing Anatomy Ace questions

Every reel is one question about one 3D body region (`assets/models/<model>.blend`): the region turns slowly, one
part (or a few) glows lime, a narrator asks the question, a 3-2-1 countdown runs, then the answer is marked. Audience:
high school and college students (pre-med, nursing, biology, the curious). The goal is comments: a fair question
where a second answer is tempting.

## Format (one item, in `banks/<model>.json`)

```json
{
  "id": "skull-04",                 // <model>-NN, continuing the bank's numbering
  "model": "skull",                 // the bank's own model
  "title": "The Skull",             // shown under ANATOMY CHECK
  "highlight": ["Occipital bone"],  // exact names from assets/models/parts.json (several = one glowing group)
  "start_degrees": 160,             // where the turn starts (0 = front, 180 = back); pick the angle that shows the part
  "distance": 4.2,                  // optional: smaller zooms in (2.0 to 6.0; 4.2 frames the whole region)
  "focus": false,                   // optional: true turns and frames around the glowing part; use with distance 1.0-2.0
  "question": "Which bone is glowing?",
  "choices": ["Parietal", "Occipital", "Temporal", "Frontal"],
  "answer_index": 1,
  "trap_index": 0,                  // the tempting wrong choice
  "lines": [                        // the narration, 5 to 9 lines, each at most 75 characters
    "The back of your skull has its own bone. Do you know it?",   // 0: the hook
    "Watch the glowing bone at the back of the head.",            // context
    "Which bone is glowing?",                                     // ask_line: choices appear, then 3-2-1
    "The parietal bones sit on top. This one is lower.",           // explain, name the trap
    "It's B. The occipital bone.",                                // answer_line: always "It's <letter>. ..."
    "Why it matters: it protects the part of the brain that handles vision."  // always last
  ],
  "ask_line": 2,
  "answer_line": 4
}
```

`python -m pytest -q` checks all of this (names, ids, letters, lengths, on-screen fit). On a pull request GitHub also
renders each new question from 8 angles and fails it if the glowing part is hard to see
(`scripts/check_visible.py`; the contact sheet is in the run's artifacts).

## Rules

- Standard textbook anatomy only, and check every fact (web search: a textbook, university or medical-education
  source). No diagnosis, treatment or medical advice; "why it matters" lines are about how the body works, common
  knowledge (like "it's the bone people break most when they fall on a hand") or why students learn it.
- Exactly one right answer. The trap is a real neighbor or a classic mix-up (radius vs ulna, left vs right lung lobes,
  parietal vs temporal, incisor vs canine), never a silly option.
- Left and right are the patient's. Say so in the narration when it matters ("the patient's left lung").
- The question line is short (one line on screen). Choices are short names ("Occipital", not "Occipital bone of skull").
- Spread answers across A to D; never the same letter three times in a row within a bank.
- Use parts big enough to see while the region turns (see below). Small parts of a big region (kneecap, heel bone,
  xiphoid, a single finger bone or vertebra) need `"focus": true` with `distance` 1.2 to 2.0 (the camera turns around
  the glowing part), a good `start_degrees`, or a group highlight.
- Mix question types so it doesn't feel repetitive: which part is glowing; which side or which one of a pair; how many
  (lobes, bones in a group, teeth of a type); what the glowing part does; its everyday name (collarbone, kneecap,
  cheekbone, wisdom tooth is not modeled); which group it belongs to (cervical, thoracic, lumbar).

## Regions and their best parts (exact names in `assets/models/parts.json`)

| Model | Title | Good parts to light up |
|---|---|---|
| heart | The Heart | the four chambers, Pulmonary trunk (valves and papillary muscles are inside: not visible) |
| lungs | The Lungs | the five lobes, Trachea |
| skull | The Skull | Frontal, Parietal (.l/.r), Occipital, Temporal (.l/.r), Sphenoid, Zygomatic (.l/.r), Maxilla (.l/.r), Mandible, Nasal (.l/.r) |
| abdomen | The Abdomen | Liver, Stomach, Gallbladder, Spleen, Pancreas (partly hidden), Duodenum, the four colon parts |
| arm | The Arm | Clavicle, Scapula, Humerus, Radius, Ulna (right arm) |
| leg | The Leg | Femur, Patella (small), Tibia, Fibula, Calcaneus, Talus; foot bones as groups (metatarsals) |
| pelvis | The Pelvis | Hip bone (.l/.r), Sacrum, Coccyx, Vertebra L5 |
| spine | The Spine | single vertebrae are small: light groups (all cervical C1-C7, thoracic T1-T12, lumbar L1-L5), Sacrum, Coccyx, Atlas (C1) |
| chest | The Rib Cage | Manubrium / Body of sternum / Xiphoid process, single ribs (.l/.r), "true/false/floating ribs" as groups |
| hand | The Hand | carpal bones as a group, Scaphoid, metacarpals, phalanges as groups (right hand) |
| eye | The Eye | Sclera, Iris, the six eye muscles (rectus and oblique) of the right eye |
| thigh | Leg Muscles | Gluteus maximus/medius, Rectus femoris, Vastus lateralis/medialis, Sartorius, Gracilis, Adductor longus, Semitendinosus, Semimembranosus, Tensor fasciae latae, Tibialis anterior, Soleus (with the leg bones) |
| teeth | The Teeth | incisors, canines, premolars, first and second molars (upper/lower, .l/.r); groups work well |

A new bank (`banks/<model>.json`) must also be added to `rotation` in `config.json` (the order organs take turns).
Never add Z-Anatomy parts it marks non-commercial (the inner ear models and the Lissie Cowley kidney). New regions
need a model extracted with Blender (`scripts/extract_organ.py`), which a person does, not the Writer.
