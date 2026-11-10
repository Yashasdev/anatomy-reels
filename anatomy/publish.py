"""Queue Anatomy Ace reels: pick the next question, render it, upload it to R2 and schedule it on Buffer.

    python -m anatomy.publish plan               # what would be queued next (no secrets needed)
    python -m anatomy.publish render-only        # render the next posts into out/, post nothing
    python -m anatomy.publish publish            # render, upload and schedule (GitHub Actions only)
    python -m anatomy.publish list-channels      # the Buffer channels and their IDs
    python -m anatomy.publish check-setup        # Buffer channels and an R2 round trip; posts nothing

Every slot from config.json "start" on, within "days_ahead" days, gets one reel. Organs take turns in
"rotation" order and each organ's questions are used in bank order, so the schedule only depends on history.json.
Slots named in config "deepdive" and "formats" post finished videos from those series instead (anatomy/series.py:
deep dives, and the five rotating short formats), or a quiz if none is ready.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import music, series

ROOT = Path(__file__).resolve().parent.parent
MUSIC_FROM = date(2026, 11, 1)  # posts from this day get original music (anatomy/music.py) instead of the old bed
CONFIG = json.loads((ROOT / "config.json").read_text())
HISTORY = ROOT / "history.json"


def history() -> list[dict]:
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def banks(active_only: bool = True) -> dict[str, list[dict]]:
    """The quiz banks in the rotation (or every bank, including ones paused from the daily quiz)."""
    names = CONFIG["rotation"] + ([] if active_only else CONFIG.get("quiz_paused", []))
    return {name: json.loads((ROOT / "banks" / f"{name}.json").read_text()) for name in names}


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


def unused_questions(used) -> int:
    used = set(used)
    return sum(q["id"] not in used for b in banks().values() for q in b)


def last_organ(hist: list[dict]) -> str | None:
    return next((h["organ"] for h in reversed(hist) if h.get("organ")), None)  # deep dives have no organ


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
    last = last_organ(hist)
    out = []
    unused = unused_questions(used)
    for at in due_slots(now, hist, unused):
        name = series.series_for(at)
        if name:
            today = tuple(q2.get("format") for at2, q2 in out if at2.date() == at.date() and q2.get("format"))
            video = series.next_video(name, at, used, today)
            if video:
                out.append((at, {**video, "kind": name, "series": name, "day": len(hist) + len(out) + 1}))
                used.append(video["id"])
                continue
            print(f"::warning::no new {name} video is ready for {at:%b %d %H:%M}; posting a quiz there instead")
        q = next_question(used, last)
        if q is None:
            print(f"::warning::the question banks are used up; nothing for {at:%b %d %H:%M}")
            break
        q["day"] = len(hist) + len(out) + 1
        q["label"] = CONFIG["label"]
        if at.date() >= MUSIC_FROM:  # an original track, never one of the last eight
            recent = [h["music"] for h in hist if h.get("music")] + [q2.get("music") for _, q2 in out]
            q["music"] = music.pick(q["day"] * 7919, avoid=[m for m in recent if m][-8:],
                                    styles=CONFIG.get("music_styles"))
        out.append((at, q))
        used.append(q["id"])
        last = q["organ"]
    for name in series.SERIES:
        if series.settings(name) and series.index(name):
            counts = series.left(name, used)
            low = {k: counts.get(k, 0) for k in series.settings(name).get("cycle", [name]) if counts.get(k, 0) < 4}
            if low:
                print(f"::warning::{name}: few videos left after this plan ({low}); make more")
    left = unused_questions(used)
    if left < 14:
        print(f"::warning::only {left} unused anatomy questions left (about {left // per_day(left)} days)")
    return out


def caption(q: dict) -> str:
    if q.get("kind") in series.SERIES:
        return series.caption(q)
    tags = CONFIG["hashtags"][:5]  # Instagram allows 5
    return (f"Day {q['day']} · {q['title']}: {q['question']}\n"
            "Comment your answer before the reveal 👇\n"
            "Follow for a new body part every day.\n\n"
            f"{CONFIG['credit']}. For learning only, not medical advice.\n"
            + " ".join(tags))


def youtube_title(q: dict) -> str:
    if q.get("kind") in series.SERIES:
        return series.youtube_title(q)
    return f"{q['question']} {q['title']} | Anatomy Check #{q['day']} #shorts"[:100]


def render(q: dict, out: Path) -> float:
    if q.get("kind") in series.SERIES:  # made and checked ahead of time; just download it
        return series.download(q, out)
    from .make import build
    return build(q, out)


def file_name(at: datetime, q: dict) -> str:
    return f"{at:%Y-%m-%d-%H%M}-{q['id']}"


def notify_for(at: datetime) -> dict | None:
    """The trending-sound test (config "notify": {"service", "slots", "from", "note"}): that platform's post in these
    slots goes out as Buffer "Notify me", so Yashas can add a trending sound in the Instagram app before posting."""
    n = CONFIG.get("notify")
    if not n or f"{at:%H:%M}" not in n["slots"] or at.date().isoformat() < n["from"] or at.date().isoformat() > n.get("until", "9999"):
        return None
    return n


def entry(at: datetime, q: dict, url: str, seconds: float, posts: dict) -> dict:
    return {"slot": at.isoformat(), "day": q["day"], "id": q["id"], "organ": q.get("organ"),
            "title": q["title"], "video_url": url, "video_seconds": round(seconds, 2), "buffer": posts,
            **({"kind": q["kind"]} if q.get("kind") else {}), **({"format": q["format"]} if q.get("format") else {}),
            **({"music": q["music"]} if q.get("music") else {})}


def render_one(slot: str) -> int:
    """Render the reel planned for one slot (each runs on its own GitHub machine)."""
    at, q = next((at, q) for at, q in plan() if at.isoformat() == slot)
    out = ROOT / "out" / f"{file_name(at, q)}.mp4"
    seconds = render(q, out)
    out.with_suffix(".json").write_text(json.dumps({"slot": slot, "id": q["id"], "seconds": seconds}))
    print(f"rendered {out.name} ({seconds:.1f} s): Day {q['day']} {q['id']} for {at:%a %b %d %I:%M %p} ET")
    return 0


def retry_failed(hist: list[dict], channels: list[dict]) -> int:
    """Posts from the last 3 days a platform failed to publish: queue each again once, 15 minutes from now (same
    video and caption). One that fails after its retry is reported once, never looped. Returns failures."""
    from . import buffer
    now, failures, changed = datetime.now(ZoneInfo("UTC")), 0, False
    banks_by_id = {q["id"]: q for b in banks(active_only=False).values() for q in b}
    for h in hist:
        if datetime.fromisoformat(h["slot"]) < now - timedelta(days=3):
            continue
        for service, pid in list(h["buffer"].items()):
            try:
                if buffer.post_status(pid).get("status") != "error":
                    continue
            except Exception:
                continue
            print(f"Day {h['day']} {h['id']} failed on {service} in Buffer.")
            if service in h.get("retried", {}):
                if service not in h.get("gave_up", []):
                    h.setdefault("gave_up", []).append(service)
                    print(f"::error::Day {h['day']} on {service} failed again after one retry; check Buffer.")
                    failures += 1
                    changed = True
                continue
            if h.get("kind") in series.SERIES:
                q = next((v for v in series.index(h["kind"]) if v["id"] == h["id"]), None)
                if q is None:
                    print(f"::error::{h['id']} isn't in the {h['kind']} index any more; not retried.")
                    failures += 1
                    continue
                q = {**q, "kind": h["kind"], "series": h["kind"]}
            else:
                q = {**banks_by_id[h["id"]], "day": h["day"]}
            due = (now + timedelta(minutes=15)).isoformat()
            try:
                ch = buffer.channel_for(service, channels, CONFIG["channels"].get(service))
                new = buffer.schedule_video(ch, caption(q), h["video_url"], due, title=youtube_title(q),
                                            thumbnail_ms=int((h["video_seconds"] - 0.25) * 1000))
            except Exception as e:
                print(f"::error::Retry on {service} failed: {e}")
                failures += 1
                continue
            h.setdefault("retried", {})[service] = pid
            h["buffer"][service] = new
            changed = True
            print(f"  queued again on {service}: {new}")
    if changed:
        HISTORY.write_text(json.dumps(hist, indent=2) + "\n")
    return failures


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
                hand = notify_for(at)
                note = hand["note"] if hand and service == hand["service"] else None
                posts[service] = buffer.schedule_video(ch, caption(q), url, at.astimezone(ZoneInfo("UTC")).isoformat(),
                                                       title=youtube_title(q), thumbnail_ms=cover_ms, notify=note)
                print(f"queued Day {q['day']} {q['id']} on {service} for {at:%a %b %d %I:%M %p} ET: {posts[service]}")
            except Exception as e:  # one network failing shouldn't stop the others
                failed += 1
                print(f"::error::{service} failed for {q['id']}: {e}")
        if not posts:
            return 1
        hist.append(entry(at, q, url, seconds, posts))
        hand = notify_for(at)
        if hand and hand["service"] in posts:
            hist[-1]["notify"] = hand["service"]
        HISTORY.write_text(json.dumps(hist, indent=2) + "\n")
    try:
        failed += retry_failed(hist, channels)
    except Exception as e:
        print(f"::warning::Couldn't check for failed posts: {e}")
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
                hand = notify_for(at)
                note = hand["note"] if hand and service == hand["service"] else None
                posts[service] = buffer.schedule_video(ch, caption(q), url, at.astimezone(ZoneInfo("UTC")).isoformat(),
                                                       title=youtube_title(q), thumbnail_ms=cover_ms, notify=note)
                print(f"  queued on {service}: {posts[service]}")
            except Exception as e:  # one network failing shouldn't stop the others
                failed += 1
                print(f"::error::{service} failed for {q['id']}: {e}")
        if not posts:
            continue
        hist.append(entry(at, q, url, seconds, posts))
        hand = notify_for(at)
        if hand and hand["service"] in posts:
            hist[-1]["notify"] = hand["service"]
        HISTORY.write_text(json.dumps(hist, indent=2) + "\n")
    return 1 if failed else 0


def metrics_summary(metrics: dict) -> dict | None:
    """What Reels HQ shows: all-time totals and, per platform, posts, views and the average share watched at 1 day."""
    recs = list(metrics.get("posts", {}).values())
    if not recs:
        return None
    def total(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return sum(vals) if vals else None
    by_platform = []
    for platform in CONFIG["platforms"]:
        items = [r for r in recs if r.get("platform") == platform]
        watch = [100 * r["snapshots"]["1d"]["averageTimeWatched"] / r["video_seconds"] for r in items
                 if r.get("video_seconds") and isinstance(r.get("snapshots", {}).get("1d", {}).get("averageTimeWatched"), (int, float))]
        by_platform.append({"platform": platform, "posts": len(items), "views": total(r.get("latest", {}).get("views") for r in items),
                            "watched": round(sum(watch) / len(watch), 1) if watch else None, "watch_samples": len(watch)})
    return {"updated_at": metrics.get("updated_at"),
            "totals": {m: total(r.get("latest", {}).get(m) for r in recs) for m in ("views", "reactions", "comments", "shares", "saves")},
            "by_platform": by_platform}


def queued(now: datetime | None = None) -> list[dict]:
    """History entries still waiting in Buffer (due 30+ minutes from now): the posts a re-render can still fix."""
    now = now or plan_now()
    return [h for h in history() if datetime.fromisoformat(h["slot"]) > now + timedelta(minutes=30)]


def queued_question(h: dict) -> dict:
    """What a queued post was made from: its bank question, or its series video (downloaded again, so a video that
    was re-rendered and republished on the release comes back fixed)."""
    if h.get("kind") in series.SERIES:
        video = next((v for v in series.index(h["kind"]) if v["id"] == h["id"]), None)
        if video is None:
            raise LookupError(f"{h['id']} isn't in the {h['kind']} index")
        return {**video, "kind": h["kind"], "series": h["kind"], "day": h["day"]}
    q = next(q for b in banks(active_only=False).values() for q in b if q["id"] == h["id"])
    return {**q, "organ": h.get("organ"), "day": h["day"], "label": CONFIG["label"],
            **({"music": h["music"]} if h.get("music") else {})}


def render_queued(slot: str) -> int:
    """Re-render one queued post with the current templates (a render job of the rerender-queued action)."""
    h = next(h for h in history() if h["slot"] == slot)
    q = queued_question(h)
    out = ROOT / "out" / f"{file_name(datetime.fromisoformat(slot), q)}-v{datetime.now(ZoneInfo('UTC')):%H%M}.mp4"
    seconds = render(q, out)
    out.with_suffix(".json").write_text(json.dumps({"slot": slot, "id": q["id"], "seconds": seconds, "rerender": True}))
    print(f"re-rendered {out.name} ({seconds:.1f} s) for the queued Day {h['day']} {h['id']}")
    return 0


def swap_queued() -> int:
    """Upload each re-rendered video and swap it into the same Buffer posts (same post IDs, time and caption)."""
    from . import buffer, storage
    hist, failed = history(), 0
    for meta in sorted((ROOT / "out").glob("*.json")):
        info = json.loads(meta.read_text())
        if not info.get("rerender"):
            continue
        h = next((x for x in hist if x["slot"] == info["slot"] and x["id"] == info["id"]), None)
        video = meta.with_suffix(".mp4")
        if h is None or not video.exists() or datetime.fromisoformat(h["slot"]) <= datetime.now(ZoneInfo("UTC")) + timedelta(minutes=10):
            print(f"::warning::{meta.stem}: not queued any more (or too close to its time); left as it was")
            continue
        url = storage.upload_to_r2(video, video.name, CONFIG["r2"])
        q = queued_question(h)
        cover_ms = int((info["seconds"] - 0.25) * 1000)
        for service, pid in h["buffer"].items():
            try:
                buffer.replace_video(pid, service, url, cover_ms, title=youtube_title(q))
                print(f"swapped the video for Day {h['day']} {h['id']} on {service}")
            except Exception as e:
                failed += 1
                print(f"::error::{service} swap failed for {h['id']}: {e}")
        h.update(video_url=url, video_seconds=round(info["seconds"], 2), rerendered=datetime.now(ZoneInfo("UTC")).date().isoformat())
        HISTORY.write_text(json.dumps(hist, indent=2) + "\n")
    return 1 if failed else 0


def write_status() -> None:
    """status.json: what Reels HQ shows for Anatomy Ace (stock, daily rate, recent and queued posts). The daily
    workflow commits it, so the dashboard reads one public file instead of every bank."""
    hist = history()
    used = {h["id"] for h in hist}
    all_banks = banks()
    unused = unused_questions(used)
    mpath = ROOT / "metrics.json"
    metrics = json.loads(mpath.read_text()) if mpath.exists() else {}
    sent = set(metrics.get("posts", {}))  # Buffer post IDs the tracker has seen go out
    run = os.environ.get("GITHUB_RUN_ID")
    flag = os.environ.get("PUBLISHING_ENABLED")
    status = {
        "generated_at": datetime.now(ZoneInfo("UTC")).replace(microsecond=0).isoformat(),
        "run_url": f"https://github.com/Yashasdev/anatomy-reels/actions/runs/{run}" if run else None,
        "publishing": None if flag is None else flag.strip().lower() == "true",
        "name": CONFIG["name"], "platforms": CONFIG["platforms"],
        "per_day": per_day(unused), "unused": unused, "total": unused + len(used), "posted": len(hist),
        "ramp": CONFIG["ramp"],
        "series": {n: {"slots": series.settings(n).get("slots", []), "from": series.settings(n).get("from"),
                       "cycle": series.settings(n).get("cycle"), "posted": sum(h.get("kind") == n for h in hist)}
                   for n in series.SERIES if series.settings(n)},
        "banks": {n: {"total": len(b), "unused": sum(q["id"] not in used for q in b)} for n, b in all_banks.items()},
        "posts": [{"slot": h["slot"], "day": h["day"], "id": h["id"], "organ": h["organ"], "title": h["title"],
                   "video_url": h["video_url"], "platforms": sorted(h["buffer"]),
                   "sent": sorted(pl for pl, pid in h["buffer"].items() if pid in sent)} for h in hist[-30:]],
        "metrics": metrics_summary(metrics),
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
    if action == "queued-json":  # for the workflow's rerender-queued action: one render job per queued post
        print(json.dumps([h["slot"] for h in queued()]))
        return 0
    if action == "render-queued":
        return render_queued(sys.argv[2])
    if action == "swap-queued":
        return swap_queued()
    if action == "post":
        return post()
    if action in ("render-only", "publish"):
        return publish(dry=action == "render-only")
    from . import buffer, storage
    if action == "list-channels":
        for c in buffer.channels():
            print(f"{c['service']:10} {c['id']}  {c['name']}  paused={c['isQueuePaused']}")
        return 0
    if action == "show-posts":  # read-only: what Buffer says happened to every post in history
        bad = 0
        now = datetime.now(ZoneInfo("UTC"))
        for h in history():
            due = datetime.fromisoformat(h["slot"])
            for service, pid in h["buffer"].items():
                try:
                    st = buffer.post_status(pid)
                    status, link = st.get("status"), st.get("externalLink") or ""
                except Exception as e:
                    status, link = f"unreadable ({e})", ""
                late = due < now - timedelta(minutes=30) and status != "sent"
                bad += late
                print(f"{'PROBLEM ' if late else ''}Day {h['day']:>2} {h['id']:12} {due:%b %d %I:%M %p} {service:9} {status} {link}")
        print(f"{bad} post(s) past their time without going out" if bad else "Every post past its time went out.")
        return 1 if bad else 0
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
