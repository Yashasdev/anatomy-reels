"""The "types" format: one bone, every way it can break ("11 types of fracture"), copied from the studio-style
breakdowns that do well on Instagram. Rendered ahead on a Mac and posted in the rotating formats slots.

    python -m anatomy.types release DIR [ids...]   # render each item in banks/types/ into DIR (<id>.mp4 + .json)
    python -m anatomy.types preview ID DIR         # half size, quick: check the timing and labels

The shot list, second by second (all timings come from the narration):
  0-3 s   the hook: the whole femur breaks a different way every half second, chips flying, tiny labels
  3-6 s   extreme close-up on the head of the femur, pulling back to the whole bone ("Here are 11 types...")
  then per type: the intact bone whips in from the right, breaks (chips burst, a crack sound), the camera pushes in
          slowly while the bone turns a little, a yellow label types itself in, pinned to the break by a dotted
          line, white captions read the definition; then the bone whips out to the left
  end     pull far back, then the chart: every fracture in rows of 4, 4 and 3 with its name; the last frame is
          the cover
Background: a gray studio gradient, lighter and darker on alternate types; black for the chart.
"""

from __future__ import annotations

import json
import math
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
import re

from .make import KOKORO, MODEL_URL, blender, ffmpeg

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
CONFIG = json.loads((ROOT / "config.json").read_text())
FPS, SR = 30, 44100
VOICE, SPEED = "af_heart", 1.0
YELLOW = (246, 222, 64)
FLASH, INTRO_MIN, TYPE_MIN, WHIP, OUTRO, COVER_TAIL = 2.9, 3.0, 3.4, 0.27, 0.8, 0.5
SAY_AT = 0.32  # each type's name is said just as the bone breaks (the break is at 0.45 s)
CAPTION_Y, CAPTION_W = 1335, 720  # inside the phone's safe area: the like/comment column covers x > 900 down here


def items() -> list[dict]:
    """Every video in banks/types/, with its script in speaking order: hook, intro, each type's lines, outro."""
    out = []
    for p in sorted((ROOT / "banks" / "types").glob("*.json")):
        for q in json.loads(p.read_text()):
            out.append({**q, "script": [q["hook"], q["intro"]] + [x for t in q["types"] for x in t["lines"]] + [q["outro"]]})
    return out


def font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / name), size)
    if weight is not None:
        f.set_variation_by_axes([weight])
    return f


LABEL = lambda s: font("Teko.ttf", s, 560)  # noqa: E731  condensed, like the reference's callouts
CAPTION = lambda s: font("Montserrat.ttf", s, 620)  # noqa: E731
BOLD = lambda s: font("Montserrat.ttf", s, 800)  # noqa: E731


# --- voice -------------------------------------------------------------------------------------------------
# Script lines carry light markup, so the narrator says them right:
#   [word](phonemes)   say the word with these phonemes (Kokoro's own guess is wrong for some medical words)
#   *word*             a slight lean: the word gets the line's main stress and the words around it are kept
#                      light. Nothing is stretched or pitched (Yashas, Nov 10: stretched vowels and a pasted-in,
#                      pitched-up "you" sounded wrong; he wants slight emphasis)
MARKUP = re.compile(r"\*(.+?)\*|\[(.+?)\]\((.+?)\)")


def shown(line: str) -> str:
    """The line as the captions show it, without the markup."""
    return MARKUP.sub(lambda m: m.group(1) or m.group(2), line)


def stressed(ph: str) -> str:
    """Primary stress on the word (secondary stress becomes primary; an unstressed word gets it at the start)."""
    ph = ph.replace("ˌ", "ˈ")
    return ph if "ˈ" in ph else "ˈ" + ph


def _find(full: str, word_ph: str, start: int) -> tuple[int, int]:
    """Where a word's phonemes sit in the line's, ignoring stress marks; whole words only."""
    bare = word_ph.replace("ˈ", "").replace("ˌ", "").rstrip(".,?!")
    pattern = "".join("[ˈˌ]?" + re.escape(ch) for ch in bare)
    m = re.compile(r"(?:(?<=\s)|^)" + pattern + r"(?=[\s.,?!]|$)").search(full, start)
    if not m:
        raise ValueError(f"can't find {word_ph!r} in {full!r}; mark a different word")
    return m.start(), m.end()


