"""Anatomy Deep Dives: ~50 s motion-graphics explainers (the nephron, the sodium-potassium pump, glycolysis...).

Each one is built and checked by hand (Remotion, Kokoro voice, original music), rendered once and published on this
repo's GitHub release "deepdives": <id>.mp4 plus index.json, which lists them in posting order with what the
caption needs. Config "deepdive" says which daily slot gets one and from when; that slot takes the next video in
the index not posted yet, and posts a quiz instead if none is ready, so a slot is never empty.

    python -m anatomy.deepdive publish DIR      # upload DIR/<id>.mp4 + DIR/<id>.json and rebuild index.json (Mac)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
RELEASE = "deepdives"
REPO = "Yashasdev/anatomy-reels"
_INDEX: list[dict] | None = None


def settings() -> dict:
    return CONFIG.get("deepdive", {})


def source() -> str:
    return f"https://github.com/{REPO}/releases/download/{RELEASE}"


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "anatomy-reels"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def index() -> list[dict]:
    """The published deep dives, in posting order (fetched once per run; none if it can't be reached)."""
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = json.loads(fetch(f"{source()}/index.json"))
        except Exception as e:
            print(f"::warning::Couldn't read the deep dive index ({e}); those slots post quizzes this run.")
            _INDEX = []
    return _INDEX


def is_slot(at: datetime) -> bool:
    s = settings()
    return bool(s) and at.date().isoformat() >= s["from"] and f"{at:%H:%M}" in s["slots"]


def next_video(used: list[str]) -> dict | None:
    return next((v for v in index() if v["id"] not in used), None)


def left(used: list[str]) -> int:
    return sum(v["id"] not in used for v in index())


def caption(q: dict) -> str:
    """Hook, the question with its choices, then the answer far below so people comment first."""
    choices = "\n".join(f"{'ABCD'[k]}) {c}" for k, c in enumerate(q["choices"]))
    tags = (q.get("hashtags") or CONFIG["hashtags"])[:5]  # Instagram allows 5
    return (f"{q['hook']}\n\n"
            f"{q['question']}\n{choices}\n"
            "Comment your answer 👇 (answer at the bottom)\n"
            "Follow for a new deep dive every day.\n\n"
            + " ".join(tags) + "\n\n.\n.\n.\n"
            f"✅ Answer: {q['answer']}) {q['choices']['ABCD'.index(q['answer'])]}\n"
            + re.sub(r"^[A-D][:,.)]\s*", "", q["why"]) + "\n"
            "For learning only, not medical advice.")


def youtube_title(q: dict) -> str:
    return f"{q['title']}: {q['question']} #shorts"[:100]


def download(q: dict, out: Path) -> float:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(fetch(f"{source()}/{q['id']}.mp4", timeout=300))
    return float(q["seconds"])


def publish_dir(folder: Path) -> None:
    """Upload every <id>.mp4 with its <id>.json in folder, then rebuild index.json from config order."""
    have = subprocess.run(["gh", "release", "view", RELEASE, "-R", REPO], capture_output=True)
    if have.returncode:
        subprocess.run(["gh", "release", "create", RELEASE, "-R", REPO, "--title", "Anatomy Deep Dives",
                        "--notes", "Finished deep dive videos. index.json lists them in posting order."], check=True)
    infos = {p.stem: json.loads(p.read_text()) for p in folder.glob("*.json") if p.name != "index.json"}
    for vid in infos:
        subprocess.run(["gh", "release", "upload", RELEASE, "-R", REPO, "--clobber",
                        str(folder / f"{vid}.mp4"), str(folder / f"{vid}.json")], check=True)
    try:
        old = {v["id"]: v for v in json.loads(fetch(f"{source()}/index.json"))}
    except Exception:
        old = {}
    merged = {**old, **infos}
    order = settings().get("order", [])
    listing = [merged[i] for i in order if i in merged] + [v for i, v in merged.items() if i not in order]
    (folder / "index.json").write_text(json.dumps(listing, indent=1, ensure_ascii=False) + "\n")
    subprocess.run(["gh", "release", "upload", RELEASE, "-R", REPO, "--clobber", str(folder / "index.json")], check=True)
    print(f"index lists {len(listing)} deep dives: {[v['id'] for v in listing]}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "publish":
        publish_dir(Path(sys.argv[2]))
    else:
        raise SystemExit(__doc__)
