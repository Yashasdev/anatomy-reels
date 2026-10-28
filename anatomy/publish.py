"""Queue Anatomy Ace reels: pick the next question, render it, upload it to R2 and schedule it on Buffer.

    python -m anatomy.publish plan               # what would be queued next (no secrets needed)
    python -m anatomy.publish render-only        # render the next posts into out/, post nothing
    python -m anatomy.publish publish            # render, upload and schedule (GitHub Actions only)
    python -m anatomy.publish list-channels      # the Buffer channels and their IDs
    python -m anatomy.publish check-setup        # Buffer channels and an R2 round trip; posts nothing

Every slot from config.json "start" on, within "days_ahead" days, gets one reel. Organs take turns in
"rotation" order and each organ's questions are used in bank order, so the schedule only depends on history.json.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
HISTORY = ROOT / "history.json"


def history() -> list[dict]:
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def banks() -> dict[str, list[dict]]:
    return {name: json.loads((ROOT / "banks" / f"{name}.json").read_text()) for name in CONFIG["rotation"]}


def next_question(used: list[str], last_organ: str | None) -> dict | None:
    """The next organ after the last one posted (skipping organs with nothing left), and its first unused question."""
    order = CONFIG["rotation"]
    start = (order.index(last_organ) + 1) % len(order) if last_organ in order else 0
    all_banks = banks()
    for k in range(len(order)):
        organ = order[(start + k) % len(order)]
        fresh = [q for q in all_banks[organ] if q["id"] not in used]
        if fresh:
            return {**fresh[0], "organ": organ}
    return None


def per_day(unused: int) -> int:
    """How many reels a day: config "ramp" steps up as the banks fill ([unused questions needed, reels a day]),
    and steps back down by itself if the Writer falls behind, so the account never runs dry."""
    return max(n for need, n in CONFIG["ramp"] if unused >= need)


def due_slots(now: datetime, hist: list[dict], unused: int) -> list[datetime]:
    """Slots from today through days_ahead that are still in the future (20+ minutes) and not queued yet, keeping
    at most max_queued posts waiting in Buffer (its free plan holds 10 per channel)."""
    tz = ZoneInfo(CONFIG["timezone"])
    taken = {h["slot"] for h in hist}
    waiting = sum(1 for h in hist if datetime.fromisoformat(h["slot"]) > now)
    # only after the last queued post, so day numbers always go out in order (a ramp-up adds slots to later days)
    after = max((datetime.fromisoformat(h["slot"]) for h in hist), default=now)
    first = max(date.fromisoformat(CONFIG["start"]), now.astimezone(tz).date())
    times = sorted(CONFIG["slots"][:per_day(unused)])  # slots are listed in the order they're added
    out = []
    for d in range(CONFIG["days_ahead"]):
        day = first + timedelta(days=d)
        for hhmm in times:
            at = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tz)
            if at > now + timedelta(minutes=20) and at > after and at.isoformat() not in taken:
                out.append(at)
    return out[: max(0, CONFIG["max_queued"] - waiting)]


def plan_now() -> datetime:
    """One clock for every job of a run (PLAN_NOW), so the render jobs and the posting job agree on the plan."""
    fixed = os.environ.get("PLAN_NOW")
    return datetime.fromisoformat(fixed) if fixed else datetime.now(ZoneInfo("UTC"))


def plan(now: datetime | None = None) -> list[tuple[datetime, dict]]:
    now = now or plan_now()
    hist = history()
    used = [h["id"] for h in hist]
    last = hist[-1]["organ"] if hist else None
    out = []
    unused = sum(len(b) for b in banks().values()) - len(used)
    for at in due_slots(now, hist, unused):
        q = next_question(used, last)
        if q is None:
            print(f"::warning::the question banks are used up; nothing for {at:%b %d %H:%M}")
            break
        q["day"] = len(hist) + len(out) + 1
        q["label"] = CONFIG["label"]
        out.append((at, q))
        used.append(q["id"])
        last = q["organ"]
    left = sum(len(b) for b in banks().values()) - len(used)
    if left < 14:
        print(f"::warning::only {left} unused anatomy questions left (about {left // per_day(left)} days)")
    return out


def caption(q: dict) -> str:
    tags = CONFIG["hashtags"][:5]  # Instagram allows 5
    return (f"Day {q['day']} · {q['title']}: {q['question']}\n"
            "Comment your answer before the reveal 👇\n"
            "Follow for a new body part every day.\n\n"
            f"{CONFIG['credit']}. For learning only, not medical advice.\n"
            + " ".join(tags))


def youtube_title(q: dict) -> str:
    return f"{q['question']} {q['title']} | Anatomy Check #{q['day']} #shorts"[:100]


def render(q: dict, out: Path) -> float:
    from .make import build
    return build(q, out)


def file_name(at: datetime, q: dict) -> str:
    return f"{at:%Y-%m-%d-%H%M}-{q['id']}"


def render_one(slot: str) -> int:
    """Render the reel planned for one slot (each runs on its own GitHub machine)."""
    at, q = next((at, q) for at, q in plan() if at.isoformat() == slot)
    out = ROOT / "out" / f"{file_name(at, q)}.mp4"
    seconds = render(q, out)
    out.with_suffix(".json").write_text(json.dumps({"slot": slot, "id": q["id"], "seconds": seconds}))
    print(f"rendered {out.name} ({seconds:.1f} s): Day {q['day']} {q['id']} for {at:%a %b %d %I:%M %p} ET")
    return 0


def post() -> int:
    """Upload and schedule the rendered reels in slot order, stopping at the first one that's missing, so the
    questions and day numbers stay in order (the next run renders the missing one again)."""
    from . import buffer, storage

    hist = history()
    channels = buffer.channels()
    failed = 0
    for at, q in plan():
        out = ROOT / "out" / f"{file_name(at, q)}.mp4"
        if not out.exists():
            print(f"::warning::{out.name} wasn't rendered; it and the slots after it wait for the next run")
            return 1
        if at < datetime.now(ZoneInfo("UTC")) + timedelta(minutes=5):
            print(f"::warning::{out.name} is too close to its time to schedule; skipping")
            continue
        seconds = json.loads(out.with_suffix(".json").read_text())["seconds"]
        url = storage.upload_to_r2(out, out.name, CONFIG["r2"])
        cover_ms = int((seconds - 0.25) * 1000)  # the designed cover frame is the last half second
        posts = {}
        for service in CONFIG["platforms"]:
            try:
                ch = buffer.channel_for(service, channels, CONFIG["channels"].get(service))
                posts[service] = buffer.schedule_video(ch, caption(q), url, at.astimezone(ZoneInfo("UTC")).isoformat(),
                                                       title=youtube_title(q), thumbnail_ms=cover_ms)
                print(f"queued Day {q['day']} {q['id']} on {service} for {at:%a %b %d %I:%M %p} ET: {posts[service]}")
            except Exception as e:  # one network failing shouldn't stop the others
                failed += 1
                print(f"::error::{service} failed for {q['id']}: {e}")
        if not posts:
            return 1
        hist.append({"slot": at.isoformat(), "day": q["day"], "id": q["id"], "organ": q["organ"],
                     "title": q["title"], "video_url": url, "video_seconds": round(seconds, 2), "buffer": posts})
        HISTORY.write_text(json.dumps(hist, indent=2) + "\n")
    return 1 if failed else 0


def publish(dry: bool) -> int:
    from . import buffer, storage

    todo = plan()[: int(os.environ.get("LIMIT") or 0) or None]  # LIMIT=1 for a quick test
    if not todo:
        print("Nothing to queue: every slot in the window is already scheduled.")
        return 0
    hist = history()
    channels = None if dry else buffer.channels()
    failed = 0
    for at, q in todo:
        name = f"{at:%Y-%m-%d-%H%M}-{q['id']}"
        out = ROOT / "out" / f"{name}.mp4"
        seconds = render(q, out)
        print(f"rendered {out.name} ({seconds:.1f} s): Day {q['day']} {q['id']} for {at:%a %b %d %I:%M %p} ET")
        if dry:
            continue
        url = storage.upload_to_r2(out, f"{name}.mp4", CONFIG["r2"])
        cover_ms = int((seconds - 0.25) * 1000)  # the designed cover frame is the last half second
        posts = {}
        for service in CONFIG["platforms"]:
            try:
                ch = buffer.channel_for(service, channels, CONFIG["channels"].get(service))
                posts[service] = buffer.schedule_video(ch, caption(q), url, at.astimezone(ZoneInfo("UTC")).isoformat(),
                                                       title=youtube_title(q), thumbnail_ms=cover_ms)
                print(f"  queued on {service}: {posts[service]}")
            except Exception as e:  # one network failing shouldn't stop the others
                failed += 1
                print(f"::error::{service} failed for {q['id']}: {e}")
        if not posts:
            continue
        hist.append({"slot": at.isoformat(), "day": q["day"], "id": q["id"], "organ": q["organ"],
                     "title": q["title"], "video_url": url, "video_seconds": round(seconds, 2), "buffer": posts})
        HISTORY.write_text(json.dumps(hist, indent=2) + "\n")
    return 1 if failed else 0


def write_status() -> None:
    """status.json: what Reels HQ shows for Anatomy Ace (stock, daily rate, recent and queued posts). The daily
    workflow commits it, so the dashboard reads one public file instead of every bank."""
    hist = history()
    used = {h["id"] for h in hist}
    all_banks = banks()
    unused = sum(1 for b in all_banks.values() for q in b if q["id"] not in used)
    run = os.environ.get("GITHUB_RUN_ID")
    flag = os.environ.get("PUBLISHING_ENABLED")
    status = {
        "generated_at": datetime.now(ZoneInfo("UTC")).replace(microsecond=0).isoformat(),
        "run_url": f"https://github.com/Yashasdev/anatomy-reels/actions/runs/{run}" if run else None,
        "publishing": None if flag is None else flag.strip().lower() == "true",
        "name": CONFIG["name"], "platforms": CONFIG["platforms"],
        "per_day": per_day(unused), "unused": unused, "total": unused + len(used), "posted": len(hist),
        "ramp": CONFIG["ramp"],
        "banks": {n: {"total": len(b), "unused": sum(q["id"] not in used for q in b)} for n, b in all_banks.items()},
        "posts": [{"slot": h["slot"], "day": h["day"], "id": h["id"], "organ": h["organ"], "title": h["title"],
                   "video_url": h["video_url"], "platforms": sorted(h["buffer"])} for h in hist[-30:]],
    }
    (ROOT / "status.json").write_text(json.dumps(status, indent=1) + "\n")


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if action == "plan":
        for at, q in plan():
            print(f"{at:%a %b %d %I:%M %p}  Day {q['day']}  {q['id']}  {q['title']}: {q['question']}")
        return 0
    if action == "status":
        write_status()
        return 0
    if action == "plan-json":  # for the workflow: one render job per slot
        print(json.dumps([at.isoformat() for at, _ in plan()]))
        return 0
    if action == "render-one":
        return render_one(sys.argv[2])
    if action == "post":
        return post()
    if action in ("render-only", "publish"):
        return publish(dry=action == "render-only")
    from . import buffer, storage
    if action == "list-channels":
        for c in buffer.channels():
            print(f"{c['service']:10} {c['id']}  {c['name']}  paused={c['isQueuePaused']}")
        return 0
    if action == "check-setup":
        problems = []
        chans = buffer.channels()
        for service in CONFIG["platforms"]:
            try:
                ch = buffer.channel_for(service, chans, CONFIG["channels"].get(service))
                print(f"Buffer {service}: {ch['name']} ({ch['id']})" + ("  QUEUE PAUSED" if ch["isQueuePaused"] else ""))
            except Exception as e:
                problems.append(str(e))
        err = storage.round_trip(CONFIG["r2"], "setup-check.txt")
        print("R2 round trip: " + (err or "ok"))
        problems += [err] if err else []
        for p in problems:
            print(f"::error::{p}")
        return 1 if problems else 0
    raise SystemExit(f"unknown action {action!r}")


if __name__ == "__main__":
    sys.exit(main())
