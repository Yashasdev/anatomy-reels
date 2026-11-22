"""'Diagnose this' in the gray studio (fmt-diagnose-09 on): a short case, four choices, a countdown, the answer lit on
real 3D anatomy, the trap explained, then a send line. Same studio, 3D layer (render/types_scene.py), voice and
labels as the Types videos (anatomy/types.py); earlier Diagnose videos were Remotion cards (~/anatomy-formats).

    python -m anatomy.diagnose say ID              # voice the script, print what whisper hears, line by line
    python -m anatomy.diagnose stills ID DIR       # one half-size frame per shot (check the 3D framing)
    python -m anatomy.diagnose preview ID DIR      # half size, quick: check timing and layout
    python -m anatomy.diagnose release DIR [ids]   # full size: DIR/<id>.mp4 + <id>.json (published with "hold")

An item (banks/diagnose/*.json, written by scripts/diagnose_bank.py) has the narration in "lines" (case, ask,
reveal, trap, send: said sentence by sentence by Kokoro af_heart), the choices, the answer and trap letters, the
labels, and five "shows" in types_scene.py's format: "case" (where it hurts: a pulsing red spot), "question" (the
region, neutral), "answer" (the answer lit yellow), "trap" (the trap part red) and "send" (the answer again, wide).

The timeline, shot by shot:
  case      the hook title and the red "where it hurts" label from the first frame; the case is read
  question  the 3D moves up, the choices card comes in under it, the question is read, "Comment your answer",
            then a 3-2-1 countdown with ticks
  answer    the right row turns yellow, the part lights up with its yellow label; the why is read
  trap      the trap's row turns red with a TRAP tag, its part turns red; the trap is explained
  send      the card leaves, the answer part turns wide, the send line holds alone ~2 s
  cover     the last 0.5 s repeats the question frame (choices, nothing revealed), so the cover never shows the answer
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import music
from . import types as T
from .make import blender, ffmpeg

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
FPS, SR = T.FPS, T.SR
SHOTS = ("case", "question", "answer", "trap", "send")
GAP = 0.3           # between sentences
LEAD = 0.3          # a shot's first line starts this long after its whip-in
COUNT = 3           # the countdown, seconds
SEND_HOLD = 1.2     # the send line holds alone this long after it's said (on screen ~5 s in all)
COVER_TAIL = 0.5
RED = (236, 64, 52)
YELLOW = T.YELLOW
CARD = (92, 1010, 888, 1400)   # the choices card: under the 3D, above the captions, clear of the right-hand column
CAPTION_LOW = 1530              # captions while the card is up (two rows end by y 1592)
ZONE = (330, 990)              # where the 3D sits while the card is up (y)
SMALL = 0.62                   # its size then
EMOJI = Path("/System/Library/Fonts/Apple Color Emoji.ttc")


def items() -> list[dict]:
    out = []
    for p in sorted((ROOT / "banks" / "diagnose").glob("*.json")):
        for q in json.loads(p.read_text()):
            L = q["lines"]
            out.append({**q, "script": L["case"] + L["ask"] + L["reveal"] + L["trap"] + L["send"]})
    return out


def item(vid: str) -> dict:
    return next(q for q in items() if q["id"] == vid)


# --- timeline ------------------------------------------------------------------------------------------------------
def plan(q: dict, lines: list[tuple[Path, float]]) -> tuple[list[dict], list[dict], dict]:
    """Blender segments (one "type" shot each), narration cues and the key moments, from each line's length."""
    cues, k = [], 0

    def say(at: float) -> float:
        nonlocal k
        cues.append({"line": k, "at": at, "text": T.shown(q["script"][k]), "shot": None})
        end = at + lines[k][1]
        k += 1
        return end

    segs, marks, t = [], {}, 0.0
    for shot in SHOTS:
        start = t
        at = 0.12 if shot == "case" else start + LEAD
        said = q["lines"]["send" if shot == "send" else {"question": "ask", "answer": "reveal"}.get(shot, shot)]
        for i, _ in enumerate(said):
            if i:
                at += GAP
            if shot == "question" and i == len(said) - 1:
                marks["count"] = at  # the countdown starts as "Comment your answer" is said
            n = len(cues)
            at = say(at)
            cues[n]["shot"] = shot
        end = at + 0.2
        if shot == "question":
            end = marks["count"] + COUNT + 0.1
        if shot == "send":
            end = at + SEND_HOLD
        segs.append({"kind": "type", "name": shot, "start": round(start, 3), "end": round(end, 3),
                     "whip_in": shot != "case", "crack": 0.1 if shot == "case" else 0.3 if shot != "question" else 999})
        marks[shot] = start
        t = end
    assert k == len(q["script"]), "every line is said once"
    marks["end"] = t
    return segs, cues, marks


