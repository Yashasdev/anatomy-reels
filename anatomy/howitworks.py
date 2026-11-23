"""The "How it works on your body" format: an everyday product explained at body level ("Deodorant vs
antiperspirant"), after TheBrainMaze's macro explainers: realistic close-ups of skin in the gray studio of "types",
one idea per shot, slow motion, outlined captions, a closing chart. Posted with the types videos (format "types",
so the caption reads the same: hook, the comment question, the send line).

    python -m anatomy.howitworks release DIR [ids...]  # render each item in banks/howitworks/ into DIR (<id>.mp4 + .json)
    python -m anatomy.howitworks preview ID DIR        # half size, few samples: check timing and labels
    python -m anatomy.howitworks stills ID OUT.png [shot@fraction ...]  # a few full-size frames side by side
    python -m anatomy.howitworks say ID                # voice the script and print what whisper hears

An item (banks/howitworks/*.json) has "lines" (the narration, with types.py's pronunciation markup), "shots" (which
lines each 3D shot covers; render/skin_scene.py draws the shots and times every event from the lines), "labels"
(yellow callouts: text, the scene's pin, from/to as [line, seconds after it starts]) and "chart" (the closing cards,
each a frame of the video at a fraction of one shot). Voice, captions, labels and the mark are the types format's.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw

from . import music
from .make import blender, ffmpeg
from .types import (BOLD, CAPTION, CAPTION_Y, CONFIG, FPS, SR, callout, chart_label, heard, shown, speak, studio,
                    thud, watermark, whoosh)

ROOT = Path(__file__).resolve().parent.parent
GAP = 0.36  # between lines (types uses 0.42; this one has more lines)
SEND_HOLD = 2.0  # the send line stays on screen this long after it's said
COVER_TAIL = 0.5
ORDER = ("stick", "surface", "apocrine", "deodorant", "eccrine", "renew", "night", "calm", "chart")
CHART_TOP, CHART_BOTTOM, CHART_Y = 400, 1180, 1335


def items() -> list[dict]:
    return [q for p in sorted((ROOT / "banks" / "howitworks").glob("*.json")) for q in json.loads(p.read_text())]


def item(qid: str) -> dict:
    return next(q for q in items() if q["id"] == qid)


def plan(q: dict, lines: list[tuple[Path, float]]) -> tuple[list[dict], list[dict], float]:
    """Narration cues (line, at, dur) and the shots (kind, start, end), from how long each line takes."""
    cues, t = [], 0.1
    first = {min(v): k for k, v in q["shots"].items()}
    for i, (_, dur) in enumerate(lines):
        if i in first and i:
            t += 0.2  # a beat when the picture moves on
        cues.append({"line": i, "at": round(t, 3), "dur": round(dur, 3)})
        t += dur + GAP
    length = cues[-1]["at"] + cues[-1]["dur"] + SEND_HOLD
    shots = []
    for kind in ORDER:
        ls = q["shots"][kind]
        start = 0.0 if kind == ORDER[0] else cues[min(ls)]["at"] - 0.2
        shots.append({"kind": kind, "start": round(start, 3)})
    for a, b in zip(shots, shots[1:]):
        a["end"] = b["start"]
    shots[-1]["end"] = length
    return shots, cues, length


def render3d(q: dict, shots, cues, frames: int, out: Path, W: int, H: int, samples: int, only=None) -> None:
    spec = {"root": str(ROOT), "out": str(out), "fps": FPS, "width": W, "height": H, "samples": samples,
            "frames": frames, "shots": shots, "cues": cues}
    if only:
        spec["only"] = only
    r = subprocess.run([blender(), "-b", "--factory-startup", "-t", os.environ.get("BLENDER_THREADS", "4"),
                        "--python", str(ROOT / "render" / "skin_scene.py"), "--", json.dumps(spec)],
                       capture_output=True, text=True)
    if r.returncode or not (out / "anchors.json").exists() or (not only and len(list(out.glob("*.png"))) < frames):
        print(r.stdout[-4000:], r.stderr[-3000:])
        raise SystemExit("Blender failed")


def at(cues, ref) -> float:
    line, dt = ref
    return cues[line]["at"] + dt


def shot_of(shots, t):
    return next((s for s in shots if s["start"] <= t < s["end"]), shots[-1])


def compose(q: dict, k: int, frames_dir: Path, anchors: dict, shots, cues, s: float, back: Image.Image,
            thumbs: list | None = None) -> Image.Image:
    """One finished frame: studio, the 3D layer, the label for this moment, the caption, the mark."""
    t = k / FPS
    img = back.copy()
    sh = shot_of(shots, t)
    if sh["kind"] != "chart":
        layer = Image.open(frames_dir / f"{k:05d}.png").convert("RGBA")
        if layer.size != img.size:
            layer = layer.resize(img.size, Image.LANCZOS)
        img.paste(layer, mask=layer)
    a = anchors.get(str(k)) or anchors.get(k)
    for lb in q.get("labels", []):
        t0, t1 = at(cues, lb["from"]), at(cues, lb["to"])
        if a and t0 <= t < t1 + 0.25:
            fade = min(1.0, max(0.0, (t1 + 0.25 - t) / 0.25))
            pin = a[lb["pin"]]
            if not (60 * s < pin[0] < 1020 * s and 200 * s < pin[1] < 1250 * s):
                continue
            callout(img, pin, lb["text"], t - t0, fade, s, clamp=True, place=label_spot(pin, lb["text"], s))
    if sh["kind"] == "chart":
        cards(img, q, thumbs or [], t - sh["start"], s)
    cue = next((c for c in reversed(cues) if c["at"] - 0.05 <= t < c["at"] + c["dur"] + (SEND_HOLD if c is cues[-1] else 0.35)), None)
    if cue:
        from .types import caption
        caption(img, shown(q["lines"][cue["line"]]), s, CHART_Y if sh["kind"] == "chart" else CAPTION_Y)
    watermark(img, s)
    return img


def label_spot(pin, text: str, s: float) -> tuple:
    """Above the pin and to whichever side has room, inside x 120-960 and clear of the captions."""
    from .types import LABEL
    w = ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(text, font=LABEL(74))
    px, py = pin[0] / s, pin[1] / s
    ey = min(max(py - 170, 400), CAPTION_Y - 190)  # below the ANATOMY ACE mark (y 258-300)
    side = 1 if px + 90 + w + 40 <= 960 else -1
    ex = px + 90 if side > 0 else px - 90
    if side < 0 and ex - w - 10 < 120:
        ex = 120 + w + 10
    return (ex, ey), side


def cards(img: Image.Image, q: dict, thumbs: list[Image.Image], age: float, s: float) -> None:
    """The closing chart: the title, then a card per answer popping in, a frame of the video in each."""
    d = ImageDraw.Draw(img)
    f = min(1.0, age / 0.5)
    col = tuple(int(255 * f) for _ in range(3))
    d.text((540 * s, 330 * s), q["chart_title"], font=BOLD(int(50 * s)), fill=col, anchor="mm")
    n = len(q["chart"])
    lo, hi, gap = 90, 900, 22  # clear of the like/comment column below y 1100
    w = (hi - lo - gap * (n - 1)) / n
    h = CHART_BOTTOM - CHART_TOP - 120
    for i, (card, th) in enumerate(zip(q["chart"], thumbs)):
        g = min(1.0, max(0.0, (age - 0.2 - 0.18 * i) / 0.35))
        if g <= 0:
            continue
        x0 = lo + i * (w + gap)
        box = (int(x0 * s), int(CHART_TOP * s), int((x0 + w) * s), int((CHART_TOP + h) * s))
        pic = th.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
        mask = Image.new("L", pic.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, pic.width - 1, pic.height - 1], radius=int(22 * s), fill=int(255 * g))
        img.paste(pic, box[:2], mask)
        ImageDraw.Draw(img).rounded_rectangle(box, radius=int(22 * s), outline=(235, 238, 242), width=max(1, int(2 * s)))
        chart_label(ImageDraw.Draw(img), ((x0 + w / 2) * s, (CHART_TOP + h + 18) * s), [card["name"]] + card["lines"], g, s, w)


def thumbs_for(q: dict, frames_dir: Path, shots, back: Image.Image, s: float) -> list[Image.Image]:
    """A frame of the video per chart card (the 3D layer over the studio), cropped to a tall card."""
    out = []
    for card in q["chart"]:
        sh = next(x for x in shots if x["kind"] == card["shot"])
        k = int((sh["start"] + (sh["end"] - sh["start"]) * card["at"]) * FPS)
        img = back.copy()
        layer = Image.open(frames_dir / f"{k:05d}.png").convert("RGBA").resize(img.size, Image.LANCZOS)
        img.paste(layer, mask=layer)
        W, H = img.size
        cw, ch = int(W * 0.55), int(H * 0.62)
        x0, y0 = (W - cw) // 2, int(H * 0.12)
        out.append(img.crop((x0, y0, x0 + cw, y0 + ch)))
    return out


def sound(q: dict, shots, cues, lines, total: float, out: Path) -> None:
    buf = np.zeros(int((total + 1) * SR), np.float32)

    def add(x, t, gain=1.0):
        a = int(t * SR)
        buf[a:a + len(x)] += x[: max(0, len(buf) - a)] * gain

    for c in cues:
        v, sr = sf.read(lines[c["line"]][0], dtype="float32")
        if sr != SR:
            v = np.interp(np.arange(0, len(v), sr / SR), np.arange(len(v)), v).astype(np.float32)
        add(v, c["at"])
    starts = {s["kind"]: s["start"] for s in shots}
    add(whoosh(), starts["surface"] - 0.12, 0.6)  # the whip from the stick into the skin
    for kind in ("apocrine", "eccrine", "calm"):  # moving to a new part of the skin
        add(whoosh(0.6), starts[kind], 0.3)
    add(thud(3), cues[7]["at"] + 0.45, 0.45)  # the salts land
    add(thud(5), cues[8]["at"] + 0.6, 0.35)  # the plug sets
    add(whoosh(0.5), starts["chart"], 0.35)
    track = music.render(q["music"], total).mean(axis=1)
    voiced = np.zeros(len(track), bool)
    for c in cues:
        voiced[int(c["at"] * SR): int((c["at"] + c["dur"]) * SR)] = True
    duck = np.convolve(np.where(voiced, 0.45, 1.0), np.ones(4410) / 4410, mode="same")
    buf[: len(track)] += (track * duck * 0.15).astype(np.float32)
    sf.write(out, buf[: int(total * SR)], SR)


def build(q: dict, out: Path, scale: float = 1.0, samples: int = 48) -> float:
    W, H = int(1080 * scale), int(1920 * scale)
    work = Path(tempfile.mkdtemp(prefix="hiw-"))
    lines = speak(q["lines"], work / "voice")
    shots, cues, length = plan(q, lines)
    frames = int(round(length * FPS))
    # HIW_CACHE: the 3D frames are rendered straight into <cache>/<id>/frames and kept, so a stopped render resumes
    # (Blender skips frames already there) and 2D-only fixes skip Blender. Delete the cache when the video is done.
    cache = os.environ.get("HIW_CACHE")
    key = json.dumps([shots, cues, frames, W, samples, (ROOT / "render" / "skin_scene.py").read_text()])
    fdir = work / "frames"
    if cache:
        keep = Path(cache).expanduser() / q["id"]
        fdir = keep / "frames"
        if not ((keep / "key.txt").exists() and (keep / "key.txt").read_text() == key):
            shutil.rmtree(keep, ignore_errors=True)
            fdir.mkdir(parents=True)
            (keep / "key.txt").write_text(key)
    if len(list(fdir.glob("*.png"))) < frames or not (fdir / "anchors.json").exists():
        render3d(q, shots, cues, frames, fdir, W, H, samples)
    else:
        print(f"{q['id']}: 3D frames from the cache", flush=True)
    anchors = json.loads((fdir / "anchors.json").read_text())
    back = studio(W, H, True)
    thumbs = thumbs_for(q, fdir, shots, back, scale)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = work / "video.mp4"
    enc = subprocess.Popen([ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                            "-pix_fmt", "yuv420p", str(tmp)], stdin=subprocess.PIPE)
    last = None
    for k in range(frames):
        last = compose(q, k, fdir, anchors, shots, cues, scale, back, thumbs)
        enc.stdin.write(last.tobytes())
    for _ in range(int(COVER_TAIL * FPS)):
        enc.stdin.write(last.tobytes())
    enc.stdin.close()
    enc.wait()
    total = frames / FPS + COVER_TAIL
    wav = work / "sound.wav"
    sound(q, shots, cues, lines, total, wav)
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(tmp), "-i", str(wav),
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    last.save(out.with_suffix(".jpg"), quality=92)
    shutil.rmtree(work, ignore_errors=True)
    return total


def stills(q: dict, out: Path, picks: list[str], samples: int = 48, scale: float = 1.0) -> None:
    """Full-size frames at shot@fraction (e.g. surface@0.6), rendered on their own, finished and set side by side."""
    work = Path(tempfile.mkdtemp(prefix="hiw-stills-"))
    lines = speak(q["lines"], work / "voice")
    shots, cues, length = plan(q, lines)
    frames = int(round(length * FPS))
    ks = []
    for p in picks:
        kind, f = p.split("@")
        sh = next(x for x in shots if x["kind"] == kind)
        ks.append(int((sh["start"] + (sh["end"] - sh["start"]) * float(f)) * FPS))
    W, H = int(1080 * scale), int(1920 * scale)
    render3d(q, shots, cues, frames, work / "frames", W, H, samples, only=ks)
    anchors = json.loads((work / "frames" / "anchors.json").read_text())
    back = studio(W, H, True)
    pics = [compose(q, k, work / "frames", anchors, shots, cues, scale, back) for k in ks]
    sheet = Image.new("RGB", (W * len(pics) + 40 * (len(pics) - 1), H), (20, 20, 22))
    for i, p in enumerate(pics):
        sheet.paste(p, (i * (W + 40), 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    shutil.rmtree(work, ignore_errors=True)
    print(f"{out}: frames {ks} of {frames}")


def info(q: dict, seconds: float) -> dict:
    """What the posting job needs (anatomy/series.py). Format "types": the same caption (hook, the comment question,
    the send line, the summary and sources)."""
    return {"id": q["id"], "format": "types", "title": q["title"], "hook": shown(q["lines"][0]), "question": q["question"],
            "choices": [], "answer": "", "why": q["why"], "seconds": round(seconds, 2), "music": q["music"],
            "hashtags": q["hashtags"][:5], "sources": q["sources"], "credit": q["credit"], "send": q["send"],
            **{k: q[k] for k in ("caption_first", "caption_extra", "youtube_title") if q.get(k)}}


def with_music(q: dict) -> dict:
    return {**q, "music": q.get("music") or music.pick(zlib.crc32(q["id"].encode()), styles=CONFIG.get("music_styles"))}


def release(folder: Path, ids: list[str], scale: float = 1.0) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for q in items():
        if ids and q["id"] not in ids:
            continue
        q = with_music(q)
        t = time.time()
        seconds = build(q, folder / f"{q['id']}.mp4", scale=scale, samples=48 if scale == 1.0 else 12)
        (folder / f"{q['id']}.json").write_text(json.dumps(info(q, seconds), indent=1, ensure_ascii=False) + "\n")
        print(f"{q['id']}: {seconds:.1f} s video, {q['music']}, rendered in {time.time() - t:.0f} s", flush=True)


def word_check(q: dict) -> None:
    work = Path(tempfile.mkdtemp(prefix="say-"))
    for line, (wav, sec) in zip(q["lines"], speak(q["lines"], work)):
        print(f"{sec:4.1f}s  {shown(line)}\n       heard: {heard(wav)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["release"] and len(a) >= 2:
        release(Path(a[1]).expanduser(), a[2:])
    elif a[:1] == ["preview"] and len(a) == 3:
        release(Path(a[2]).expanduser(), [a[1]], scale=0.5)
    elif a[:1] == ["stills"] and len(a) >= 3:
        stills(with_music(item(a[1])), Path(a[2]).expanduser(), a[3:] or ["surface@0.7", "eccrine@0.97"],
               samples=int(os.environ.get("HIW_SAMPLES", 48)), scale=float(os.environ.get("HIW_SCALE", 1.0)))
    elif a[:1] == ["say"] and len(a) == 2:
        word_check(item(a[1]))
    else:
        raise SystemExit(__doc__)
