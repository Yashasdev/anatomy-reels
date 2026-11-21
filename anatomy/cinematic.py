"""Cinematic 3D videos (Nov 2026): the brain deep dive dd-brain-anger ("This is why you hate your boyfriend") and
the blood types rebuild fmt-types-09b. Dark, near-black looks with glowing structures, depth of field, bloom, grain;
yellow labels and white captions like the "types" videos (anatomy/types.py).

    python -m anatomy.cinematic stills DIR [names...]   # the look samples: 2 frames per video, labels drawn
    python -m anatomy.cinematic preview DIR ID          # half size, 16 samples: timing and labels
    python -m anatomy.cinematic release DIR ID [--keep FRAMES] [--samples N]   # full render: DIR/ID.mp4, .jpg, .json
                                                        # (--keep: 3D frames kept there, a stopped render resumes)

3D layers: render/brain_scene.py (Z-Anatomy brain, assets/models/brain.blend) and render/blood_scene.py (built
red cells, antigens, antibodies, a vessel).
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .make import blender
from .types import BOLD, CAPTION, LABEL, YELLOW, callout, watermark, wrap

ROOT = Path(__file__).resolve().parent.parent
RED, VIOLET, TEAL, AMBER = (255, 70, 60), (190, 140, 255), (80, 230, 220), (255, 176, 60)

# the brain model's parts by role (names as in Z-Anatomy); anything unlisted is cortex glass
ROLE_PATTERNS = {
    "amygdala": r"^Amygdaloid body",
    "hippocampus": r"^Hippocampus\.[lr]$",
    "hypothalamus": r"^Hypothalamus$",
    "pituitary": r"^(Adenohypophysis|Neurohypophysis)$",
    "thalamus": r"^Thalamus\.[lr]$",
    "callosum": r"^Corpus callosum$",
    "basal": r"^(Caudate nucleus|Putamen)\.[lr]$",
    "pfc": r"^(Superior frontal gyrus|Middle frontal gyrus|Opercular part of inferior frontal gyrus|"
           r"Triangular part of inferior frontal gyrus|Orbital part of +inferior frontal gyrus|Orbital gyri.*|"
           r"Straight gyrus|Frontal pole)",
}


# --- the look samples -------------------------------------------------------------------------------------------
BRAIN_STILLS = [
    {"name": "brain-1-hook", "cam": {"focus": "amygdala", "dir": [-0.55, -1.0, 0.25], "dist": 1.75, "lens": 40,
                                     "fstop": 8.0, "aim": "all", "shift": [0, 0, 0.1]},
     "window": {"at": "amygdala", "radius": 0.11, "soft": 0.05},
     "lit": {"amygdala": [0.95, 0.05, 0.03, 3]},
     "flows": [{"from": "amygdala", "to": "hypothalamus", "color": [1.0, 0.15, 0.08], "head": 0.55, "n": 50,
                "arc": [0, -0.02, 0.03], "strength": 10}],
     "pins": ["amygdala"], "dust": 140},
    {"name": "brain-2-hormones", "cam": {"focus": "pituitary", "dir": [-0.8, -1.0, 0.05], "dist": 1.35, "lens": 50,
                                         "fstop": 5.6, "shift": [0, 0, 0.06]},
     "window": {"at": "hypothalamus", "radius": 0.07, "soft": 0.035},
     "lit": {"hypothalamus": [1.0, 0.42, 0.08, 4], "pituitary": [0.55, 0.25, 1.0, 5]},
     "flows": [{"from": "hypothalamus", "to": "pituitary", "color": [0.62, 0.3, 1.0], "head": 0.95, "n": 220,
                "spread": 0.45, "trail": 0.9, "size": 0.002, "strength": 8, "arc": [0, -0.02, 0]}],
     "pins": ["hypothalamus", "pituitary"], "dust": 120},
]

BLOOD_STILLS = [
    {"name": "blood-1-hook", "kind": "hook"},
    {"name": "blood-2-cell", "kind": "cell", "type": "A+"},
]


def run_blender(script: str, spec: dict) -> None:
    cmd = [blender(), "-b", "--factory-startup", "-t", "4", "--python", str(ROOT / "render" / script), "--",
           json.dumps(spec)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    shots = [ln for ln in r.stdout.splitlines() if ln.startswith("SHOT")]
    sys.stderr.write("\n".join(ln for ln in r.stdout.splitlines() if ln.startswith(("MERGED", "SHOT", "TIME"))) + "\n")
    if r.returncode or len(shots) < len(spec.get("only") or spec["shots"]):
        sys.stderr.write(r.stdout[-4000:] + r.stderr[-4000:])
        raise SystemExit(f"{script} failed")


def grade(img: Image.Image, seed: int = 0) -> Image.Image:
    """Vignette and film grain over the render."""
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((x - w / 2) / (w * 0.62)) ** 2 + ((y - h * 0.46) / (h * 0.6)) ** 2)
    a *= (1 - 0.55 * np.clip(r - 0.35, 0, 1) ** 1.6)[..., None]
    g = np.random.default_rng(seed).normal(0, 3.2, (h // 2, w // 2, 1)).astype(np.float32)
    a += np.repeat(np.repeat(g, 2, axis=0), 2, axis=1)[:h, :w]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def title(img: Image.Image, rows: list[tuple[str, tuple]], y: int, size: int = 96) -> None:
    """The hook, big and bold at the top, a word or line in an accent colour."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = BOLD(size)
    for i, (text, colour) in enumerate(rows):
        d.text((img.width / 2, y + i * size * 1.08), text, font=f, fill=colour + (255,), anchor="mt",
               stroke_width=5, stroke_fill=(6, 6, 8, 240))
    shadow = layer.getchannel("A").filter(ImageFilter.GaussianBlur(10))
    img.paste((0, 0, 0), mask=shadow.point(lambda v: v * 0.5))
    img.paste(layer, mask=layer)