# --- drawing -------------------------------------------------------------------------------------------------------
def emoji(ch: str, size: int) -> Image.Image | None:
    try:
        f = ImageFont.truetype(str(EMOJI), 160)
    except OSError:
        return None
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((100, 100), ch, font=f, embedded_color=True, anchor="mm")
    im = T.crop(im)
    k = size / max(im.size)
    return im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)


def pill(img: Image.Image, text: str, y: float, s: float, fill=YELLOW, ink=(16, 16, 18), size: int = 36,
         fade: float = 1.0) -> None:
    if fade <= 0:
        return
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = T.BOLD(int(size * s))
    w = d.textlength(text, font=f)
    a = int(255 * fade)
    h = size * 1.5
    d.rounded_rectangle([img.width / 2 - w / 2 - 24 * s, y * s, img.width / 2 + w / 2 + 24 * s, (y + h) * s],
                        radius=int(h / 2 * s), fill=(*fill, a))
    d.text((img.width / 2, (y + h / 2) * s), text, font=f, fill=(*ink, a), anchor="mm")
    img.paste(layer, (0, 0), layer)


def banner(img: Image.Image, text: str, fade: float, s: float) -> None:
    """The hook title: heavy white with a dark outline, up to 2 lines from y 330, inside x 120-960."""
    if fade <= 0:
        return
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for size in range(84, 40, -2):
        f = T.font("Montserrat.ttf", int(size * s), 900)
        rows = T.wrap(d, text, f, int(840 * s))
        if len(rows) <= 2 and max(d.textlength(r, font=f) for r in rows) <= 840 * s:
            break
    a = int(255 * fade)
    for j, row in enumerate(rows):
        d.text((img.width / 2, (332 + j * size * 1.08) * s), row, font=f, fill=(255, 255, 255, a), anchor="mt",
               stroke_width=max(1, int(7 * s)), stroke_fill=(14, 14, 18, a))
    img.paste(layer, (0, 0), layer)


def label_font(text: str, s: float, width: float = 760) -> ImageFont.FreeTypeFont:
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    size = 74
    while size > 44 and d.textlength(text, font=T.LABEL(size)) > width:
        size -= 2
    return T.LABEL(int(size * s))


def callout(img: Image.Image, pin, text: str, age: float, fade: float, s: float, place, colour=YELLOW) -> None:
    """types.callout with the font shrunk to fit long names and a colour (red for the symptom and the trap)."""
    if age < 0 or fade <= 0:
        return
    alpha = int(255 * fade)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = label_font(text, 1.0)
    f = T.LABEL(int(f.size * s))
    full_w = d.textlength(text, font=f)
    elbow, side = (place[0][0] * s, place[0][1] * s), place[1]
    lead = min(1.0, age / 0.16)
    tip = (pin[0] + (elbow[0] - pin[0]) * lead, pin[1] + (elbow[1] - pin[1]) * lead)
    white = (255, 255, 255, int(alpha * 0.9))
    dark = (10, 10, 12, int(alpha * 0.55))
    r = 9 * s
    d.ellipse([pin[0] - r - 2 * s, pin[1] - r - 2 * s, pin[0] + r + 2 * s, pin[1] + r + 2 * s], outline=dark,
              width=max(2, int(2 * s)))
    d.ellipse([pin[0] - r, pin[1] - r, pin[0] + r, pin[1] + r], outline=white, width=max(2, int(2.5 * s)))
    d.ellipse([pin[0] - 2.5 * s, pin[1] - 2.5 * s, pin[0] + 2.5 * s, pin[1] + 2.5 * s], fill=white)
    d.line([pin, tip], fill=dark, width=max(2, int(4 * s)))
    T.dotted(d, pin, tip, s, white)
    if age > 0.16:
        grow = min(1.0, (age - 0.16) / 0.25)
        end = (elbow[0] + side * (full_w + 34 * s) * grow, elbow[1])
        d.line([elbow, end], fill=(255, 255, 255, int(alpha * 0.75)), width=max(1, int(2 * s)))
        shown = text[: int(round(len(text) * min(1.0, (age - 0.2) / 0.38)))] if age > 0.2 else ""
        if shown:
            x = elbow[0] + 6 * s if side > 0 else elbow[0] - 6 * s - d.textlength(shown, font=f)
            x = min(max(x, T.LABEL_X[0] * s), T.LABEL_X[1] * s - full_w) if side > 0 else max(x, T.LABEL_X[0] * s)
            d.text((x, elbow[1] - 6 * s), shown, font=f, fill=colour + (alpha,), anchor="ls",
                   stroke_width=max(2, int(4 * s)), stroke_fill=(12, 12, 14, int(alpha * 0.9)))
    shadow = layer.getchannel("A").filter(ImageFilter.GaussianBlur(6 * s))
    img.paste((0, 0, 0), mask=shadow.point(lambda a: a * 0.4))
    img.paste(layer, mask=layer)


