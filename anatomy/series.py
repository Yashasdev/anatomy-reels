"""Series of finished videos posted in quiz slots: Anatomy Deep Dives and the rotating short formats.

Each video is made and checked ahead of time (Remotion or Blender on the Mac, Kokoro voice, original music) and
published on one of this repo's GitHub releases with an index.json listing the videos in posting order and what
the caption needs. A series in config.json names its release and the daily slots it takes from a date:

  "deepdive": {"release": "deepdives", "slots": ["18:00"], "from": "2026-11-07", "order": [...]}
  "formats":  {"release": "formats", "slots": ["12:30", "16:00"], "from": "...",
               "cycle": ["missing", "zoom", "diagnose", "myth", "rank"]}

A slot of a series posts its next unposted video; with a "cycle", the day's slots take the next formats in turn
(two slots a day over five formats: every format twice in five days, never twice on one day), and if that format
has nothing ready the next one in the cycle steps in. With nothing ready at all, the slot posts a quiz.

    python -m anatomy.series publish SERIES DIR     # upload DIR/<id>.mp4 + .json, rebuild index.json (on the Mac)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
REPO = "Yashasdev/anatomy-reels"
SERIES = ("deepdive", "formats")
FOLLOW = {"deepdive": "Follow for a new deep dive every day.", "formats": "Follow for a new anatomy challenge every day."}
_INDEX: dict[str, list[dict]] = {}


def settings(name: str) -> dict:
    return CONFIG.get(name, {})


def release(name: str) -> str:
    return settings(name).get("release", "deepdives" if name == "deepdive" else name)


def source(name: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{release(name)}"


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "anatomy-reels"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def index(name: str) -> list[dict]:
    """A series' published videos, in posting order (fetched once per run; none if it can't be reached)."""
    if name not in _INDEX:
        try:
            _INDEX[name] = json.loads(fetch(f"{source(name)}/index.json"))
        except Exception as e:
            print(f"::warning::Couldn't read the {name} index ({e}); its slots post quizzes this run.")
            _INDEX[name] = []
    return _INDEX[name]


def series_for(at: datetime) -> str | None:
    """Which series owns this slot, if any."""
    for name in SERIES:
        s = settings(name)
        if s and at.date().isoformat() >= s["from"] and f"{at:%H:%M}" in s["slots"]:
            return name
    return None


def wanted_format(name: str, at: datetime) -> str | None:
    """The format this slot should carry today (series with a "cycle"), or None for a plain series."""
    s = settings(name)
    if not s.get("cycle"):
        return None
    day = (at.date() - date.fromisoformat(s["from"])).days
    k = day * len(s["slots"]) + sorted(s["slots"]).index(f"{at:%H:%M}")
    return s["cycle"][k % len(s["cycle"])]


def next_video(name: str, at: datetime, used: list[str]) -> dict | None:
    fresh = [v for v in index(name) if v["id"] not in used]
    want = wanted_format(name, at)
    if want is None:
        return fresh[0] if fresh else None
    cycle = settings(name)["cycle"]
    start = cycle.index(want)
    for k in range(len(cycle)):  # the wanted format, else the next one in the cycle that has a video ready
        fmt = cycle[(start + k) % len(cycle)]
        pick = next((v for v in fresh if v.get("format") == fmt), None)
        if pick:
            return pick
    return None


def left(name: str, used: list[str]) -> dict[str, int]:
    """Videos not posted yet, per format (or under the series' name)."""
    out: dict[str, int] = {}
    for v in index(name):
        if v["id"] not in used:
            key = v.get("format", name)
            out[key] = out.get(key, 0) + 1
    return out


def answer_text(q: dict) -> str:
    letters = [a.strip() for a in q["answer"].split(",")]
    if len(letters) > 1:  # a ranking: "C, A, D, B" -> "C, A, D, B (Liver, Brain, Lungs, Heart)"
        return f"{q['answer']} ({', '.join(q['choices']['ABCD'.index(x)] for x in letters)})"
    return f"{q['answer']}) {q['choices']['ABCD'.index(letters[0])]}"


def caption(q: dict) -> str:
    """Hook, the question with its choices, then the answer far below so people comment first."""
    choices = "\n".join(f"{'ABCD'[k]}) {c}" for k, c in enumerate(q["choices"]))
    tags = (q.get("hashtags") or CONFIG["hashtags"])[:5]  # Instagram allows 5
    medical = "Educational, not medical advice." if q.get("format") == "diagnose" else "For learning only, not medical advice."
    credit = f"\n{CONFIG['credit']}." if q.get("format") in ("missing", "zoom") else ""
    return (f"{q['hook']}\n\n"
            f"{q['question']}\n{choices}\n"
            "Comment your answer 👇 (answer at the bottom)\n"
            f"{FOLLOW.get(q.get('series', 'deepdive'), FOLLOW['deepdive'])}\n\n"
            + " ".join(tags) + "\n\n.\n.\n.\n"
            f"✅ Answer: {answer_text(q)}\n"
            + re.sub(r"^[A-D][:,.)]\s*", "", q["why"]) + "\n"
            + medical + credit)


def youtube_title(q: dict) -> str:
    return f"{q['title']}: {q['question']} #shorts"[:100]


def download(q: dict, out: Path) -> float:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(fetch(f"{source(q.get('series', 'deepdive'))}/{q['id']}.mp4", timeout=300))
    return float(q["seconds"])


def publish_dir(name: str, folder: Path) -> None:
    """Upload every <id>.mp4 with its <id>.json in folder, then rebuild the series' index.json."""
    rel = release(name)
    if subprocess.run(["gh", "release", "view", rel, "-R", REPO], capture_output=True).returncode:
        subprocess.run(["gh", "release", "create", rel, "-R", REPO, "--title", f"Anatomy Ace: {name}",
                        "--notes", "Finished videos. index.json lists them in posting order."], check=True)
    infos = {p.stem: json.loads(p.read_text()) for p in sorted(folder.glob("*.json")) if p.name != "index.json"}
    for vid in infos:
        subprocess.run(["gh", "release", "upload", rel, "-R", REPO, "--clobber",
                        str(folder / f"{vid}.mp4"), str(folder / f"{vid}.json")], check=True)
    try:
        old = {v["id"]: v for v in json.loads(fetch(f"{source(name)}/index.json"))}
    except Exception:
        old = {}
    merged = {**old, **infos}
    order = settings(name).get("order", [])
    listing = [merged[i] for i in order if i in merged] + [v for i, v in merged.items() if i not in order]
    (folder / "index.json").write_text(json.dumps(listing, indent=1, ensure_ascii=False) + "\n")
    subprocess.run(["gh", "release", "upload", rel, "-R", REPO, "--clobber", str(folder / "index.json")], check=True)
    print(f"{name}: index lists {len(listing)} videos")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "publish" and sys.argv[2] in SERIES:
        publish_dir(sys.argv[2], Path(sys.argv[3]))
    else:
        raise SystemExit(__doc__)