def caption_hl(img: Image.Image, text: str, y: int = 1335, width: int = 760, hl: dict | None = None) -> None:
    """White captions with chosen words in an accent colour (the word being explained)."""
    hl = hl or {}
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = CAPTION(54)
    rows = wrap(d, text, f, width)
    lh = 66
    y0 = y - lh * len(rows) // 2
    for i, row in enumerate(rows):
        x = img.width / 2 - d.textlength(row, font=f) / 2
        for word in row.split(" "):
            key = re.sub(r"[^\w]", "", word).lower()
            colour = next((c for k, c in hl.items() if re.sub(r"[^\w]", "", k).lower() == key), (255, 255, 255))
            d.text((x, y0 + i * lh + 48), word, font=f, fill=colour + (255,), anchor="ls", stroke_width=4,
                   stroke_fill=(8, 8, 10, 235))
            x += d.textlength(word + " ", font=f)
    shadow = layer.getchannel("A").filter(ImageFilter.GaussianBlur(6))
    img.paste((0, 0, 0), mask=shadow.point(lambda v: v * 0.4))
    img.paste(layer, mask=layer)


def pill(img: Image.Image, xy, text: str, colour, size: int = 34, anchor: str = "mm") -> None:
    """A rounded tag: the stage line, a hormone's name riding its stream."""
    d = ImageDraw.Draw(img, "RGBA")
    f = BOLD(size)
    tw = d.textlength(text, font=f)
    w, h = tw + size * 1.2, size * 1.75
    x, y = xy
    if anchor == "mm":
        x -= w / 2
    y -= h / 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=(8, 8, 12, 190), outline=colour + (255,), width=3)
    d.text((x + w / 2, y + h / 2 + 1), text, font=f, fill=colour + (255,), anchor="mm")