def place(cover: np.ndarray, pin, text: str, s: float, top: int, bottom: int) -> tuple:
    """Where a label sits ((elbow x, y), side) in 1080 x 1920 units: over the least-covered gray near the pin,
    the whole name inside x 120-960 and y top..bottom (types.place_label, with a band to stay in)."""
    f = label_font(text, 1.0)
    text_w = ImageDraw.Draw(Image.new("L", (4, 4))).textlength(text, font=f)
    h, w = cover.shape
    k = 1080 / w
    best, score = None, 1e9
    for side in (1, -1):
        for ex in range(100, 1000, 20):
            x0, x1 = (ex, ex + text_w + 40) if side > 0 else (ex - text_w - 40, ex)
            t0, t1 = (ex + 6, ex + 6 + text_w) if side > 0 else (ex - 6 - text_w, ex - 6)
            if t0 < T.LABEL_X[0] or t1 > T.LABEL_X[1]:
                continue
            for ey in range(top, bottom, 20):
                if ey > 1100 and x1 > 900:
                    continue
                box = cover[int((ey - 80) / k): int((ey + 12) / k), int(x0 / k): int(x1 / k)]
                over = float(box.mean()) if box.size else 1.0
                dist = math.dist((ex, ey), (pin[0] / s, pin[1] / s)) / 1000
                sc = over * 4 + dist * 0.6
                if sc < score:
                    best, score = ((ex, ey), side), sc
    return best


