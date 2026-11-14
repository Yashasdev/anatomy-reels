"""The quiz's "look" option: the default (classic, black and lime) render must stay exactly as it was, and the studio
look (light-gray sweep, outlined text) only turns on when asked.

anatomy.make.build runs here with Kokoro, Blender and FFmpeg stubbed out: fake voice lines of fixed lengths and a
fake 3D layer, so the frames it composes can be compared with tests/fixtures/quiz_classic.json, recorded from the
code before the studio look was added. Frames are compared as small grayscale thumbnails with a tolerance, so a
different Pillow or FreeType on GitHub doesn't fail the test, but any moved, recolored or added element does.
Regenerate the fixture only for a deliberate change to the classic look: python -m tests.test_quiz_look record
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw

from anatomy import make

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "quiz_classic.json"
THUMB = (54, 96)
Q = {"id": "test-quiz", "model": "spine", "title": "The Spine", "highlight": ["Sacrum"], "start_degrees": 180,
     "distance": 3.0, "question": "How many vertebrae form the sacrum?", "choices": ["5", "3", "4", "7"],
     "answer_index": 0, "trap_index": 2, "day": 85, "label": "ANATOMY CHECK",
     "lines": ["One bone at the base of your spine was once separate pieces.", "Watch the glowing triangle.",
               "How many vertebrae form the sacrum?", "The sacrum forms from five vertebrae.", "It's A. Five.",
               "Why it matters: it's the back wall of the pelvis."],
     "ask_line": 2, "answer_line": 4}
SECONDS = [1.1, 0.7, 0.9, 0.8, 0.5, 0.9]


def fake_layer(k: int) -> Image.Image:
    """A stand-in for one Blender frame: a soft disc that drifts with k on a transparent square."""
    s = make.MODEL_BOX[2]
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 260 + (k * 37) % 300
    d.ellipse((x, 220, x + 360, 700), fill=(210, 190, 150, 255))
    d.rectangle((x + 120, 520, x + 240, 640), fill=(80, 220, 10, 255))
    return img


def run(monkeypatch, tmp_path: Path, **kw) -> tuple[dict, dict[str, np.ndarray]]:
    """Build Q with everything external stubbed; returns the Blender spec and a few frames as thumbnails."""
    work = tmp_path / "work"
    seen = {}

    def voice_lines(texts, out, voice, speed):
        out.mkdir(parents=True, exist_ok=True)
        lines = []
        for i, sec in enumerate(SECONDS[: len(texts)]):
            path = out / f"line{i:02d}.wav"
            sf.write(path, np.zeros(int(sec * 24000), np.float32), 24000)
            lines.append((path, sec))
        return lines

    def fake_run(args, **_):
        if "--python" in args:
            spec = json.loads(args[-1])
            seen["spec"] = spec
            Path(spec["out"]).mkdir(parents=True)
            for k in range(1, spec["frames"] + 1):
                fake_layer(k).save(Path(spec["out"]) / f"f{k:04d}.png")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(make, "voice_lines", voice_lines)
    monkeypatch.setattr(make, "blender", lambda: "blender")
    monkeypatch.setattr(make, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(make.subprocess, "run", fake_run)
    monkeypatch.setattr(make.tempfile, "mkdtemp", lambda **_: str(work.mkdir() or work))
    monkeypatch.setattr(make.shutil, "rmtree", lambda *a, **k: None)
    monkeypatch.setattr(make, "FPS", 4)  # few frames: the layout, not the motion, is what's checked
    monkeypatch.setenv("ANATOMY_ENGINE", "BLENDER_EEVEE_NEXT")
    make.build(dict(Q), tmp_path / "out" / "q.mp4", **kw)
    frames = sorted((work / "frames").glob("*.png"))
    picks = {"first": frames[0], "ask": frames[len(frames) // 3], "middle": frames[len(frames) // 2],
             "answer": frames[-4], "cover": frames[-1]}
    thumbs = {k: np.asarray(Image.open(p).convert("L").resize(THUMB, Image.BOX), np.float32) for k, p in picks.items()}
    return seen["spec"], thumbs


def pack(a: np.ndarray) -> str:
    return base64.b64encode(np.clip(a.round(), 0, 255).astype(np.uint8).tobytes()).decode()


def unpack(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), np.uint8).reshape(THUMB[1], THUMB[0]).astype(np.float32)


def test_default_render_is_unchanged(monkeypatch, tmp_path):
    want = json.loads(FIXTURE.read_text())
    spec, thumbs = run(monkeypatch, tmp_path)
    spec = {k: v for k, v in spec.items() if k not in ("model", "out")}  # absolute paths
    assert spec == want["spec"], "the classic quiz must send Blender exactly the same spec"
    for name, packed in want["frames"].items():
        diff = np.abs(thumbs[name] - unpack(packed))
        assert diff.mean() < 0.6 and diff.max() < 40, f"classic frame '{name}' changed (mean {diff.mean():.2f})"


def test_studio_look_is_opt_in(monkeypatch, tmp_path):
    spec, thumbs = run(monkeypatch, tmp_path, look="studio")
    assert spec.get("studio") is True
    assert thumbs["first"][5:20].mean() > 60, "studio frames sit on the gray sweep, not black"


def record(tmp: Path) -> None:
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        spec, thumbs = run(mp, tmp)
    finally:
        mp.undo()
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text(json.dumps({"spec": {k: v for k, v in spec.items() if k not in ("model", "out")},
                                   "frames": {k: pack(v) for k, v in thumbs.items()}}, indent=1) + "\n")
    print(f"wrote {FIXTURE}")


if __name__ == "__main__" and sys.argv[1:] == ["record"]:
    import tempfile
    record(Path(tempfile.mkdtemp()))