def brain_overlay(name: str, img: Image.Image, pins: dict) -> Image.Image:
    img = grade(img, 1)
    if name == "brain-1-hook":
        title(img, [("THIS IS WHY YOU", (255, 255, 255)), ("HATE YOUR", RED), ("BOYFRIEND", (255, 255, 255))], 300)
        callout(img, pins["amygdala"], "AMYGDALA", 1.0, 1.0, 1.0, place=((pins["amygdala"][0] + 130, 1120), 1))
    else:
        pill(img, (150, 330), "2/5  THE SLOW WAVE", VIOLET, anchor="lm")
        callout(img, pins["hypothalamus"], "HYPOTHALAMUS", 1.0, 1.0, 1.0, place=((pins["hypothalamus"][0] - 60, 520), 1))
        callout(img, pins["pituitary"], "PITUITARY", 1.0, 1.0, 1.0, place=((pins["pituitary"][0] + 90, 1150), 1))
        mid = ((pins["hypothalamus"][0] + pins["pituitary"][0]) / 2 - 150,
               (pins["hypothalamus"][1] + pins["pituitary"][1]) / 2)
        pill(img, mid, "CRH", VIOLET, size=40)
        caption_hl(img, "your pituitary answers with ACTH,", hl={"ACTH": VIOLET})
    watermark(img, 1.0)
    return img


def blood_overlay(name: str, img: Image.Image, pins: dict) -> Image.Image:
    img = grade(img, 2)
    if name == "blood-1-hook":
        title(img, [("GIVE SOMEONE THE", (255, 255, 255)), ("WRONG BLOOD TYPE", RED)], 300, size=88)
        pill(img, (540, 545), "TYPE A BLOOD  →  TYPE B PATIENT", (255, 255, 255), size=32)
        callout(img, pins["clump"], "CLUMPING", 1.0, 1.0, 1.0, place=((pins["clump"][0] + 120, 1160), 1))
        caption_hl(img, "and this happens.", y=1400)
    else:
        pill(img, (150, 330), "A POSITIVE  ·  ABOUT 1 IN 3", (255, 255, 255), anchor="lm")
        callout(img, pins["sugar"], "A ANTIGEN", 1.0, 1.0, 1.0, place=((pins["sugar"][0] - 40, 560), 1))
        callout(img, pins["rh"], "Rh (D) PROTEIN", 1.0, 1.0, 1.0, place=((pins["rh"][0] - 380, 1170), 1))
        callout(img, pins["antibody"], "ANTI-B (IgM)", 1.0, 1.0, 1.0,
                place=((min(pins["antibody"][0], 880) - 330, pins["antibody"][1] - 190), 1))
        caption_hl(img, "A markers, and plasma that attacks B.", hl={"A": (150, 245, 40), "B": (255, 110, 120)})
    watermark(img, 1.0)
    return img


_env = __import__("os").environ
QUICK = {"width": 540, "height": 960, "samples": 16} if _env.get("QUICK") else {}
if _env.get("ENGINE"):  # ENGINE=cycles: the one-frame quality and time comparison
    QUICK["engine"] = _env["ENGINE"]


def stills(dest: Path, only: list[str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="cinematic-"))
    jobs = []
    want = lambda n: not only or n in only  # noqa: E731
    if any(want(s["name"]) for s in BRAIN_STILLS):
        run_blender("brain_scene.py", {"root": str(ROOT), "out": str(work), "roles": ROLE_PATTERNS,
                                       "samples": 128, **QUICK, "shots": [s for s in BRAIN_STILLS if want(s["name"])]})
        jobs += [(s["name"], brain_overlay) for s in BRAIN_STILLS if want(s["name"])]
    if any(want(s["name"]) for s in BLOOD_STILLS):
        run_blender("blood_scene.py", {"out": str(work), "samples": 96, **QUICK,
                                       "shots": [s for s in BLOOD_STILLS if want(s["name"])]})
        jobs += [(s["name"], blood_overlay) for s in BLOOD_STILLS if want(s["name"])]
    for name, overlay in jobs:
        pins = json.loads((work / f"{name}.json").read_text())["pins"]
        img = Image.open(work / f"{name}.png").convert("RGB")
        if img.width != 1080:  # quick renders: scale up so the overlay layout holds
            k = 1080 / img.width
            img = img.resize((1080, 1920))
            pins = {key: [v[0] * k, v[1] * k] for key, v in pins.items()}
        overlay(name, img, pins).save(dest / f"{name}.png")
        print(dest / f"{name}.png")