def card(img: Image.Image, q: dict, age: float, s: float, state: str, t_state: float) -> None:
    """The choices card. state: "ask" (all plain), "answer" (the right row yellow, the rest dim), "trap" (and the
    trap's row red with a TRAP tag). age: seconds since it came in (it rises and fades in over 0.35 s)."""
    if age < 0:
        return
    f_in = min(1.0, age / 0.35)
    dy = (1 - f_in) ** 2 * 60
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = CARD
    y0, y1 = y0 + dy, y1 + dy
    a = int(255 * f_in)
    d.rounded_rectangle([x0 * s, y0 * s, x1 * s, y1 * s], radius=int(30 * s), fill=(248, 248, 250, int(238 * f_in)))
    qf = T.BOLD(int(38 * s))
    size = 38
    while d.textlength(q["question"], font=qf) > (x1 - x0 - 60) * s and size > 28:
        size -= 1
        qf = T.BOLD(int(size * s))
    d.text(((x0 + x1) / 2 * s, (y0 + 52) * s), q["question"], font=qf, fill=(20, 20, 24, a), anchor="mm")
    ans, trap = "ABCD".index(q["answer"]), "ABCD".index(q["trap"])
    row_h, gap = 64, 12
    for i, choice in enumerate(q["choices"]):
        ry = y0 + 100 + i * (row_h + gap)
        box = [(x0 + 28) * s, ry * s, (x1 - 28) * s, (ry + row_h) * s]
        fill, outline, ink, dim = (255, 255, 255), (200, 202, 208), (24, 24, 28), 1.0
        if state in ("answer", "trap"):
            g = min(1.0, t_state / 0.25) if state == "answer" else 1.0
            if i == ans:
                fill = tuple(int(255 + (c - 255) * g) for c in YELLOW)
                outline = tuple(int(200 + (c - 200) * g) for c in (196, 170, 20))
            elif not (state == "trap" and i == trap):
                dim = 1 - 0.6 * g
        if state == "trap" and i == trap:
            g = min(1.0, t_state / 0.25)
            outline = tuple(int(200 + (c - 200) * g) for c in RED)
        ra = int(a * dim)
        d.rounded_rectangle(box, radius=int(18 * s), fill=(*fill, ra), outline=(*outline, ra), width=max(2, int(3 * s)))
        cx, cy = (x0 + 70) * s, (ry + row_h / 2) * s
        d.ellipse([cx - 20 * s, cy - 20 * s, cx + 20 * s, cy + 20 * s], fill=(28, 28, 32, ra))
        d.text((cx, cy), "ABCD"[i], font=T.BOLD(int(24 * s)), fill=(255, 255, 255, ra), anchor="mm")
        cf = T.CAPTION(int(32 * s))
        csize = 32
        while d.textlength(choice, font=cf) > (x1 - x0 - 240) * s and csize > 22:
            csize -= 1
            cf = T.CAPTION(int(csize * s))
        d.text(((x0 + 108) * s, cy), choice, font=cf, fill=(*ink, ra), anchor="lm")
        if state in ("answer", "trap") and i == ans and (state == "trap" or t_state > 0):  # with the yellow
            d.text(((x1 - 60) * s, cy), "✓", font=T.font("Inter-ExtraBold.otf", int(36 * s)), fill=(20, 20, 24, a),
                   anchor="mm")
        if state == "trap" and i == trap and t_state > 0:
            g = min(1.0, t_state / 0.25)
            tf = T.BOLD(int(22 * s))
            tw = d.textlength("TRAP", font=tf)
            tx = (x1 - 50) * s
            chip = Image.new("RGBA", img.size, (0, 0, 0, 0))  # its own layer: drawing straight onto the row would
            cd = ImageDraw.Draw(chip)                        # punch a see-through hole in it while it fades in
            cd.rounded_rectangle([tx - tw - 24 * s, cy - 19 * s, tx, cy + 19 * s], radius=int(19 * s),
                                 fill=(*RED, int(a * g)))
            cd.text((tx - tw / 2 - 12 * s, cy), "TRAP", font=tf, fill=(255, 255, 255, int(a * g)), anchor="mm")
            layer.alpha_composite(chip)
    shadow = layer.getchannel("A").filter(ImageFilter.GaussianBlur(14 * s))
    img.paste((0, 0, 0), mask=shadow.point(lambda v: v * 0.25))
    img.paste(layer, (0, 0), layer)


def countdown(img: Image.Image, t: float, s: float, hand: Image.Image | None) -> None:
    """ "Comment your answer 👇" with a 3-2-1 ring, at the captions' place."""
    if t < 0 or t > COUNT:
        return
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = T.BOLD(int(38 * s))
    text = "Comment your answer"
    tw = d.textlength(text, font=f)
    ew = (hand.width + 10 * s) if hand else 0
    ring = 92 * s
    total = ring + 22 * s + tw + 48 * s + ew
    x = (CARD[0] + CARD[2]) / 2 * s - total / 2
    y = CAPTION_LOW * s
    n = COUNT - int(t)
    frac = t - int(t)
    cx = x + ring / 2
    d.ellipse([cx - ring / 2, y - ring / 2, cx + ring / 2, y + ring / 2], fill=(20, 20, 24, 235))
    d.arc([cx - ring / 2 + 6 * s, y - ring / 2 + 6 * s, cx + ring / 2 - 6 * s, y + ring / 2 - 6 * s], -90,
          -90 + 360 * (1 - frac), fill=YELLOW + (255,), width=max(2, int(7 * s)))
    pop = 1 + 0.25 * max(0.0, 1 - frac / 0.15)
    d.text((cx, y), str(n), font=T.BOLD(int(46 * s * pop)), fill=(255, 255, 255, 255), anchor="mm")
    px = x + ring + 22 * s
    d.rounded_rectangle([px, y - 38 * s, px + tw + 48 * s + ew, y + 38 * s], radius=int(38 * s),
                        fill=(255, 255, 255, 245))
    d.text((px + 24 * s, y), text, font=f, fill=(20, 20, 24, 255), anchor="lm")
    img.paste(layer, (0, 0), layer)
    if hand:
        bob = math.sin(t * 2 * math.pi * 1.5) * 4 * s
        img.paste(hand, (int(px + 24 * s + tw + 10 * s), int(y - hand.height / 2 + bob)), hand)


