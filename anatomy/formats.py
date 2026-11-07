"""The other 3D formats: "Which bone is missing?" and "Zoom out: guess the body part" (banks/formats/<kind>.json).

They're drawn by anatomy/make.py (an item's "kind" picks the format) and rendered ahead of time on a Mac, like the
deep dives: each video goes out as <id>.mp4 plus <id>.json with what the caption needs.

    python -m anatomy.formats release DIR [ids...]   # render every item (or the given ids) into DIR, one at a time
    python -m anatomy.formats list                   # ids, answers and traps

Item keys beyond the classic quiz's: "kind" ("missing" or "zoom"), "reveal" (parts that fade in glowing or light up
at the answer), "hide" (missing: parts left out until then), "sway" ([degrees, seconds]: swing around start_degrees
instead of a full turn, so the gap stays in sight), "zoom" ({"target", "aim", "start"}: where the close-up starts),
"focus_on", "note" (small text under the header until the answer), "why", "hashtags", "sources".
"""

from __future__ import annotations

import json
import sys
import time
import zlib
from pathlib import Path

from . import music

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
TITLES = {"missing": "Which bone is missing?", "zoom": "Zoom out: guess the body part"}


def items() -> list[dict]:
    return [q for p in sorted((ROOT / "banks" / "formats").glob("*.json")) for q in json.loads(p.read_text())]


def tracks(qs: list[dict]) -> dict[str, str]:
    """An original track per video (anatomy/music.py), never one of the previous eight in this list."""
    out: dict[str, str] = {}
    for q in qs:
        out[q["id"]] = q.get("music") or music.pick(zlib.crc32(q["id"].encode()), avoid=list(out.values())[-8:],
                                                    styles=CONFIG.get("music_styles"))
    return out


def info(q: dict, seconds: float, track: str) -> dict:
    return {"id": q["id"], "format": q["kind"], "title": TITLES[q["kind"]], "hook": q["lines"][0],
            "question": q["question"], "choices": q["choices"], "answer": "ABCD"[q["answer_index"]],
            "why": q["why"], "seconds": round(seconds, 2), "music": track, "hashtags": q["hashtags"][:5],
            "sources": q["sources"]}


def release(folder: Path, ids: list[str]) -> None:
    from .make import build
    qs = items()
    music_for = tracks(qs)
    folder.mkdir(parents=True, exist_ok=True)
    for q in qs:
        if ids and q["id"] not in ids:
            continue
        t = time.time()
        seconds = build({**q, "music": music_for[q["id"]]}, folder / f"{q['id']}.mp4")
        (folder / f"{q['id']}.json").write_text(json.dumps(info(q, seconds, music_for[q["id"]]), indent=1,
                                                           ensure_ascii=False) + "\n")
        print(f"{q['id']}: {seconds:.1f} s video, {music_for[q['id']]}, rendered in {time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["release"] and len(sys.argv) >= 3:
        release(Path(sys.argv[2]).expanduser(), sys.argv[3:])
    elif sys.argv[1:2] == ["list"]:
        for q in items():
            print(q["id"], "ABCD"[q["answer_index"]], q["choices"][q["answer_index"]], "| trap:", q["choices"][q["trap_index"]])
    else:
        raise SystemExit(__doc__)