# --- the videos ------------------------------------------------------------------------------------------------
FPS, SR = 30, 44100
GAP, WHIPF, TAIL, SEND_HOLD = 0.38, 5, 0.5, 2.0
COLOURS = {"lime": (150, 245, 40), "coral": (255, 110, 120), "yellow": YELLOW, "blue": (100, 165, 255),
           "red": RED, "violet": VIOLET, "teal": TEAL, "amber": AMBER, "white": (255, 255, 255)}


def items() -> list[dict]:
    return [q for p in sorted((ROOT / "banks" / "cinematic").glob("*.json")) for q in json.loads(p.read_text())]


def timeline(q: dict, lengths: list[float]) -> tuple[list[dict], list[dict], float]:
    """Cues (each line's start and length) and shots (start, end) from how long each voiced line takes. The last
    line is the send line; it holds alone for SEND_HOLD seconds, then the cover tail."""
    cues, shots, t = [], [], 0.15
    for i, (line, sec) in enumerate(zip(q["beats"], lengths)):
        if line.get("shot"):
            start = 0.0 if not shots else t - 0.12
            if shots:
                shots[-1]["end"] = start
            shots.append({"name": line["shot"], "start": start, **q["shots"][line["shot"]]})
        cues.append({**line, "i": i, "at": t, "len": sec})
        t += sec + GAP
    total = cues[-1]["at"] + cues[-1]["len"] + SEND_HOLD + TAIL
    shots[-1]["end"] = total
    for sh in shots:
        sh["seconds"] = sh["end"] - sh["start"]
        sh["frames"] = int(round(sh["end"] * FPS)) - int(round(sh["start"] * FPS))
    return cues, shots, total


def send_line(img: Image.Image, text: str) -> None:
    rows = wrap(ImageDraw.Draw(img), text.upper().rstrip("."), BOLD(60), 820)
    title(img, [(r, (255, 255, 255)) for r in rows], 1330, size=60)


def plink(seed: int) -> np.ndarray:
    """A soft falling plink for a label landing."""
    t = np.arange(int(0.25 * SR)) / SR
    f = 1400 * np.exp(-t * 6) + 700
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 22)
    return (x * 0.22).astype(np.float32)


def label_place(pin, text: str) -> tuple:
    """Where a yellow label sits: up and to the side of its pin, always inside the phone's safe area (x 120-900)."""
    w = ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(text, font=LABEL(74))
    y = min(max(pin[1] - 170, 430), 1150)
    if pin[0] - 120 - w >= 120 and pin[0] + 120 + w + 30 > 900:
        return (pin[0] - 110, y), -1
    return (min(max(120, pin[0] + 110), 900 - w - 30), y), 1


def whip(img: Image.Image, k: float, out: bool) -> Image.Image:
    """The shot whips away to the left (out, k 0 -> 1) or in from the right (k 0 -> 1), smeared sideways."""
    a = np.asarray(img).astype(np.float32)
    e = k * k if out else (1 - k) * (1 - k)
    shift = int((-1 if out else 1) * e * img.width * 0.6)
    acc = np.zeros_like(a)
    for j in range(8):
        acc += np.roll(a, shift + int((j - 4) * 0.03 * img.width * (0.3 + e)), axis=1)
    return Image.fromarray((acc / 8).astype(np.uint8))


