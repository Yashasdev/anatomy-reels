"""Tracker: once a day, save every Anatomy Ace post's numbers from Buffer and write scorecard.md.

    python -m anatomy.track        # needs BUFFER_API_KEY (the daily workflow passes it)

metrics.json has one record per post per platform, keyed by Buffer post ID: what the post was (type: quiz, deep
dive or one of the rotating formats; organ; length; music), "latest" numbers, and "snapshots" at 1, 3, 7 and 30
days old so posts are compared at the same age. scorecard.md compares the types; the Strategist reads both.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MILESTONES = {"1d": 1, "3d": 3, "7d": 7, "30d": 30}
GRACE_HOURS = 48
COLUMNS = [("views", "Views"), ("reactions", "Likes"), ("comments", "Comments"), ("shares", "Shares"),
           ("saves", "Saves"), ("averageTimeWatched", "Avg watch (s)")]


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def post_type(entry: dict) -> str:
    """quiz, deepdive, or the format's name (missing, zoom, diagnose, myth, rank)."""
    if entry.get("kind") == "formats":
        return entry.get("format", "format")
    return entry.get("kind") or "quiz"


def describe(entry: dict, platform: str) -> dict:
    return {"slot": entry["slot"], "day": entry["day"], "id": entry["id"], "type": post_type(entry),
            "organ": entry.get("organ"), "title": entry.get("title"), "platform": platform,
            "video_seconds": entry.get("video_seconds"), "music": entry.get("music"),
            "sound": "trending (by hand)" if entry.get("notify") == platform else "original track"}


def update(hist: list[dict], data: dict, now: datetime, fetch) -> list[str]:
    posts, notes, todo = data["posts"], [], []
    for entry in hist:
        if parse_time(entry["slot"]) > now:
            continue  # not out yet
        for platform, post_id in entry["buffer"].items():
            if not posts.get(post_id, {}).get("done"):
                todo.append((entry, platform, post_id))
    results = fetch([pid for _, _, pid in todo]) if todo else {}
    for entry, platform, post_id in todo:
        post = results.get(post_id)
        label = f"Day {entry['day']} {entry['id']} {platform}"
        if post is None:
            notes.append(f"{label}: Buffer can't find post {post_id}")
            continue
        if post.get("status") != "sent" or not post.get("sentAt"):
            if post.get("status") not in ("scheduled", "sending"):
                notes.append(f"{label}: Buffer status is {post.get('status')}")
            continue
        rec = posts.setdefault(post_id, {"snapshots": {}})
        rec.update(describe(entry, platform), sent_at=post["sentAt"], link=post.get("externalLink"))
        age = (now - parse_time(post["sentAt"])).total_seconds() / 3600
        snap = {"checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "age_hours": round(age, 1),
                **{m["type"]: m["value"] for m in post.get("metrics") or []}}
        rec["latest"] = snap
        for name, days in MILESTONES.items():
            if name not in rec["snapshots"] and days * 24 <= age < days * 24 + GRACE_HOURS:
                rec["snapshots"][name] = snap
        if age >= MILESTONES["30d"] * 24 + GRACE_HOURS or "30d" in rec["snapshots"]:
            rec["done"] = True
    data["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return notes


def _avg(values: list) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "–"
    mean = sum(values) / len(values)
    return f"{mean:,.1f}" if mean < 100 else f"{mean:,.0f}"


def _watched(recs: list[dict], snap: str) -> str:
    shares = [r["snapshots"][snap]["averageTimeWatched"] / r["video_seconds"] for r in recs
              if "averageTimeWatched" in r["snapshots"][snap] and r.get("video_seconds")]
    return f"{100 * sum(shares) / len(shares):.0f}%" if shares else "–"


def _table(groups: dict, snap: str, key_name: str) -> list[str]:
    head = [key_name, "Posts"] + [t for _, t in COLUMNS] + ["Watched"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for key, recs in sorted(groups.items()):
        cells = [str(key), str(len(recs))] + [_avg([r["snapshots"][snap].get(m) for r in recs]) for m, _ in COLUMNS]
        lines.append("| " + " | ".join(cells + [_watched(recs, snap)]) + " |")
    return lines


def scorecard(data: dict) -> str:
    recs = list(data["posts"].values())
    out = ["# Anatomy Ace scorecard", "",
           f"Updated {data.get('updated_at', '?')}. Averages per post at the same age (Buffer's numbers). "
           "Types: quiz (3D bone/organ quiz), deepdive, and the rotating formats (missing, zoom, diagnose, myth, rank). "
           "YouTube reports only views, likes and comments through Buffer.", ""]
    for snap in ("1d", "7d"):
        have = [r for r in recs if snap in r["snapshots"]]
        out += [f"## At {snap} old", ""]
        if not have:
            out += ["No posts this old yet.", ""]
            continue
        by_type = defaultdict(list)
        for r in have:
            by_type[r["type"]].append(r)
        out += ["### By type (all platforms)", ""] + _table(by_type, snap, "Type") + [""]
        for platform in sorted({r["platform"] for r in have}):
            g = defaultdict(list)
            for r in have:
                if r["platform"] == platform:
                    g[r["type"]].append(r)
            out += [f"### {platform.title()}", ""] + _table(g, snap, "Type") + [""]
    have = [r for r in recs if "1d" in r["snapshots"] and r["platform"] == "instagram" and r.get("sound")]
    if any(r["sound"] != "original track" for r in have):
        g = defaultdict(list)
        for r in have:
            g[f"{r['type']} / {r['sound']}"].append(r)
        out += ["## Trending sound vs original track (Instagram, 1 day old)", "",
                "The 8 PM quiz goes out as Buffer 'Notify me' and is finished by hand with an Instagram trending sound.", ""]
        out += _table(g, "1d", "Type / sound") + [""]
    top = sorted((r for r in recs if r.get("latest")), key=lambda r: -(r["latest"].get("views") or 0))[:10]
    if top:
        out += ["## Top 10 posts by views so far", "", "| Day | Type | Post | Platform | Views | Comments | Shares |",
                "|---|---|---|---|---|---|---|"]
        out += [f"| {r['day']} | {r['type']} | {r['title']} | {r['platform']} | {r['latest'].get('views', '–')} | "
                f"{r['latest'].get('comments', '–')} | {r['latest'].get('shares', '–')} |" for r in top]
    return "\n".join(out) + "\n"


def run(now: datetime, fetch) -> list[str]:
    hist = json.loads((ROOT / "history.json").read_text())
    path = ROOT / "metrics.json"
    data = json.loads(path.read_text()) if path.exists() else {"posts": {}}
    notes = update(hist, data, now, fetch)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    (ROOT / "scorecard.md").write_text(scorecard(data))
    return notes


def main() -> int:
    from .buffer import post_metrics
    for note in run(datetime.now(timezone.utc), post_metrics):
        print(note)
    print("metrics.json and scorecard.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
