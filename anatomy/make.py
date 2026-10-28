"""Make an anatomy reel from one question in a bank: narration, a 3D render of the organ with one part lit, and
the quiz layout on top, in the QuantProf-style look the other channels use (black, lime, serif captions).

    python -m anatomy.make heart-01            # renders out/heart-01.mp4 (Blender, Kokoro and FFmpeg needed)

Order of a reel: a challenge hook, the setup, the question with four choices, a 3-2-1 to comment, the
explanation, the answer ("It's A"), and why it matters. The last half second repeats the question frame, so the
platforms' cover shows the puzzle, not the answer.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
W, H, FPS, LAYER_FPS = 1080, 1920, 30, 15
SR = 44100
LIME, RED, GREEN, YELLOW, WHITE, GREY = (163, 230, 53), (239, 68, 68), (34, 197, 94), (250, 204, 21), (255, 255, 255), (150, 150, 150)
MODEL_BOX = (60, 250, 960)  # x, y, size of the square 3D layer
LEAD_IN, GAP, COVER_TAIL = 0.5, 0.2, 0.5


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


SERIF = lambda s: font("lmroman10-regular.otf", s)  # noqa: E731
SANS = lambda s: font("Inter-ExtraBold.otf", s)  # noqa: E731


def blender() -> str:
    for p in [os.environ.get("BLENDER", ""), "/Applications/Blender.app/Contents/MacOS/Blender", shutil.which("blender") or ""]:
        if p and Path(p).exists():
            return p
    raise SystemExit("Blender isn't installed (set BLENDER to its path)")


def ffmpeg() -> str:
    return shutil.which("ffmpeg") or __import__("imageio_ffmpeg").get_ffmpeg_exe()


# --- voice --------------------------------------------------------------------------------------------------
KOKORO = Path(os.environ.get("KOKORO_DIR", Path.home() / ".cache" / "kokoro"))
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def voice_lines(texts: list[str], out: Path, voice: str, speed: float) -> list[tuple[Path, float]]:
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
        said = t.replace("%", " percent")
        samples, sr = k.create(said, voice=voice, speed=speed, lang="en-us")
        x = np.asarray(samples, np.float32)
        loud = np.flatnonzero(np.abs(x) > 0.01)
        x = x[max(loud[0] - 400, 0): loud[-1] + 2400] if len(loud) else x
        path = out / f"line{i:02d}.wav"
        sf.write(path, x, sr)
        lines.append((path, len(x) / sr))
    return lines


# --- sounds (made here, nothing licensed) ------------------------------------------------------------------
def tone(freq: float, dur: float, decay: float, gain: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    return (np.sin(2 * np.pi * freq * t) * np.exp(-t * decay) * gain).astype(np.float32)


SOUNDS = {"tick": lambda: tone(1800, 0.06, 60, 0.35), "pop": lambda: tone(660, 0.15, 25, 0.4),
          "bell": lambda: tone(1320, 1.0, 4, 0.35) + tone(1980, 1.0, 6, 0.15),
          "whoosh": lambda: (np.random.default_rng(1).uniform(-1, 1, int(0.5 * SR)) *
                             np.sin(np.linspace(0, np.pi, int(0.5 * SR))) * 0.25).astype(np.float32)}


def bed(length: float) -> np.ndarray:
    """A soft, slow pad under the voice."""
    t = np.arange(int(length * SR)) / SR
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66), (164.81, 207.65, 246.94)]
    out = np.zeros(len(t), np.float32)
    for i in range(int(length // 2) + 1):
        a, b = int(i * 2 * SR), min(int((i + 1) * 2 * SR), len(t))
        if a >= len(t):
            break
        s = t[a:b] - t[a]
        env = np.minimum(1, s / 0.4) * np.minimum(1, (2 - s) / 0.4)
        out[a:b] += sum(np.sin(2 * np.pi * f * s) for f in chords[i % 4]) * env / 3
    return out * 0.05


# --- layout -------------------------------------------------------------------------------------------------
def centered(d: ImageDraw.ImageDraw, y: int, text: str, f, fill) -> None:
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=fill)


def wrap(d, text: str, f, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        test = f"{cur} {w}".strip()
        if cur and d.textlength(test, font=f) > width:
            lines.append(cur)
            cur = w
        else:
            cur = test
    return lines + [cur]


def caption(d, text: str, word: int) -> None:
    """A word-group caption in a white box, the current word on a lime highlight."""
    f = SERIF(46)
    words = text.split()
    widths = [d.textlength(w, font=f) for w in words]
    gap = d.textlength(" ", font=f)
    total = sum(widths) + gap * (len(words) - 1)
    x, y = (W - total) / 2, 1545
    d.rounded_rectangle((x - 22, y - 12, x + total + 22, y + 62), 8, fill=WHITE)
    for i, (w, ww) in enumerate(zip(words, widths)):
        if i == word:
            d.rounded_rectangle((x - 6, y - 6, x + ww + 6, y + 56), 6, fill=LIME)
        d.text((x, y), w, font=f, fill=(0, 0, 0))
        x += ww + gap


def chunks(line: str, most: int = 4) -> list[str]:
    out, cur = [], []
    for w in line.split():
        cur.append(w)
        if len(cur) == most or re.search(r"[.,:;?!]$", w):
            out.append(" ".join(cur))
            cur = []
    return out + ([" ".join(cur)] if cur else [])


def choice_boxes(d, choices: list[str], marks: dict[int, tuple]) -> None:
    f, badge = SERIF(44), SANS(30)
    for i, c in enumerate(choices):
        col, row = i % 2, i // 2
        x0, y0 = 50 + col * 500, 1290 + row * 100
        box = (x0, y0, x0 + 480, y0 + 86)
        if i in marks:
            d.rounded_rectangle(box, 14, fill=tuple(int(v * 0.3) for v in marks[i]), outline=marks[i], width=6)
        else:
            d.rounded_rectangle(box, 14, fill=(0, 0, 0), outline=WHITE, width=2)
        d.ellipse((x0 + 22, y0 + 18, x0 + 72, y0 + 68), fill=WHITE)
        lw = d.textlength("ABCD"[i], font=badge)
        d.text((x0 + 47 - lw / 2, y0 + 23), "ABCD"[i], font=badge, fill=(0, 0, 0))
        text = c if d.textlength(c, font=f) < 370 else c
        g = f if d.textlength(text, font=f) < 370 else SERIF(36)
        d.text((x0 + 92, y0 + 18 if g is f else 24), text, font=g, fill=WHITE)


# --- the reel -----------------------------------------------------------------------------------------------
def build(q: dict, out: Path, voice: str = "af_heart", speed: float = 1.25, engine: str = "") -> float:
    engine = engine or os.environ.get("ANATOMY_ENGINE", "BLENDER_EEVEE_NEXT")
    work = Path(tempfile.mkdtemp(prefix=f"anatomy-{q['id']}-"))
    lines = voice_lines(q["lines"], work / "voice", voice, speed)
    ask_line = q["ask_line"]                      # the narration line that asks the question (choices appear)
    answer_line = q["answer_line"]                # the line that says "It's A" (marks appear)
    # timeline: lead-in, each line with a gap, and the 3-2-1 right after the question
    starts, t = [], LEAD_IN
    for i, (_, sec) in enumerate(lines):
        starts.append(t)
        t += sec + GAP
        if i == ask_line:
            countdown_at = t
            t += 3.0
    length = t + 0.3
    cover_at = starts[ask_line] + lines[ask_line][1]

    # the 3D layer, rendered once for the whole length at 15 fps
    # one full turn is enough: the model only spins, so later frames repeat it (saves a quarter of the render)
    turn = q.get("degrees_per_second", 24)
    frames = min(int(length * LAYER_FPS) + 1, round(360 * LAYER_FPS / turn))
    spec = {"model": str(ROOT / "assets" / "models" / f"{q['model']}.blend"), "out": str(work / "layer"),
            "frames": frames, "fps": LAYER_FPS, "highlight": q["highlight"], "engine": engine,
            "width": MODEL_BOX[2], "height": MODEL_BOX[2], "distance": q.get("distance", 4.2),
            "degrees_per_second": turn, "start_degrees": q.get("start_degrees", -20)}
    r = subprocess.run([blender(), "-b", "--factory-startup", "--python", str(ROOT / "render" / "blender_scene.py"),
                        "--", json.dumps(spec)], capture_output=True, text=True)
    if r.returncode or not (work / "layer" / "f0001.png").exists():
        raise RuntimeError(f"Blender failed for {q['id']}:\n{(r.stdout + r.stderr)[-3000:]}")

    header_title = SANS(44)
    header_sub = SERIF(42)
    frame_dir = work / "frames"
    frame_dir.mkdir()
    cue_words = []  # (start, end, chunk text, word index) for captions
    for (path, sec), s, text in zip(lines, starts, q["lines"]):
        groups = chunks(text)
        weights = [len(w) + 2 for g in groups for w in g.split()]
        edges = np.cumsum(weights) / sum(weights) * sec
        k = 0
        for g in groups:
            for wi, _ in enumerate(g.split()):
                a = s + (edges[k - 1] if k else 0)
                cue_words.append((a, s + edges[k], g, wi))
                k += 1

    n = int(length * FPS)
    cover = None
    for i in range(n):
        tt = i / FPS
        img = Image.new("RGB", (W, H), (0, 0, 0))
        layer = Image.open(work / "layer" / f"f{int(tt * LAYER_FPS) % frames + 1:04d}.png").convert("RGBA")
        img.paste(layer, MODEL_BOX[:2], layer)
        d = ImageDraw.Draw(img)
        centered(d, 70, q.get("label", "ANATOMY CHECK"), header_title, LIME)
        centered(d, 132, f"#{q.get('day', 1)} · {q['title']}", header_sub, WHITE)
        if tt >= starts[ask_line]:
            centered(d, 1205, q["question"], SERIF(50), YELLOW)
            marks = {}
            if tt >= starts[answer_line]:
                marks = {q["answer_index"]: GREEN, q["trap_index"]: RED}
            choice_boxes(d, q["choices"], marks)
        if tt >= starts[answer_line]:
            centered(d, 205, q["choices"][q["answer_index"]], SANS(52), LIME)
        if countdown_at <= tt < countdown_at + 3:
            num = 3 - int(tt - countdown_at)
            d.ellipse((W / 2 - 60, 1060, W / 2 + 60, 1180), outline=YELLOW, width=8)
            centered(d, 1083, str(num), SANS(64), YELLOW)
            f = SANS(40)
            w = d.textlength("Comment your answer", font=f)
            d.rounded_rectangle(((W - w) / 2 - 22, 1535, (W + w) / 2 + 22, 1607), 8, fill=WHITE)
            centered(d, 1545, "Comment your answer", f, (0, 0, 0))
        else:
            cur = next((c for c in cue_words if c[0] <= tt < c[1]), None)
            if cur:
                caption(d, cur[2], cur[3])
        if cover is None and tt >= cover_at:
            cover = img.copy()
        img.save(frame_dir / f"{i:05d}.png")
    cover = cover or img
    for j in range(int(COVER_TAIL * FPS)):
        cover.save(frame_dir / f"{n + j:05d}.png")
    total = length + COVER_TAIL

    # sound: voice lines, effects, soft bed, leveled
    buf = np.zeros(int(total * SR) + SR, np.float32)

    def add(x, at, gain=1.0):
        a = int(at * SR)
        buf[a:a + len(x)] += x[: len(buf) - a] * gain
    add(SOUNDS["whoosh"](), 0.0)
    for (path, _), s in zip(lines, starts):
        v, sr = sf.read(path, dtype="float32")
        if sr != SR:
            v = np.interp(np.arange(0, len(v), sr / SR), np.arange(len(v)), v).astype(np.float32)
        add(v, s)
    add(SOUNDS["pop"](), starts[ask_line])
    for k in range(3):
        add(SOUNDS["tick"](), countdown_at + k)
    add(SOUNDS["bell"](), starts[answer_line])
    buf[: int(total * SR)] += bed(total)
    wav = work / "sound.wav"
    sf.write(wav, buf[: int(total * SR)], SR)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frame_dir / "%05d.png"),
                    "-i", str(wav), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:v", "libx264", "-crf", "19",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest",
                    "-movflags", "+faststart", str(out)], check=True)
    cover.save(out.with_suffix(".jpg"), quality=92)
    shutil.rmtree(work, ignore_errors=True)
    return total


def load_bank(name: str = "heart") -> list[dict]:
    return json.loads((ROOT / "banks" / f"{name}.json").read_text())


def main() -> None:
    ids = sys.argv[1:]
    bank = [q for b in sorted((ROOT / "banks").glob("*.json")) for q in json.loads(b.read_text())]
    for q in bank:
        if not ids or q["id"] in ids:
            sec = build(q, ROOT / "out" / f"{q['id']}.mp4")
            print(f"out/{q['id']}.mp4  {sec:.1f} s")


if __name__ == "__main__":
    main()