def chart_frame(q: dict, age: float, said: set) -> Image.Image:
    """The closing chart: every type, how common it is (the words the Red Cross uses), bars growing in turn."""
    img = Image.new("RGB", (1080, 1920), (8, 6, 8))
    g = np.asarray(img).astype(np.float32)
    y, x = np.mgrid[0:1920, 0:1080].astype(np.float32)
    glow = np.exp(-(((x - 540) / 700) ** 2 + ((y - 800) / 900) ** 2))[..., None] * np.array([46, 8, 10])
    img = Image.fromarray(np.clip(g + glow, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    c = q["chart"]
    d.text((540, 330), c["title"], font=BOLD(50), fill=(255, 255, 255), anchor="mm")
    d.text((540, 385), f"Source: {c['source']}", font=CAPTION(26), fill=(170, 160, 165), anchor="mm")
    top = max(r[1] for r in c["rows"])
    for k, (name, pct, words) in enumerate(c["rows"]):
        a = min(1.0, max(0.0, (age - 0.12 * k) / 0.45))
        if a <= 0:
            continue
        yy = 470 + k * 96
        hot = name in said
        col = (255, 70, 60) if hot else (200, 40, 44)
        d.rounded_rectangle([120, yy, 250, yy + 66], radius=16, fill=col)
        d.text((185, yy + 34), name, font=BOLD(36), fill=(255, 255, 255), anchor="mm")
        wbar = 590 * (pct / top) ** 0.6 * a
        d.rounded_rectangle([270, yy + 10, 270 + max(8, wbar), yy + 30], radius=10,
                            fill=(255, 120, 110) if hot else (150, 40, 46))
        d.text((270, yy + 42), words, font=CAPTION(30), fill=(255, 255, 255) if hot else (215, 205, 208))
    return img


def chunks(text: str, most: int = 7) -> list[str]:
    """A line as short caption phrases (split at punctuation, about 7 words at most), shown one after another."""
    parts = [p.strip() for p in re.findall(r"[^,.?!:]+[,.?!:\"]*", text) if p.strip()]
    out = []
    for p in parts:
        words = p.split()
        while len(words) > most + 1 or (len(" ".join(words)) > 40 and len(words) > 2):
            half = (len(words) + 1) // 2
            out.append(" ".join(words[:half]))
            words = words[half:]
        if out and len(out[-1].split()) + len(words) <= 4:  # tiny bits ride with the phrase before
            out[-1] += " " + " ".join(words)
        else:
            out.append(" ".join(words))
    return out


def chunk_at(text: str, k: float) -> str:
    """The phrase being said at fraction k of the line (by characters, which track speech closely enough)."""
    cs = chunks(text)
    total = sum(len(c) for c in cs)
    acc = 0
    for c in cs:
        acc += len(c)
        if k * total < acc:
            return c
    return cs[-1]


def fx_draw(img: Image.Image, fx: dict, age: float, pins: dict) -> None:
    """The 2D beats over the 3D (age: seconds since the line started)."""
    d = ImageDraw.Draw(img, "RGBA")
    pop = lambda a: min(1.0, max(0.0, a / 0.25))  # noqa: E731
    if "bubbles" in fx:
        target = pins.get("amygdala", (540, 1000))
        for j, text in enumerate(fx["bubbles"]):
            a = age - 0.3 * j
            if a <= 0:
                continue
            k = min(1.0, a / 2.2)
            x0, y0 = (150 + 330 * j, 470 + 140 * (j % 2))
            x, y = x0 + (target[0] - x0) * k * 0.55, y0 + (target[1] - y0) * k * 0.45
            al = int(255 * pop(a) * (1 - 0.6 * k))
            f = CAPTION(38)
            w = d.textlength(text, font=f) + 56
            d.rounded_rectangle([x - w / 2, y - 34, x + w / 2, y + 34], radius=30, fill=(245, 245, 248, al))
            d.polygon([(x - 18, y + 30), (x - 40, y + 56), (x, y + 32)], fill=(245, 245, 248, al))
            d.text((x, y), text, font=f, fill=(20, 20, 24, al), anchor="mm")
    if "meters" in fx:
        for j, name in enumerate(fx["meters"]):
            a = age - 0.25 * j
            if a <= 0:
                continue
            y = 450 + j * 120
            fill = min(1.0, a / 0.9)
            d.text((150, y), name, font=BOLD(34), fill=(255, 255, 255, int(255 * pop(a))), anchor="ls")
            d.rounded_rectangle([150, y + 14, 870, y + 44], radius=15, fill=(255, 255, 255, 40))
            d.rounded_rectangle([150, y + 14, 150 + 720 * (0.35 + 0.6 * fill), y + 44], radius=15,
                                fill=AMBER + (int(255 * pop(a)),))
            d.text((880, y), "↑", font=BOLD(56), fill=AMBER + (int(255 * pop(a)),), anchor="rs")
    if "tag" in fx and fx["tag"][1] in pins:
        x, y = pins[fx["tag"][1]]
        if age > 0.2:
            pill(img, (min(max(x - 120, 160), 860), min(max(y, 480), 1150)), fx["tag"][0], VIOLET, size=40)
    if "clock" in fx:
        lo, hi = fx["clock"]
        cx, cy, r = 540, 650, 190
        k = min(1.0, age / 1.6)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 90), width=6)
        d.arc([cx - r, cy - r, cx + r, cy + r], -90 + 360 * lo / 60, -90 + 360 * hi / 60, fill=VIOLET + (255,), width=22)
        ang = math.radians(-90 + 360 * (hi * k) / 60)
        d.line([(cx, cy), (cx + (r - 30) * math.cos(ang), cy + (r - 30) * math.sin(ang))], fill=(255, 255, 255, 255),
               width=8)
        d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=(255, 255, 255, 255))
        d.text((cx, cy + r + 50), f"{int(hi * k)} MIN", font=BOLD(56), fill=(255, 255, 255, 255), anchor="mm")
        d.text((cx, cy - r - 44), "CORTISOL PEAK", font=BOLD(40), fill=VIOLET + (255,), anchor="mm")
    if "cards" in fx or "cards_fly" in fx:
        n = fx.get("cards") or fx.get("cards_fly")
        cx, cy = pins.get("hippocampus", (540, 900))
        for j in range(n):
            a = age - 0.2 * j
            if a <= 0:
                continue
            ang = 2 * math.pi * j / n + age * 0.6
            fly = min(1.0, max(0.0, (a - 0.2) / 1.2)) if "cards_fly" in fx else 0.0
            sc = 1 + 2.2 * fly * fly
            x = cx + math.cos(ang) * 260 * (1 + fly)
            y = cy + math.sin(ang) * 150 * (1 + fly) - 150
            w, h = 170 * sc, 112 * sc
            al = int(230 * pop(a) * (1 - fly))
            d.rounded_rectangle([x - w / 2, y - h / 2, x + w / 2, y + h / 2], radius=12 * sc,
                                fill=(255, 214, 120, int(al * 0.25)), outline=(255, 214, 120, al), width=3)
            for row in range(3):
                d.line([(x - w * 0.35, y - h * 0.2 + row * h * 0.2), (x + w * (0.35 - 0.2 * (row == 2)),
                        y - h * 0.2 + row * h * 0.2)], fill=(255, 230, 170, al), width=max(2, int(3 * sc)))
    if "counter" in fx:
        pre, num, post = fx["counter"]
        k = min(1.0, max(0.0, (age - 1.2) / 1.0))  # counts up as "60 percent" is said
        if age > 0.9:
            title(img, [(f"{pre}{int(round(num * k))}{post}", RED)], 430, size=150)
            d.text((540, 610), "AMYGDALA RESPONSE", font=BOLD(36), fill=(255, 255, 255, 230), anchor="mm")
    if "stamp" in fx and age > 2.3:
        a = min(1.0, (age - 2.3) / 0.18)
        layer = Image.new("RGBA", (760, 260), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle([10, 10, 750, 250], radius=24, outline=AMBER + (255,), width=12)
        ld.text((380, 130), fx["stamp"], font=BOLD(150), fill=AMBER + (255,), anchor="mm")
        sc = 1.6 - 0.6 * a
        layer = layer.resize((int(760 * sc), int(260 * sc))).rotate(-8, expand=True)
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
        img.paste(layer, (int(540 - layer.width / 2), int(560 - layer.height / 2)), layer)
    if "checks" in fx:
        for j, text in enumerate(fx["checks"]):
            a = age - 0.55 * j - 0.3
            if a <= 0:
                continue
            y = 440 + j * 96
            al = int(255 * pop(a))
            d.ellipse([150, y - 34, 218, y + 34], fill=TEAL + (al,))
            d.line([(166, y), (180, y + 16), (204, y - 16)], fill=(10, 30, 30, al), width=9)
            d.text((248, y), text, font=BOLD(56), fill=(255, 255, 255, al), anchor="lm")


def build(q: dict, out: Path, quick: bool = False, samples: int | None = None, keep: Path | None = None) -> float:
    """Voice, 3D frames (render/<scene>_scene.py), overlays, sound: out (.mp4, .jpg cover)."""
    from . import music
    from .types import speak, shown, whoosh

    work = Path(tempfile.mkdtemp(prefix="cine-"))
    script = [ln["say"] for ln in q["beats"]]
    lines = speak(script, work / "voice")
    cues, shots, total = timeline(q, [sec for _, sec in lines])
    scale = 0.5 if quick else 1.0
    frames_dir = keep or (work / "frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    three_d = [sh for sh in shots if sh["kind"] != "chart"]
    step = 3 if quick else 1
    spec = {"root": str(ROOT), "out": str(frames_dir), "samples": samples or (16 if quick else 64), "step": step,
            "width": int(1080 * scale), "height": int(1920 * scale), "roles": ROLE_PATTERNS,
            "shots": [{k: v for k, v in sh.items() if k not in ("start", "end")} for sh in three_d]}
    run_blender(q["scene"], spec)
    pins = {sh["name"]: json.loads((frames_dir / sh["name"] / "pins.json").read_text()) for sh in three_d}

    video = work / "video.mp4"
    enc = subprocess.Popen(["ffmpeg" if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0
                            else __import__("imageio_ffmpeg").get_ffmpeg_exe(), "-y", "-loglevel", "error",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1080x1920", "-r", str(FPS), "-i", "-",
                            "-c:v", "libx264", "-crf", "22", "-preset", "slow", "-pix_fmt", "yuv420p", str(video)],
                           stdin=subprocess.PIPE)
    n = int(round(total * FPS))
    labels_at = []  # (time, shot) of each label landing, for the plinks
    last = None
    for k in range(n):
        t = k / FPS
        si = next(i for i, sh in enumerate(shots) if t < sh["end"] or i == len(shots) - 1)
        sh = shots[si]
        f = k - int(round(sh["start"] * FPS))
        cue = next((c for c in reversed(cues) if c["at"] - 0.05 <= t), cues[0])
        if sh["kind"] == "chart":
            first = next(c for c in cues if c.get("shot") == sh["name"])
            img = chart_frame(q, t - sh["start"], set(q["chart"].get("highlight", [])) if t >= first["at"] + 0.4 else set())
        else:
            fr = min(f, sh["frames"] - 1)
            img = Image.open(frames_dir / sh["name"] / f"{fr - fr % step:05d}.png").convert("RGB")
            if img.width != 1080:
                img = img.resize((1080, 1920))
            fp = pins[sh["name"]][min(f, len(pins[sh["name"]]) - 1)]
            fp = {key: [v[0] / scale, v[1] / scale] for key, v in fp.items()}
            if f < WHIPF and si > 0:
                img = whip(img, f / WHIPF, out=False)
            elif sh["frames"] - f <= WHIPF and si < len(shots) - 1:
                img = whip(img, 1 - (sh["frames"] - f) / WHIPF, out=True)
            img = grade(img, k // 2)  # the grain changes every other frame: lighter on the encoder
            if sh["name"] == q["beats"][0]["shot"]:  # the hook title holds over the first shot
                title(img, [(r, COLOURS[c]) for r, c in q["hook_title"]], 300, size=88)
                if q.get("hook_pill"):
                    pill(img, (540, 545), q["hook_pill"], (255, 255, 255), size=32)
            # the label of the latest line in this shot that has one
            lab = next((c for c in reversed(cues) if c.get("label") and c["at"] <= t and c["at"] >= sh["start"] - 0.2), None)
            if lab and lab["label"][1] in fp:
                pin = fp[lab["label"][1]]
                age = t - lab["at"] - 0.15
                fade = min(1.0, max(0.0, (sh["end"] - 0.1 - t) / 0.2))
                callout(img, pin, lab["label"][0], age, fade, 1.0, place=label_place(pin, lab["label"][0]))
                if (lab["i"], sh["name"]) not in [x[1:] for x in labels_at]:
                    labels_at.append((lab["at"] + 0.15, lab["i"], sh["name"]))
            stage = next((c["stage"] for c in reversed(cues) if c.get("stage") and c["at"] - 0.2 <= t and
                          c["at"] >= sh["start"] - 0.2), None)
            if stage:
                pill(img, (150, 330), stage, (255, 255, 255), anchor="lm")
            fxc = next((c for c in reversed(cues) if c.get("fx") and c["at"] <= t and c["at"] >= sh["start"] - 0.2
                        and t < c["at"] + c["len"] + 1.4), None)
            if fxc:
                fx_draw(img, fxc["fx"], t - fxc["at"], fp)
        if t < cue["at"] + cue["len"] + 0.35:
            last_line = cue["i"] == len(cues) - 1
            hl = {w: COLOURS[c] for w, c in cue.get("hl", {}).items()}
            if last_line:  # the send line, big and alone
                send_line(img, shown(cue["say"]))
            else:
                k = (t - cue["at"]) / max(0.1, cue["len"])
                caption_hl(img, chunk_at(shown(cue["say"]), k), y=1420 if sh["kind"] == "chart" else 1335, hl=hl)
        elif cue["i"] == len(cues) - 1:
            send_line(img, shown(cue["say"]))
        watermark(img, 1.0)
        enc.stdin.write(img.tobytes())
        last = img
    enc.stdin.close()
    enc.wait()

    buf = np.zeros(int((total + 1) * SR), np.float32)

    def add(x, at, gain=1.0):
        a = int(at * SR)
        buf[a:a + len(x)] += x[: max(0, len(buf) - a)] * gain

    import soundfile as sf
    for c in cues:
        v, sr = sf.read(lines[c["i"]][0], dtype="float32")
        if sr != SR:
            v = np.interp(np.arange(0, len(v), sr / SR), np.arange(len(v)), v).astype(np.float32)
        add(v, c["at"])
    for sh in shots[1:]:
        add(whoosh(0.3), sh["start"] - 0.15, 0.45)
    for at, i, _ in labels_at[:10]:
        add(plink(i), at, 0.6)
    track = music.render(q["music"], total).mean(axis=1)
    voiced = np.zeros(len(track), bool)
    for c in cues:
        voiced[int(c["at"] * SR): int((c["at"] + c["len"]) * SR)] = True
    duck = np.convolve(np.where(voiced, 0.4, 1.0), np.ones(4410) / 4410, mode="same")
    buf[: len(track)] += (track * duck * 0.14).astype(np.float32)
    wav = work / "sound.wav"
    sf.write(wav, buf[: int(total * SR)], SR)
    from .make import ffmpeg
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav),
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    last.save(out.with_suffix(".jpg"), quality=92)
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return total


def info(q: dict, seconds: float) -> dict:
    """What the posting job needs (anatomy/series.py)."""
    from .types import shown
    return {"id": q["id"], "format": q["format"], "title": q["title"], "hook": shown(q["beats"][0]["say"]),
            "question": q["question"], "choices": [], "answer": "", "why": q["why"], "seconds": round(seconds, 2),
            "music": q["music"], "hashtags": q["hashtags"][:5], "sources": q["sources"], "credit": q["credit"],
            "send": q["send"], "hold": True}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "stills":
        stills(Path(sys.argv[2]).expanduser(), sys.argv[3:])
    elif len(sys.argv) >= 4 and sys.argv[1] in ("release", "preview"):  # release DIR ID [--keep FRAMES_DIR]
        q = next(x for x in items() if x["id"] == sys.argv[3])
        folder = Path(sys.argv[2]).expanduser()
        keep = Path(sys.argv[sys.argv.index("--keep") + 1]).expanduser() if "--keep" in sys.argv else None
        smp = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else None
        secs = build(q, folder / f"{q['id']}.mp4", quick=sys.argv[1] == "preview", keep=keep, samples=smp)
        (folder / f"{q['id']}.json").write_text(json.dumps(info(q, secs), indent=1, ensure_ascii=False) + "\n")
        print(f"{q['id']}: {secs:.1f} s")
    else:
        print(__doc__)