def caption_at(img: Image.Image, text: str, s: float, y: int, big: bool = False) -> None:
    if not big:
        T.caption(img, text, s, y)
        return
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = T.font("Montserrat.ttf", int(58 * s), 800)
    rows = T.wrap(d, text, f, int(760 * s))
    lh = int(70 * s)
    y0 = int(y * s) - lh * len(rows) // 2
    for i, row in enumerate(rows):
        d.text((480 * s, y0 + i * lh), row, font=f, fill=(255, 255, 255, 255), anchor="mt",
               stroke_width=max(2, int(5 * s)), stroke_fill=(10, 10, 12, 235))
    shadow = layer.getchannel("A").filter(ImageFilter.GaussianBlur(8 * s))
    img.paste((0, 0, 0), mask=shadow.point(lambda a: a * 0.4))
    img.paste(layer, mask=layer)


def layer_at(layer: Image.Image, k: float, s: float) -> tuple[Image.Image, tuple[float, float, float]]:
    """The 3D layer shrunk by k (1 = full screen) and moved up into ZONE as it shrinks; returns it and the map
    (scale, dx, dy) for pins."""
    if k >= 0.999:
        return layer, (1.0, 0.0, 0.0)
    W, H = layer.size
    small = layer.resize((max(1, int(W * k)), max(1, int(H * k))), Image.BILINEAR)
    g = (1 - k) / (1 - SMALL)
    cx = W / 2 + g * ((CARD[0] + CARD[2]) / 2 * s - W / 2)
    cy = H / 2 + g * ((ZONE[0] + ZONE[1]) / 2 * s - H / 2)
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ox, oy = int(cx - small.width / 2), int(cy - small.height / 2)
    out.paste(small, (ox, oy))
    return out, (k, ox, oy)


def smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


# --- sound -------------------------------------------------------------------------------------------------------
def tick(seed: int) -> np.ndarray:
    t = np.arange(int(0.08 * SR)) / SR
    x = np.sin(2 * np.pi * 1850 * t) * np.exp(-t * 90) + np.sin(2 * np.pi * 930 * t) * np.exp(-t * 60) * 0.5
    return (x / np.abs(x).max() * 0.35).astype(np.float32)


def chime() -> np.ndarray:
    """The reveal: two soft rising bell notes."""
    t = np.arange(int(0.9 * SR)) / SR
    out = np.zeros_like(t)
    for f0, at in ((659.25, 0.0), (987.77, 0.09)):
        tt = np.clip(t - at, 0, None)
        out += (np.sin(2 * np.pi * f0 * tt) + 0.3 * np.sin(2 * np.pi * f0 * 2 * tt)) * np.exp(-tt * 5) * (t >= at)
    return (out / np.abs(out).max() * 0.35).astype(np.float32)


def buzz() -> np.ndarray:
    """The trap: a short low two-note 'nope'."""
    t = np.arange(int(0.38 * SR)) / SR
    f = np.where(t < 0.16, 220, 165)
    x = np.sign(np.sin(2 * np.pi * f * t)) * 0.3 + np.sin(2 * np.pi * f * t)
    x = np.convolve(x, np.ones(30) / 30, mode="same") * np.exp(-t * 6)
    return (x / np.abs(x).max() * 0.22).astype(np.float32)


# --- render ------------------------------------------------------------------------------------------------------
def spec_for(q: dict, segs: list[dict], frames: int, out: Path, W: int, H: int, samples: int) -> dict:
    return {"root": str(ROOT), "out": str(out), "fps": FPS, "width": W, "height": H, "samples": samples,
            "frames": frames, "timeline": segs, "shows": q["shows"]}