def phonemes(k, line: str) -> str:
    """The line as Kokoro phonemes. The whole line is phonemized at once (so "a" stays "uh"), then the marked
    words are swapped in; next to a leaned-on word, the neighbouring words lose their main stress."""
    full = k.tokenizer.phonemize(shown(line), "en-us").strip()
    pos = 0
    for m in MARKUP.finditer(line):
        word = m.group(1) or m.group(2)
        i, j = _find(full, k.tokenizer.phonemize(word, "en-us").strip(), pos)
        if m.group(1):
            a = full.rfind(" ", 0, max(0, full.rfind(" ", 0, i)))  # the word before, kept light
            b = full.find(" ", j + 1)
            b = len(full) if b < 0 else b  # and the word after
            lo, hi = max(a, 0), b
            new_word = stressed(full[i:j])
            full = full[:lo] + full[lo:i].replace("ˈ", "ˌ") + new_word + full[j:hi].replace("ˈ", "ˌ") + full[hi:]
            pos = lo + len(full[lo:i]) + len(new_word)
        else:
            full = full[:i] + m.group(3) + full[j:]
            pos = i + len(m.group(3))
    return full


def _trim(x: np.ndarray) -> np.ndarray:
    loud = np.flatnonzero(np.abs(x) > 0.01)
    return x[max(loud[0] - 200, 0): loud[-1] + 600] if len(loud) else x


def speak(texts: list[str], out: Path, voice: str = VOICE, speed: float = SPEED) -> list[tuple[Path, float]]:
    """Like make.voice_lines, but reading the markup above."""
    import urllib.request

    from kokoro_onnx import Kokoro
    KOKORO.mkdir(parents=True, exist_ok=True)
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        if not (KOKORO / name).exists():
            urllib.request.urlretrieve(MODEL_URL + name, KOKORO / name)
    k = Kokoro(str(KOKORO / "kokoro-v1.0.onnx"), str(KOKORO / "voices-v1.0.bin"))
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, t in enumerate(texts):
        x, sr = k.create(phonemes(k, t), voice=voice, speed=speed, lang="en-us", is_phonemes=True)
        x = _trim(np.asarray(x, np.float32))
        path = out / f"line{i:02d}.wav"
        sf.write(path, x, sr)
        lines.append((path, len(x) / sr))
    return lines


# --- timeline ----------------------------------------------------------------------------------------------
def plan(q: dict, lines: list[tuple[Path, float]], gap: float = 0.22) -> tuple[list[dict], list[dict], float]:
    """Segments for Blender and the narration cues (line index, start, text), from how long each line takes."""
    k = 0
    cues, segs = [], []

    def say(at: float) -> float:
        nonlocal k
        cues.append({"line": k, "at": at, "text": shown(q["script"][k])})
        end = at + lines[k][1]
        k += 1
        return end

    t = say(0.12)
    segs.append({"kind": "flash", "start": 0.0, "end": FLASH, "types": q["flash"]})
    end = say(FLASH + 0.15)
    segs.append({"kind": "intro", "start": FLASH, "end": max(FLASH + INTRO_MIN, end + 0.35)})
    t = segs[-1]["end"]
    for i, ty in enumerate(q["types"]):
        at = t + SAY_AT
        for _ in ty["lines"]:
            at = say(at) + gap
        seg_end = max(t + TYPE_MIN, at - gap + 0.25 + WHIP)
        segs.append({"kind": "type", "name": ty["name"], "label": ty["label"], "start": t, "end": seg_end,
                     "whip_in": i > 0})
        t = seg_end
    segs.append({"kind": "outro", "start": t, "end": t + OUTRO})
    t += OUTRO
    end = say(t + 0.3)
    segs.append({"kind": "grid", "start": t, "end": max(t + 4.0, end + 1.6)})
    assert k == len(q["script"]), "every script line is said once"
    return segs, cues, segs[-1]["end"]


