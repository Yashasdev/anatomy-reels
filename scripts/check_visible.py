"""Check that each question's glowing part can actually be seen: render 8 angles of the turn (small and quick)
and count the lime pixels. Fails if the part shows in fewer than half the angles. Also saves a contact sheet.

    python scripts/check_visible.py skull-04 leg-01      # given ids
    python scripts/check_visible.py --new origin/main    # every question added since that git ref
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from anatomy.make import blender  # noqa: E402

ANGLES, SIZE, MIN_SHARE = 8, 320, 0.0015  # a part counts as seen when 0.15% of the frame is lime


def all_items() -> dict[str, dict]:
    return {q["id"]: q for p in sorted((ROOT / "banks").glob("*.json")) for q in json.loads(p.read_text())}


def new_ids(ref: str) -> list[str]:
    old = set()
    for p in sorted((ROOT / "banks").glob("*.json")):
        r = subprocess.run(["git", "show", f"{ref}:banks/{p.name}"], capture_output=True, text=True, cwd=ROOT)
        if r.returncode == 0:
            old |= {q["id"] for q in json.loads(r.stdout)}
    return [i for i in all_items() if i not in old]


def lime_share(path: Path) -> float:
    im = Image.open(path).convert("RGBA")
    px = im.getdata()
    lime = sum(1 for r, g, b, a in px if a > 128 and g > 150 and g > r + 25 and g > b + 60)
    return lime / (im.width * im.height)


def check(q: dict, work: Path) -> tuple[int, list[Path]]:
    turn = 360 / ANGLES
    spec = {"model": str(ROOT / "assets" / "models" / f"{q['model']}.blend"), "out": str(work / q["id"]),
            "frames": ANGLES, "fps": 1, "highlight": q["highlight"], "degrees_per_second": turn,
            "start_degrees": q.get("start_degrees", -20), "distance": q.get("distance", 4.2),
            "engine": os.environ.get("ANATOMY_ENGINE", "BLENDER_EEVEE_NEXT"), "samples": 4,
            "width": SIZE, "height": SIZE}
    r = subprocess.run([blender(), "-b", "--factory-startup", "--python", str(ROOT / "render" / "blender_scene.py"),
                        "--", json.dumps(spec)], capture_output=True, text=True)
    frames = sorted((work / q["id"]).glob("f*.png"))
    if r.returncode or len(frames) < ANGLES:
        raise RuntimeError(f"Blender failed for {q['id']}:\n{(r.stdout + r.stderr)[-2000:]}")
    seen = sum(lime_share(f) >= MIN_SHARE for f in frames)
    return seen, frames


def main() -> int:
    items = all_items()
    ids = new_ids(sys.argv[2]) if sys.argv[1:2] == ["--new"] else sys.argv[1:]
    if not ids:
        print("No new questions to check.")
        return 0
    work = Path(tempfile.mkdtemp())
    sheet = Image.new("RGB", (ANGLES * SIZE // 2, len(ids) * (SIZE // 2 + 24)), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    bad = []
    for row, i in enumerate(ids):
        q = items[i]
        seen, frames = check(q, work)
        ok = seen >= ANGLES // 2
        print(f"{'ok  ' if ok else 'FAIL'} {i}: glowing part seen in {seen} of {ANGLES} angles ({q['highlight']})")
        bad += [] if ok else [i]
        y = row * (SIZE // 2 + 24)
        d.text((6, y + 4), f"{i}  {q['question']}  ->  {q['choices'][q['answer_index']]}  (seen {seen}/{ANGLES})",
               fill=(255, 255, 255) if ok else (255, 80, 80))
        for k, f in enumerate(frames):
            a = Image.open(f).convert("RGBA")
            bg = Image.new("RGBA", a.size, (0, 0, 0, 255))
            bg.alpha_composite(a)
            sheet.paste(bg.convert("RGB").resize((SIZE // 2, SIZE // 2)), (k * SIZE // 2, y + 24))
    out = ROOT / "out" / "visibility.png"
    out.parent.mkdir(exist_ok=True)
    sheet.save(out)
    print(f"contact sheet: {out}")
    if bad:
        print(f"::error::glowing part hard to see in {', '.join(bad)}: pick a bigger part, another start angle, "
              "or a smaller distance (zooms in)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