def run_blender(spec: dict) -> None:
    r = subprocess.run(["nice", "-n", "10", blender(), "-b", "--factory-startup", "-t",
                        os.environ.get("BLENDER_THREADS", "4"), "--python", str(ROOT / "render" / "types_scene.py"),
                        "--", json.dumps(spec)], capture_output=True, text=True)
    if r.returncode or not (Path(spec["out"]) / "anchors.json").exists():
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("Blender failed")


def build(q: dict, out: Path, scale: float = 1.0, samples: int = 32, step: int = 1) -> float:
    W, H = int(1080 * scale), int(1920 * scale)
    s = scale
    work = Path(tempfile.mkdtemp(prefix="diagnose-"))
    lines = T.speak(q["script"], work / "voice")
    segs, cues, marks = plan(q, lines)
    frames = int(round(marks["end"] * FPS))
    spec = spec_for(q, segs, frames, work / "frames", W, H, samples)
    if step > 1:
        spec["only"] = list(range(0, frames, step))
    keep = os.environ.get("DIAGNOSE_CACHE")
    key = json.dumps({**spec, "out": ""}, sort_keys=True) + (ROOT / "render" / "types_scene.py").read_text()
    import hashlib
    key = hashlib.sha256(key.encode()).hexdigest()
    cached = Path(keep).expanduser() / q["id"] if keep else None
    if cached and (cached / "key.txt").exists() and (cached / "key.txt").read_text() == key:
        shutil.copytree(cached / "frames", work / "frames")
        print(f"{q['id']}: 3D frames from the cache", flush=True)
    else:
        run_blender(spec)
        if cached:
            shutil.rmtree(cached, ignore_errors=True)
            shutil.copytree(work / "frames", cached / "frames")
            (cached / "key.txt").write_text(key)
    anchors = {int(k): v for k, v in json.loads((work / "frames" / "anchors.json").read_text()).items()}
    back = T.studio(W, H, True)
    back2 = T.studio(W, H, False)
    hand = emoji("👇", int(54 * s))
    seg_of = lambda t: next((sg for sg in segs if sg["start"] <= t < sg["end"]), segs[-1])  # noqa: E731

    def size_at(t: float) -> float:
        """The 3D layer's size: full in the case and send shots, SMALL while the card is up (eased at the cuts)."""
        q0, sd = marks["question"], marks["send"]
        if t < q0 or t >= sd + 0.25:
            return 1.0 if t < q0 else 1.0
        a = smooth((t - q0) / 0.3) if t < q0 + 0.3 else 1.0
        b = smooth((t - sd) / 0.25) if t >= sd else 0.0
        return 1 - (1 - SMALL) * a * (1 - b)

    # where each shot's label sits: over the least-covered gray across the shot
    places: dict[str, tuple] = {}
    texts = {"case": q["symptom_label"], "answer": q["answer_label"], "trap": q["trap_label"]}

    def frame_layer(k: int) -> Image.Image:
        p = work / "frames" / f"{k:05d}.png"
        if not p.exists():  # a preview renders every step-th frame
            p = work / "frames" / f"{k - k % step:05d}.png"
        return Image.open(p).convert("RGBA")

    for sg in segs:
        if sg["name"] not in texts:
            continue
        a, b = int((sg["start"] + 0.4) * FPS), int(sg["end"] * FPS)
        acc, n = None, 0
        pin = None
        for k in range(a - a % step, b, max(3, step)):
            lay, (kk, ox, oy) = layer_at(frame_layer(k), size_at(k / FPS), s)
            al = np.asarray(lay.getchannel("A").resize((135, 240), Image.BILINEAR), np.float32) / 255
            acc = al if acc is None else acc + al
            n += 1
            if k in anchors and pin is None:
                xy = anchors[k]["xy"]
                pin = (xy[0] * kk + ox, xy[1] * kk + oy)
        top, bottom = (300, 1180) if sg["name"] == "case" else (ZONE[0] + 90, ZONE[1])  # names clear the header
        if sg["name"] == "case":
            top = 560  # under the hook title
        places[sg["name"]] = place(acc / max(1, n), pin or (W / 2, H / 2), texts[sg["name"]], s, top, bottom)

    tmp_video = work / "video.mp4"
    enc = subprocess.Popen([ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                            "-pix_fmt", "yuv420p", str(tmp_video)], stdin=subprocess.PIPE)
    cover = None
    for k in range(frames):
        t = k / FPS
        sg = seg_of(t)
        name = sg["name"]
        img = (back if name in ("case", "answer", "send") else back2).copy()
        i = segs.index(sg)
        if i and t < sg["start"] + T.WHIP:  # the light changes under the whip, as in Types
            prev = back if segs[i - 1]["name"] in ("case", "answer", "send") else back2
            img = Image.blend(prev, img, (t - sg["start"]) / T.WHIP)
        lay, (kk, ox, oy) = layer_at(frame_layer(k), size_at(t), s)
        img.paste(lay, mask=lay)
        a = anchors.get(k)
        fade = min(1.0, max(0.0, (sg["end"] - 0.12 - t) / 0.25))
        if a and name in texts and not a.get("small"):
            pin = (a["xy"][0] * kk + ox, a["xy"][1] * kk + oy)
            age = t - (sg["start"] + (0.25 if name == "case" else 0.45))
            callout(img, pin, texts[name], age, fade, s, places[name], YELLOW if name == "answer" else RED)
        if name == "case":
            banner(img, q["hook_title"], fade, s)
        if marks["question"] <= t < marks["send"] + 0.2:
            out_f = 1.0 if t < marks["send"] else max(0.0, 1 - (t - marks["send"]) / 0.2)
            state = "ask" if t < marks["answer"] else "answer" if t < marks["trap"] else "trap"
            t_state = t - (marks["answer"] + 0.35 if state == "answer" else marks["trap"] + 0.35 if state == "trap" else 0)
            sub = Image.new("RGB", img.size)
            sub.paste(img)
            card(img, q, t - marks["question"] - 0.15, s, state, max(0.0, t_state))
            if out_f < 1:
                img = Image.blend(sub, img, out_f)
        countdown(img, t - marks["count"], s, hand)
        cue = next((c for c in reversed(cues) if c["at"] - 0.05 <= t < c["at"] + lines[c["line"]][1] + 0.3), None)
        if name == "send":  # the send line holds alone to the end
            cue = next(c for c in cues if c["shot"] == "send")
            if t >= cue["at"] - 0.05:
                caption_at(img, cue["text"], s, 1335, big=True)
        elif cue and not (marks["count"] <= t < marks["count"] + COUNT):
            caption_at(img, cue["text"], s, T.CAPTION_Y if name == "case" else CAPTION_LOW)
        pill(img, "DIAGNOSE THIS", 250, s)
        T.watermark(img, s)
        if name == "question" and t >= marks["count"] + 0.2 and cover is None:
            # the cover: the question with its choices, no countdown, no caption (redrawn clean)
            cover_img = (back2).copy()
            cover_img.paste(lay, mask=lay)
            card(cover_img, q, 1.0, s, "ask", 0)
            pill(cover_img, "DIAGNOSE THIS", 250, s)
            banner_small = q["hook_title"]
            T.caption(cover_img, banner_small, s, CAPTION_LOW)
            T.watermark(cover_img, s)
            cover = cover_img
        enc.stdin.write(img.convert("RGB").tobytes())
    for _ in range(int(COVER_TAIL * FPS)):
        enc.stdin.write(cover.convert("RGB").tobytes())
    enc.stdin.close()
    enc.wait()
    total = frames / FPS + COVER_TAIL

    # sound: the narrator, a thud as the pain shows, a whoosh at every cut, ticks, a chime at the answer, a buzz
    # at the trap, an original track under it all, ducked under the voice
    buf = np.zeros(int((total + 1) * SR), np.float32)

    def add(x, at, gain=1.0):
        a0 = int(at * SR)
        buf[a0:a0 + len(x)] += x[: max(0, len(buf) - a0)] * gain

    for c in cues:
        v, sr = sf.read(lines[c["line"]][0], dtype="float32")
        if sr != SR:
            v = np.interp(np.arange(0, len(v), sr / SR), np.arange(len(v)), v).astype(np.float32)
        add(v, c["at"])
    add(T.thud(3), 0.12, 0.8)
    for sg in segs[1:]:
        add(T.whoosh(), sg["start"] - 0.05, 0.6)
    for j in range(COUNT):
        add(tick(j), marks["count"] + j, 0.9)
    add(chime(), marks["answer"] + 0.3, 0.9)
    add(buzz(), marks["trap"] + 0.3, 0.9)
    track = music.render(q["music"], total).mean(axis=1)
    voiced = np.zeros(len(track), bool)
    for c in cues:
        voiced[int(c["at"] * SR): int((c["at"] + lines[c["line"]][1]) * SR)] = True
    duck = np.convolve(np.where(voiced, 0.45, 1.0), np.ones(4410) / 4410, mode="same")
    buf[: len(track)] += (track * duck * 0.15).astype(np.float32)
    wav = work / "sound.wav"
    sf.write(wav, buf[: int(total * SR)], SR)
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(tmp_video), "-i", str(wav),
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    cover.convert("RGB").save(out.with_suffix(".jpg"), quality=92)
    shutil.rmtree(work, ignore_errors=True)
    return total