# --- drawing -----------------------------------------------------------------------------------------------
def studio(w: int, h: int, light: bool, black: bool = False) -> Image.Image:
    """The gray studio sweep: brighter in the middle, falling off to the corners."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((x - w * 0.5) / (w * 0.75)) ** 2 + ((y - h * 0.42) / (h * 0.62)) ** 2)
    if black:
        hi, lo = np.array([62, 64, 68]), np.array([4, 4, 6])
        r = np.sqrt(((x - w * 0.5) / (w * 0.55)) ** 2 + ((y - h * 0.4) / (h * 0.42)) ** 2)
    elif light:
        hi, lo = np.array([150, 154, 162]), np.array([86, 90, 98])
    else:
        hi, lo = np.array([112, 116, 124]), np.array([34, 36, 42])
    k = np.clip(r, 0, 1)[..., None] ** 1.4
    img = hi * (1 - k) + lo * k
    img += np.random.default_rng(3).normal(0, 1.2, img.shape)  # a little grain so the gradient doesn't band
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def wrap(d: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    out, cur = [], ""
    for word in text.split():
        nxt = f"{cur} {word}".strip()
        if d.textlength(nxt, font=f) <= width or not cur:
            cur = nxt
        else:
            out.append(cur)
            cur = word
    return out + [cur] if cur else out


def caption(img: Image.Image, text: str, s: float, y: int = CAPTION_Y) -> None:
    """White captions with a dark outline, centred low on the screen."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = CAPTION(int(52 * s))
    rows = wrap(d, text, f, int(CAPTION_W * s))
    lh = int(62 * s)
    y0 = int(y * s) - lh * len(rows) // 2
    for i, row in enumerate(rows):
        d.text((img.width / 2, y0 + i * lh), row, font=f, fill=(255, 255, 255, 255), anchor="mt",
               stroke_width=max(2, int(4 * s)), stroke_fill=(10, 10, 12, 235))
    shadow = layer.getchannel("A").filter(ImageFilter.GaussianBlur(6 * s))
    img.paste((0, 0, 0), mask=shadow.point(lambda a: a * 0.35))
    img.paste(layer, mask=layer)


def dotted(d: ImageDraw.ImageDraw, a, b, s: float, fill) -> None:
    n = max(1, int(math.dist(a, b) / (9 * s)))
    for i in range(0, n, 2):
        p = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
        q = (a[0] + (b[0] - a[0]) * (i + 1) / n, a[1] + (b[1] - a[1]) * (i + 1) / n)
        d.line([p, q], fill=fill, width=max(1, int(2 * s)))


def callout(img: Image.Image, pin, text: str, age: float, fade: float, s: float) -> None:
    """The yellow label: the pin ring, a dotted leader up to a thin rule, and the name typing in above it."""
    if age < 0:
        return
    alpha = int(255 * fade)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = LABEL(int(74 * s))
    full_w = d.textlength(text, font=f)
    side = 1 if pin[0] + (110 + 40) * s + full_w <= 900 * s else -1  # keep it clear of the right-hand buttons
    # the label stays above the captions and below the app's top bar, however low or high the break is
    elbow = (pin[0] + side * 110 * s, min(max(pin[1] - 150 * s, 270 * s), (CAPTION_Y - 170) * s))
    lead = min(1.0, age / 0.16)
    tip = (pin[0] + (elbow[0] - pin[0]) * lead, pin[1] + (elbow[1] - pin[1]) * lead)
    white = (255, 255, 255, int(alpha * 0.9))
    r = 9 * s
    d.ellipse([pin[0] - r, pin[1] - r, pin[0] + r, pin[1] + r], outline=white, width=max(2, int(2.5 * s)))
    d.ellipse([pin[0] - 2.5 * s, pin[1] - 2.5 * s, pin[0] + 2.5 * s, pin[1] + 2.5 * s], fill=white)
    dotted(d, pin, tip, s, white)
    if age > 0.16:
        grow = min(1.0, (age - 0.16) / 0.25)
        rule = (full_w + 34 * s) * grow
        end = (elbow[0] + side * rule, elbow[1])
        d.line([elbow, end], fill=(255, 255, 255, int(alpha * 0.75)), width=max(1, int(2 * s)))
        shown = text[: int(round(len(text) * min(1.0, (age - 0.2) / 0.38)))] if age > 0.2 else ""
        if shown:
            x = elbow[0] + 6 * s if side > 0 else elbow[0] - 6 * s - d.textlength(shown, font=f)
            d.text((x, elbow[1] - 6 * s), shown, font=f, fill=YELLOW + (alpha,), anchor="ls",
                   stroke_width=max(1, int(1.5 * s)), stroke_fill=(40, 34, 0, int(alpha * 0.5)))
    img.paste(layer, mask=layer)


