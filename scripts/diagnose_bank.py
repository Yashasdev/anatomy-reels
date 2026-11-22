"""Writes banks/diagnose/studio.json (the gray-studio "Diagnose this" cases, fmt-diagnose-09 on). The shows repeat
long part lists, so they're assembled here; edit this file and rerun it rather than the JSON.

    python scripts/diagnose_bank.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTS = json.loads((ROOT / "assets" / "models" / "parts.json").read_text())
CREDIT = "3D model: Z-Anatomy / BodyParts3D (CC BY-SA 4.0)"


def show(model, **kw):
    return {"model": model, **kw}


def pt(part, at, **kw):
    return {"part": part, "at": at, **kw}


def pain(at, size=0.011):
    """The pulsing red spot where it hurts (the case shot): grows in, then throbs."""
    return {"blobs": [{"name": "pain", "at": at, "size": [size] * 3, "kind": "disc", "grow": [0.0, 0.25]}],
            "hurt": ["pain"], "pulse": 1.4}


# --- 09: tennis elbow in someone who has never played tennis -------------------------------------------------------
ECRB, ECRL = "Extensor carpi radialis brevis muscle.r", "Extensor carpi radialis longus muscle.r"
FCR, BR = "Flexor carpi radialis muscle.r", "Brachioradialis muscle.r"
ELBOW_FRAME = [[-0.30, -0.04, 0.96], [-0.14, 0.07, 1.26]]
ELBOW_WIDE = [[-0.31, -0.05, 0.84], [-0.13, 0.08, 1.34]]  # the hook: the whole elbow, the joint in sight
LATERAL = pt(ECRB, [0.2, 0.6, 1.0])  # its origin, on the lateral epicondyle
MEDIAL = pt(FCR, [0.9, 0.5, 1.0])  # its origin, on the medial epicondyle
tennis = {
    "id": "fmt-diagnose-09",
    "subtitle": "Tennis elbow, no tennis",
    "for": "Anyone who lifts, types, paints or carries kids; they send it to the friend who says they have tennis "
           "elbow but has never held a racket (a tease, and a real answer for that friend).",
    "hook_title": "ELBOW PAIN EVERY TIME YOU LIFT A MUG",
    "lines": {
        "case": ["It hurts on the outside of your elbow every time you lift a mug.", "And you've never played tennis."],
        "ask": ["Which muscle's tendon is it?", "Comment your answer."],
        "reveal": ["It's C, the extensor [carpi](kˈɑːɹpaɪ) [radialis](ɹˌeɪdiˈælɪs) brevis.",
                   "Its tendon starts on the outer elbow bump, and every grip tugs on it."],
        "trap": ["Flexor [carpi](kˈɑːɹpaɪ) [radialis](ɹˌeɪdiˈælɪs) is the trap.", "That one starts on the inside bump: golfer's elbow."],
        "send": ["Send this to the friend with tennis elbow who's never held a racket."],
    },
    "question": "Which muscle's tendon is it?",
    "choices": ["Brachioradialis", "Biceps brachii", "Extensor carpi radialis brevis", "Flexor carpi radialis"],
    "answer": "C", "trap": "D",
    "symptom_label": "OUTSIDE OF ELBOW",
    "answer_label": "EXTENSOR CARPI RADIALIS BREVIS",
    "trap_label": "TRAP: FLEXOR CARPI RADIALIS",
    "shows": {
        "case": show("elbow", orient=[0, 0, 75], frame=ELBOW_WIDE, pin={"part": "pain", "at": [0.5, 0.5, 0.5]},
                     focus=LATERAL, zoom=0.95, **pain(LATERAL, 0.008)),
        "question": show("elbow", orient=[0, 0, 40], frame=ELBOW_WIDE, pin=LATERAL, zoom=0.9),
        "answer": show("elbow", orient=[0, 0, 90], frame=ELBOW_FRAME, lit=[ECRB], ghost=[ECRL, BR, FCR], pin=LATERAL,
                       zoom=0.62),
        "trap": show("elbow", orient=[0, 0, -90], frame=ELBOW_FRAME, hurt=[FCR], ghost=[ECRB, ECRL, BR], pin=MEDIAL,
                     zoom=0.62),
        "send": show("elbow", orient=[0, 0, 70], frame=ELBOW_FRAME, lit=[ECRB], ghost=[ECRL, BR, FCR], pin=LATERAL,
                     zoom=0.95),
    },
    "why": "Pain on the outside of the elbow with gripping and lifting is lateral epicondylitis (\"tennis elbow\"): the "
           "tendon of the extensor carpi radialis brevis, where it starts on the lateral epicondyle, is the one most "
           "often involved. Most people who get it don't play tennis; repeated gripping and wrist work cause it. Flexor "
           "carpi radialis (D) is the trap: it starts on the medial epicondyle, the inside bump, and that is medial "
           "epicondylitis (\"golfer's elbow\").",
    "hashtags": ["#tenniselbow", "#anatomy", "#physicaltherapy", "#premed", "#nursingstudent"],
    "sources": ["https://www.ncbi.nlm.nih.gov/books/NBK431092/",
                "https://www.orthoinfo.org/en/diseases--conditions/tennis-elbow-lateral-epicondylitis/",
                "https://www.ncbi.nlm.nih.gov/books/NBK519000/",
                "https://www.hss.edu/condition-list_tennis-elbow.asp"],
    "send": "Send this to the friend with tennis elbow who's never held a racket 🎾",
}

# --- 10: plantar fasciitis, the first steps of the morning ---------------------------------------------------------
FOOT_BONES = [n for n in PARTS["foot"] if n not in ("Plantar aponeurosis ligament.r", "Calcaneal tendon.r")]
PF, ACH = "Plantar aponeurosis ligament.r", "Calcaneal tendon.r"
FOOT_FRAME = [[-0.13, -0.13, -0.02], [-0.03, 0.10, 0.12]]
HEEL = pt("Calcaneus.r", [0.7, 0.8, 0.0])  # under the heel, the medial tubercle side
PF_HEEL = pt(PF, [0.6, 0.85, 0.2])
heel = {
    "id": "fmt-diagnose-10",
    "subtitle": "The first steps hurt",
    "for": "Adults on their feet all day, runners, new parents; they send it to the person who limps to the kettle "
           "every morning (help: it puts a name to their pain).",
    "hook_title": "HEEL PAIN ON YOUR FIRST STEPS OUT OF BED",
    "lines": {
        "case": ["Your first steps out of bed feel like a nail in the bottom of your heel.",
                 "After a few minutes of walking, it eases up."],
        "ask": ["Which structure is it?", "Comment your answer."],
        "reveal": ["It's A, the plantar [fascia](fˈæʃiə).",
                   "This thick band runs from your heel to your toes, and it's sorest at the heel."],
        "trap": ["The Achilles tendon is the trap.", "It hurts at the back of the heel or just above it, not underneath."],
        "send": ["Send this to the friend who limps to the coffee machine every morning."],
    },
    "question": "Which structure is it?",
    "choices": ["Plantar fascia", "Tibial nerve", "Achilles tendon", "Calcaneus (heel bone)"],
    "answer": "A", "trap": "C",
    "symptom_label": "BOTTOM OF HEEL",
    "answer_label": "PLANTAR FASCIA",
    "trap_label": "TRAP: ACHILLES TENDON",
    "shows": {
        "case": show("foot", parts=FOOT_BONES + [PF], orient=[-35, 0, -70], frame=FOOT_FRAME,
                     pin={"part": "pain", "at": [0.5, 0.5, 0.5]}, focus=HEEL, zoom=0.5, **pain(HEEL, 0.009)),
        "question": show("foot", parts=FOOT_BONES + [PF], orient=[-25, 0, -60], frame=FOOT_FRAME, pin=PF_HEEL, zoom=0.8),
        "answer": show("foot", parts=FOOT_BONES + [PF], orient=[-45, 0, -75], frame=FOOT_FRAME, lit=[PF], pin=PF_HEEL,
                       focus=pt(PF, [0.5, 0.6, 0.0]), zoom=0.55),
        "trap": show("foot", orient=[0, 0, -140], frame=FOOT_FRAME, hurt=[ACH], ghost=[PF], pin=pt(ACH, [0.5, 0.6, 0.25]),
                     zoom=0.62),
        "send": show("foot", parts=FOOT_BONES + [PF], orient=[-40, 0, -70], frame=FOOT_FRAME, lit=[PF], pin=PF_HEEL,
                     zoom=0.85),
    },
    "why": "Stabbing pain under the heel with the first steps after sleep or rest, easing as you walk, is the classic "
           "sign of plantar fasciitis: the plantar fascia is the thick band under the foot from the heel bone to the "
           "toes, and it is sorest where it attaches to the heel. The Achilles tendon (C) is the trap: its pain is at "
           "the back of the heel or along the tendon above it, not underneath.",
    "hashtags": ["#plantarfasciitis", "#heelpain", "#anatomy", "#physicaltherapy", "#nursingstudent"],
    "sources": ["https://www.ncbi.nlm.nih.gov/books/NBK431073/",
                "https://www.orthoinfo.org/en/diseases--conditions/plantar-fasciitis-and-bone-spurs/",
                "https://www.orthoinfo.org/en/diseases--conditions/achilles-tendinitis/"],
    "send": "Send this to the friend who limps to the coffee machine every morning ☕",
}

# --- 11: the sprinter's hamstring ---------------------------------------------------------------------------------
BFL, BFS = "Long head of biceps femoris muscle.r", "Short head of biceps femoris muscle.r"
ST, SM = "Semitendinosus muscle.r", "Semimembranosus muscle.r"
THIGH_FRAME = [[-0.16, -0.06, 0.40], [0.0, 0.10, 0.92]]
BACK_OF_THIGH = {"xyz": [-0.075, 0.085, 0.63]}
OTHER_MUSCLES = lambda keep: [n for n in PARTS["hamstring"] if "muscle" in n and n != keep]  # noqa: E731
hamstring = {
    "id": "fmt-diagnose-11",
    "subtitle": "The sprint that ends it",
    "for": "Anyone who plays a sport or runs; they send it to the friend who still sprints like they're 17 (a tease "
           "with a real warning in it).",
    "hook_title": "SHARP PAIN MID-SPRINT",
    "lines": {
        "case": ["Mid-sprint, a runner feels a sharp pain in the back of the thigh.",
                 "Everyone says hamstring. But which one?"],
        "ask": ["Which muscle did they most likely strain?", "Comment your answer."],
        "reveal": ["It's D, the biceps femoris, long head.",
                   "It's the one sprinters strain most, as the leg swings forward."],
        "trap": ["[Semitendinosus](sˌɛmitˌɛndɪnˈoʊsəs) is the trap.", "It's an inner hamstring, and it's strained much less often."],
        "send": ["Send this to your friend who still sprints like they're seventeen."],
    },
    "question": "Which muscle did they most likely strain?",
    "choices": ["Semitendinosus", "Rectus femoris", "Gastrocnemius", "Biceps femoris"],
    "answer": "D", "trap": "A",
    "symptom_label": "BACK OF THIGH",
    "answer_label": "BICEPS FEMORIS (LONG HEAD)",
    "trap_label": "TRAP: SEMITENDINOSUS",
    "shows": {
        "case": show("hamstring", orient=[0, 0, 180], frame=THIGH_FRAME, pin={"part": "pain", "at": [0.5, 0.5, 0.5]},
                     focus=BACK_OF_THIGH, zoom=0.85, **pain(BACK_OF_THIGH, 0.012)),
        "question": show("hamstring", orient=[0, 0, 155], frame=THIGH_FRAME, pin=pt(BFL, [0.5, 1.0, 0.6]), zoom=0.9),
        "answer": show("hamstring", orient=[0, 0, 200], frame=THIGH_FRAME, lit=[BFL], ghost=OTHER_MUSCLES(BFL),
                       pin=pt(BFL, [0.5, 1.0, 0.6]), zoom=0.62),
        "trap": show("hamstring", orient=[0, 0, 160], frame=THIGH_FRAME, hurt=[ST], ghost=OTHER_MUSCLES(ST),
                     pin=pt(ST, [0.5, 1.0, 0.6]), zoom=0.62),
        "send": show("hamstring", orient=[0, 0, 190], frame=THIGH_FRAME, lit=[BFL], ghost=OTHER_MUSCLES(BFL),
                     pin=pt(BFL, [0.5, 1.0, 0.6]), zoom=0.95),
    },
    "why": "A sudden sharp pain in the back of the thigh while sprinting is a hamstring strain, and the long head of the "
           "biceps femoris (on the outer side of the back of the thigh) is the hamstring most often strained in "
           "sprinting, typically as the leg swings forward late in the stride. Semitendinosus (A) is the trap: it's a "
           "hamstring too, one of the two inner hamstrings, but it's involved much less often.",
    "hashtags": ["#hamstring", "#sportsinjury", "#anatomy", "#physicaltherapy", "#premed"],
    "sources": ["https://www.ncbi.nlm.nih.gov/books/NBK558936/",
                "https://www.orthoinfo.org/en/diseases--conditions/hamstring-muscle-injuries/",
                "https://www.ncbi.nlm.nih.gov/books/NBK546688/"],
    "send": "Send this to your friend who still sprints like they're 17 🏃",
}

# --- 12: looking down at a phone ------------------------------------------------------------------------------------
TRAP_M, SUPRA = "Upper trapezius muscle.r", "Supraspinatus muscle.r"
TRAPEZIUS = [TRAP_M, "Middle trapezius muscle.r", "Lower trapezius muscle.r"]
HEAD = [n for n in PARTS["neck"] if not n.endswith(".r") and not n.startswith(("Vertebra", "Atlas", "Axis", "Manubrium"))]
HEAD += [n for n in PARTS["neck"] if n.endswith(".r") and n.split(".")[0] in {
    "Lacrimal bone", "Maxilla", "Nasal bone", "Palatine bone", "Parietal bone", "Temporal bone", "Zygomatic bone",
    "Inferior nasal concha bone"}]
NECK_FRAME = [[-0.24, -0.10, 1.22], [0.08, 0.14, 1.72]]
NOD = [{"parts": HEAD + ["Atlas (C1)", "Axis (C2)", "Vertebra C3"],
        "pivot": pt("Vertebra C5", [0.5, 0.5, 0.5], snap=False),
        "keys": [[0, 0, 0, 0], [0.8, 32, 0, 0], [60, 32, 0, 0]]}]
SPAN = [{"part": TRAP_M, "from": pt("Occipital bone", [0.35, 0.85, 0.15]), "to": pt("Clavicle.r", [0.15, 0.6, 0.5])}]
NECK_PIN = pt(TRAP_M, [0.4, 0.9, 0.5])
phone = {
    "id": "fmt-diagnose-12",
    "subtitle": "Phone neck",
    "for": "Everyone with a phone; they send it to the friend who's always looking down at theirs ('this is you').",
    "hook_title": "NECK ACHE AFTER HOURS ON YOUR PHONE",
    "lines": {
        "case": ["Hours of looking down at your phone.", "Now the side of your neck and the top of your shoulder ache."],
        "ask": ["Which muscle is most likely overworked?", "Comment your answer."],
        "reveal": ["It's B, the upper trapezius.",
                   "It runs from your skull to your shoulder, and helps hold your head as it tips."],
        "trap": ["[Supraspinatus](sˌuːpɹəspaɪnˈeɪtəs) is the trap.", "It's a rotator cuff muscle.",
                 "It hurts on the outer shoulder when you lift your arm."],
        "send": ["Send this to the friend reading this with their head tipped down."],
    },
    "question": "Which muscle is most likely overworked?",
    "choices": ["Deltoid", "Upper trapezius", "Supraspinatus", "Pectoralis major"],
    "answer": "B", "trap": "C",
    "symptom_label": "ACHES HERE",
    "answer_label": "UPPER TRAPEZIUS",
    "trap_label": "TRAP: SUPRASPINATUS",
    "shows": {
        "case": show("neck", orient=[0, 0, 140], frame=NECK_FRAME, moves=NOD, spans=SPAN,
                     pin={"part": "pain", "at": [0.5, 0.5, 0.5]}, focus=NECK_PIN, zoom=0.7, **pain(NECK_PIN, 0.013)),
        "question": show("neck", orient=[0, 0, 150], frame=NECK_FRAME, moves=NOD, spans=SPAN, pin=NECK_PIN, zoom=0.92),
        "answer": show("neck", orient=[0, 0, 145], frame=NECK_FRAME, moves=NOD, spans=SPAN, lit=[TRAP_M], pin=NECK_PIN,
                       zoom=0.7),
        "trap": show("neck", orient=[20, 0, 160], frame=NECK_FRAME, moves=NOD, spans=SPAN, hurt=[SUPRA],
                     ghost=TRAPEZIUS + [n for n in PARTS["neck"] if "deltoid" in n] + ["Clavicle.r"],
                     pin=pt(SUPRA, [0.4, 0.6, 1.0]), focus=pt(SUPRA, [0.5, 0.5, 1.0]), zoom=0.45),
        "send": show("neck", orient=[0, 0, 145], frame=NECK_FRAME, moves=NOD, spans=SPAN, lit=[TRAP_M], pin=NECK_PIN,
                     zoom=0.95),
    },
    "why": "Hours of looking down at a phone tip the head forward, and the muscles at the back of the neck work harder "
           "to hold it; an aching side of the neck and top of the shoulder points to the upper trapezius, which runs "
           "from the base of the skull and the neck to the collarbone and shoulder blade (the levator scapulae often "
           "joins in). Supraspinatus (C) is the trap: it's part of the rotator cuff, and its pain is usually felt on "
           "the outside of the shoulder and upper arm, worse when lifting the arm, not up the neck.",
    "hashtags": ["#textneck", "#neckpain", "#anatomy", "#physicaltherapy", "#posture"],
    "sources": ["https://www.ncbi.nlm.nih.gov/books/NBK518994/",
                "https://www.ncbi.nlm.nih.gov/books/NBK551702/",
                "https://www.orthoinfo.org/en/diseases--conditions/rotator-cuff-tears/"],
    "send": "Send this to the friend reading this with their head tipped down 📱",
}

items = [tennis, heel, hamstring, phone]
for q in items:
    q.setdefault("title", "Diagnose this")
    q.setdefault("credit", CREDIT)
(ROOT / "banks" / "diagnose" / "studio.json").write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n")
print("wrote", len(items), "items")