def stills(q: dict, folder: Path) -> None:
    """One half-size frame per shot, from a dummy timeline (no voice): checks the framing of every show."""
    folder.mkdir(parents=True, exist_ok=True)
    segs, t = [], 0.0
    for shot in SHOTS:
        segs.append({"kind": "type", "name": shot, "start": t, "end": t + 3.0, "whip_in": shot != "case",
                     "crack": 0.1 if shot == "case" else 0.3 if shot != "question" else 999})
        t += 3.0
    frames = int(t * FPS)
    work = Path(tempfile.mkdtemp(prefix="diagnose-stills-"))
    spec = spec_for(q, segs, frames, work, 540, 960, 12)
    spec["only"] = [int((i * 3.0 + 1.6) * FPS) for i in range(len(SHOTS))]
    run_blender(spec)
    for shot, k in zip(SHOTS, spec["only"]):
        img = T.studio(540, 960, True)
        lay = Image.open(work / f"{k:05d}.png").convert("RGBA")
        img.paste(lay, mask=lay)
        img.save(folder / f"{q['id']}_{shot}.png")
    shutil.rmtree(work, ignore_errors=True)


def info(q: dict, seconds: float) -> dict:
    """What the posting job needs (anatomy/series.py); "hold" waits for Yashas's OK."""
    return {"id": q["id"], "format": "diagnose", "title": q["title"], "hook": T.shown(" ".join(q["lines"]["case"])),
            "question": q["question"], "choices": q["choices"], "answer": q["answer"], "why": q["why"],
            "seconds": round(seconds, 2), "music": q["music"], "hashtags": q["hashtags"][:5], "sources": q["sources"],
            "send": q["send"], "credit": q["credit"], "hold": True}