def small_label(img: Image.Image, pin, text: str, s: float) -> None:
    d = ImageDraw.Draw(img)
    d.text((pin[0] + 40 * s, pin[1] - 4 * s), text, font=CAPTION(int(22 * s)), fill=(225, 228, 234), anchor="lm")


def watermark(img: Image.Image, s: float) -> None:
    """Our mark where the reference has its logo: a hairline from the top and the name under it."""
    d = ImageDraw.Draw(img)
    x = 58 * s
    d.line([(x, 0), (x, 150 * s)], fill=(235, 238, 242), width=max(1, int(2 * s)))
    for i, word in enumerate(("ANATOMY", "ACE")):
        d.text((x, 166 * s + i * 24 * s), word, font=BOLD(int(19 * s)), fill=(235, 238, 242), anchor="mt")


# --- sound -------------------------------------------------------------------------------------------------
def snap(seed: int) -> np.ndarray:
    """A bone snapping: a sharp crack, a few splinter clicks and a low thump."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(0.45 * SR)) / SR
    crack = rng.uniform(-1, 1, len(t)) * np.exp(-t * 55)
    crack = np.diff(np.concatenate([[0], crack]))  # brighter
    thump = np.sin(2 * np.pi * 75 * t) * np.exp(-t * 22) * 0.7
    out = crack * 1.4 + thump
    for _ in range(5):
        a = int(rng.uniform(0.01, 0.12) * SR)
        n = int(0.006 * SR)
        out[a:a + n] += rng.uniform(-1, 1, n) * np.exp(-np.arange(n) / (n / 4)) * 0.6
    return (out / np.abs(out).max() * 0.55).astype(np.float32)


def whoosh(length: float = 0.32) -> np.ndarray:
    n = int(length * SR)
    x = np.random.default_rng(7).uniform(-1, 1, n)
    x = np.convolve(x, np.ones(12) / 12, mode="same")  # softer
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return (x * env * 0.5).astype(np.float32)


# --- render ------------------------------------------------------------------------------------------------
def build(q: dict, out: Path, scale: float = 1.0, samples: int = 48) -> float:
    W, H = int(1080 * scale), int(1920 * scale)
    work = Path(tempfile.mkdtemp(prefix="types-"))
    lines = speak(q["script"], work / "voice")
    segs, cues, length = plan(q, lines)
    frames = int(round(length * FPS))
    spec = {"root": str(ROOT), "out": str(work / "frames"), "fps": FPS, "width": W, "height": H,
            "samples": samples, "frames": frames, "timeline": segs}
    r = subprocess.run([blender(), "-b", "--factory-startup", "--python", str(ROOT / "render" / "fracture_scene.py"),
                        "--", json.dumps(spec)], capture_output=True, text=True)
    if r.returncode or not (work / "frames" / "anchors.json").exists():
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("Blender failed")
    anchors = {int(k): v for k, v in json.loads((work / "frames" / "anchors.json").read_text()).items()}
    labels = {t["name"]: t["label"] for t in q["types"]}

    backs = {"light": studio(W, H, True), "dark": studio(W, H, False), "black": studio(W, H, False, black=True)}
    which = []
    for i, sg in enumerate(segs):  # alternate light and dark studio per type, black for the chart
        which.append("black" if sg["kind"] == "grid" else "light" if sg["kind"] != "type" else ("light", "dark")[i % 2])

    def seg_at(t: float) -> int:
        return next((i for i, sg in enumerate(segs) if sg["start"] <= t < sg["end"]), len(segs) - 1)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_video = work / "video.mp4"
    enc = subprocess.Popen([ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                            "-pix_fmt", "yuv420p", str(tmp_video)], stdin=subprocess.PIPE)
    last = None
    for k in range(frames):
        t = k / FPS
        i = seg_at(t)
        sg = segs[i]
        img = backs[which[i]].copy()
        if sg["kind"] == "type" and t < sg["start"] + WHIP and i > 0 and segs[i - 1]["kind"] == "type":
            # the studio light changes during the whip, so the cut hides in the motion blur
            a = (t - sg["start"]) / WHIP
            img = Image.blend(backs[which[i - 1]], backs[which[i]], a)
        layer = Image.open(work / "frames" / f"{k:05d}.png").convert("RGBA")
        img.paste(layer, mask=layer)
        a = anchors.get(k)
        if a and "grid" in a:
            d = ImageDraw.Draw(img)
            fade = min(1.0, (t - sg["start"]) / 0.5)
            col = tuple(int(255 * fade) for _ in range(3))
            d.text((W / 2, 300 * scale), q["grid_title"], font=BOLD(int(46 * scale)), fill=col, anchor="mm")
            for g in a["grid"]:
                for j, word in enumerate(labels[g["label"]].title().split()):
                    d.text((g["xy"][0], g["xy"][1] + j * 26 * scale), word, font=BOLD(int(20 * scale)),
                           fill=col, anchor="mt")
        elif a and a.get("small"):
            small_label(img, a["xy"], labels[a["label"]], scale)
        elif a:
            crack = sg["start"] + 0.45
            fade = min(1.0, max(0.0, (sg["end"] - 0.12 - t) / 0.25))
            callout(img, a["xy"], labels[a["label"]], t - crack - 0.12, fade, scale)
        cue = next((c for c in reversed(cues) if c["at"] - 0.05 <= t < c["at"] + lines[c["line"]][1] + 0.35), None)
        if cue:
            caption(img, cue["text"], scale, 1480 if sg["kind"] == "grid" else CAPTION_Y)
        watermark(img, scale)
        enc.stdin.write(img.tobytes())
        last = img
    for _ in range(int(COVER_TAIL * FPS)):  # the chart holds for the cover
        enc.stdin.write(last.tobytes())
    enc.stdin.close()
    enc.wait()
    total = frames / FPS + COVER_TAIL

    # sound: the narrator, a snap at every break, a whoosh at every cut, an original track under it all
    buf = np.zeros(int((total + 1) * SR), np.float32)

    def add(x, at, gain=1.0):
        a = int(at * SR)
        buf[a:a + len(x)] += x[: max(0, len(buf) - a)] * gain

    for c in cues:
        v, sr = sf.read(lines[c["line"]][0], dtype="float32")
        if sr != SR:
            v = np.interp(np.arange(0, len(v), sr / SR), np.arange(len(v)), v).astype(np.float32)
        add(v, c["at"])
    for sg in segs:
        if sg["kind"] == "flash":
            for j in range(len(sg["types"])):
                add(snap(j), sg["start"] + j * (sg["end"] - sg["start"]) / len(sg["types"]) + 1 / FPS, 0.55)
        if sg["kind"] == "type":
            add(snap(zlib.crc32(sg["name"].encode())), sg["start"] + 0.45, 0.8)
            add(whoosh(), sg["end"] - WHIP - 0.05, 0.7)
        if sg["kind"] == "intro":
            add(whoosh(0.6), sg["start"], 0.4)
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
    last.save(out.with_suffix(".jpg"), quality=92)
    shutil.rmtree(work, ignore_errors=True)
    return total


def info(q: dict, seconds: float) -> dict:
    """What the posting job needs (anatomy/series.py), like the other formats' <id>.json."""
    return {"id": q["id"], "format": "types", "title": q["title"], "hook": shown(q["script"][0]), "question": q["question"],
            "choices": [], "answer": "", "why": q["why"], "seconds": round(seconds, 2), "music": q["music"],
            "hashtags": q["hashtags"][:5], "sources": q["sources"], "credit": q["credit"]}


def release(folder: Path, ids: list[str], scale: float = 1.0) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for q in items():
        if ids and q["id"] not in ids:
            continue
        q = {**q, "music": q.get("music") or music.pick(zlib.crc32(q["id"].encode()), styles=CONFIG.get("music_styles"))}
        t = time.time()
        seconds = build(q, folder / f"{q['id']}.mp4", scale=scale, samples=32 if scale == 1.0 else 12)
        (folder / f"{q['id']}.json").write_text(json.dumps(info(q, seconds), indent=1, ensure_ascii=False) + "\n")
        print(f"{q['id']}: {seconds:.1f} s video, {q['music']}, rendered in {time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["release"] and len(sys.argv) >= 3:
        release(Path(sys.argv[2]).expanduser(), sys.argv[3:])
    elif sys.argv[1:2] == ["preview"] and len(sys.argv) == 4:
        release(Path(sys.argv[3]).expanduser(), [sys.argv[2]], scale=0.5)
    else:
        raise SystemExit(__doc__)
