"""Hit check: when a post takes off, post more of the same series while it's hot.

    python -m anatomy.hits         # after the tracker (track.yml): find hits, update hits.json, warn on low stock

Why: a small account grows when it follows a hit fast with more of the same (RedPenPrep posts sequels in the same
series within a day). Once a day, after metrics.json is updated, an Instagram post 12-72 hours old is a **hit** when

- its latest views are at least 3x the median of Anatomy's last 30 Instagram posts at about the same age (their
  1-day snapshot where there is one, else their latest numbers if they're 12+ hours old) and at least 1,000, or
- its shares per person reached are at least 3x the median of the same posts, with 2 or more shares.

A hit makes its series **hot** for 5 days (the day it's found and the 4 after): a deep dive's series is its family
(anatomy/series.py series_name: dd-onetake-rbc -> onetake, or one-offs by their own id), a format's is the format.
Quizzes aren't a series: their hits are recorded and reported but change nothing. While a series is hot, its slot
posts it first (publish.plan): the deep dive slot takes the hot series' next video, and a formats slot gives the hot
format its turn first, at most once a day. With nothing of it in stock, nothing changes. History still stores ids,
so rebuilds are untouched. A hot series with fewer than 3 videos left gets a "make more" warning (and status.json).
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "hits.json"
FACTOR = 3            # times the median
MIN_VIEWS = 1000      # and at least this many views
MIN_SHARES = 2        # a share-rate hit needs at least this many shares
AGE_HOURS = (12, 72)  # posts this old are checked
BASELINE = 30         # the last 30 Instagram posts
MIN_BASELINE = 10     # fewer comparable posts than this: no verdict
HOT_DAYS = 5
LOW_STOCK = 3


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load() -> dict:
    """hits.json; an unreadable file means no hot series (the plan must never fail on it)."""
    try:
        return json.loads(PATH.read_text()) if PATH.exists() else {"hits": []}
    except Exception as e:
        print(f"::warning::Couldn't read hits.json ({e}); no series is treated as hot.", file=sys.stderr)
        return {"hits": []}


def series_kind(entry: dict) -> str:
    """deepdive, formats or quiz, from a history entry (or a metrics record's type)."""
    if entry.get("kind") in ("deepdive", "formats"):
        return entry["kind"]
    if entry.get("type") == "deepdive":
        return "deepdive"
    if entry.get("type") and entry["type"] != "quiz":
        return "formats"
    return "quiz"


def _numbers(rec: dict, now: datetime) -> dict | None:
    """A baseline post's numbers at about one day old: its 1d snapshot, else its latest if it's 12+ hours old."""
    snap = rec.get("snapshots", {}).get("1d")
    if snap:
        return snap
    age = (now - parse_time(rec["sent_at"])).total_seconds() / 3600 if rec.get("sent_at") else 0
    return rec.get("latest") if age >= AGE_HOURS[0] else None


def _rate(n: dict) -> float | None:
    return n["shares"] / n["reach"] if n.get("reach") and isinstance(n.get("shares"), (int, float)) else None


def detect(metrics: dict, now: datetime) -> list[dict]:
    """Instagram posts 12-72 hours old that are hits right now, with the numbers that made them one."""
    ig = sorted((dict(r, buffer_id=pid) for pid, r in metrics.get("posts", {}).items()
                 if r.get("platform") == "instagram" and r.get("sent_at") and parse_time(r["sent_at"]) <= now),
                key=lambda r: r["sent_at"])
    comparable = [(r, n) for r in ig if (n := _numbers(r, now)) and isinstance(n.get("views"), (int, float))]
    out = []
    for rec in ig:
        age = (now - parse_time(rec["sent_at"])).total_seconds() / 3600
        latest = rec.get("latest") or {}
        if not AGE_HOURS[0] <= age <= AGE_HOURS[1] or not isinstance(latest.get("views"), (int, float)):
            continue
        base = [n for r, n in comparable if r["buffer_id"] != rec["buffer_id"]][-BASELINE:]
        if len(base) < MIN_BASELINE:
            continue
        views_base = statistics.median(n["views"] for n in base)
        rates = [x for n in base if (x := _rate(n)) is not None]
        rate_base = statistics.median(rates) if rates else None
        by = []
        if latest["views"] >= max(FACTOR * views_base, MIN_VIEWS):
            by.append("views")
        rate = _rate(latest)
        if (rate is not None and rate_base and rate >= FACTOR * rate_base
                and latest.get("shares", 0) >= MIN_SHARES):
            by.append("shares")
        if by:
            out.append({"post": rec["id"], "buffer_id": rec["buffer_id"], "day": rec.get("day"),
                        "title": rec.get("title"), "kind": series_kind(rec),
                        **({"format": rec["type"]} if series_kind(rec) == "formats" else {}),
                        "age_hours": round(age, 1), "views": latest["views"], "baseline": round(views_base),
                        "shares": latest.get("shares"), "reach": latest.get("reach"),
                        "share_rate": round(rate, 4) if rate is not None else None,
                        "share_baseline": round(rate_base, 4) if rate_base is not None else None, "by": by})
    return out


def series_of(hit: dict) -> str | None:
    """The hit's series, worked out again from the current index, so a one-off that later gets sequels joins
    their family (falls back to what was recorded)."""
    from . import series
    if hit["kind"] == "quiz":
        return None
    if hit["kind"] == "formats":
        return hit.get("series") or hit.get("format")
    videos = series.index("deepdive")
    if videos and any(v["id"] == hit["post"] for v in videos):
        return series.series_name("deepdive", hit["post"], videos)
    return hit.get("series") or hit["post"]


def record(data: dict, found: list[dict], today: date) -> list[dict]:
    """Add new hits to data (a post is a hit once: later checks update its numbers, not its dates)."""
    known = {h["buffer_id"]: h for h in data.setdefault("hits", [])}
    new = []
    for f in found:
        if f["buffer_id"] in known:
            known[f["buffer_id"]].update({k: f[k] for k in ("views", "baseline", "shares", "reach", "share_rate",
                                                             "share_baseline", "age_hours")},
                                         by=sorted(set(known[f["buffer_id"]]["by"]) | set(f["by"])))
            continue
        hit = {**f, "series": None, "date": today.isoformat(),
               "until": (today + timedelta(days=HOT_DAYS - 1)).isoformat()}
        hit["series"] = series_of(hit)
        data["hits"].append(hit)
        new.append(hit)
    return new


def active(when: date, data: dict | None = None) -> list[dict]:
    """Hits whose series is hot on this day (quizzes left out), newest first, then the biggest."""
    data = load() if data is None else data
    on = [h for h in data.get("hits", []) if h["kind"] != "quiz" and h["date"] <= when.isoformat() <= h["until"]]
    return sorted(on, key=lambda h: (h["date"], h["views"] / max(h["baseline"], 1)), reverse=True)


def hot(name: str, when: date, data: dict | None = None) -> tuple[str, ...]:
    """The hot series for one of anatomy/series.py's series (deepdive or formats) on a day, best first."""
    out = []
    for h in active(when, data):
        s = series_of(h)
        if h["kind"] == name and s and s not in out:
            out.append(s)
    return tuple(out)


def stock(kind: str, name: str, used) -> int:
    from . import series
    videos = series.index(kind)
    return sum(1 for v in videos if v["id"] not in set(used) and series.series_name(kind, v, videos) == name)


def report(when: date, used, data: dict | None = None) -> list[dict]:
    """The hot series today with what's left in stock (status.json "hot"); warns for the ones running low."""
    out, seen = [], set()
    for h in active(when, data):
        s = series_of(h)
        if (h["kind"], s) in seen:
            continue
        seen.add((h["kind"], s))
        left = stock(h["kind"], s, used)
        row = {"series": s, "kind": h["kind"], "post": h["post"], "views": h["views"], "baseline": h["baseline"],
               "by": h["by"], "date": h["date"], "until": h["until"], "left": left, "make_more": left < LOW_STOCK}
        if row["make_more"]:
            print(f"::warning::{s} is a hit: make more ({left} left in stock; hot until {h['until']})", file=sys.stderr)
        out.append(row)
    return out


def run(now: datetime) -> list[dict]:
    """Find today's hits in metrics.json and save hits.json; returns the new ones."""
    metrics = json.loads((ROOT / "metrics.json").read_text())
    tz = ZoneInfo(json.loads((ROOT / "config.json").read_text())["timezone"])
    data = load()
    new = record(data, detect(metrics, now), now.astimezone(tz).date())
    data["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    PATH.write_text(json.dumps(data, indent=1) + "\n")
    for h in new:
        what = f"series {h['series']} is hot until {h['until']}" if h["series"] else "a quiz (no series, no effect)"
        why = []
        if "views" in h["by"]:
            why.append(f"{h['views']:,} views vs a median of {h['baseline']:,}")
        if "shares" in h["by"]:
            why.append(f"{h['shares']} shares, {100 * h['share_rate']:.2f}% of reach vs a median of "
                       f"{100 * h['share_baseline']:.2f}%")
        print(f"Hit: Day {h['day']} {h['post']} on Instagram ({'; '.join(why)}): {what}")
    return new


def main() -> int:
    now = datetime.now(timezone.utc)
    new = run(now)
    print(f"{len(new)} new hit(s); hits.json updated")
    hist = json.loads((ROOT / "history.json").read_text())
    tz = ZoneInfo(json.loads((ROOT / "config.json").read_text())["timezone"])
    report(now.astimezone(tz).date(), [h["id"] for h in hist])
    return 0


if __name__ == "__main__":
    sys.exit(main())