def with_music(q: dict) -> dict:
    return {**q, "music": q.get("music") or music.pick(zlib.crc32(q["id"].encode()), styles=CONFIG.get("music_styles"))}


def release(folder: Path, ids: list[str], scale: float = 1.0, step: int = 1) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for q in items():
        if ids and q["id"] not in ids:
            continue
        q = with_music(q)
        t = time.time()
        seconds = build(q, folder / f"{q['id']}.mp4", scale=scale, samples=32 if scale == 1.0 else 12, step=step)
        if scale == 1.0 and step == 1:
            (folder / f"{q['id']}.json").write_text(json.dumps(info(q, seconds), indent=1, ensure_ascii=False) + "\n")
        print(f"{q['id']}: {seconds:.1f} s video, {q['music']}, rendered in {time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["say"] and len(a) == 2:
        T.word_check(item(a[1]))
    elif a[:1] == ["stills"] and len(a) == 3:
        stills(item(a[1]), Path(a[2]).expanduser())
    elif a[:1] == ["preview"] and len(a) == 3:
        release(Path(a[2]).expanduser(), [a[1]], scale=0.5, step=3)
    elif a[:1] == ["release"] and len(a) >= 2:
        release(Path(a[1]).expanduser(), a[2:])
    else:
        raise SystemExit(__doc__)
