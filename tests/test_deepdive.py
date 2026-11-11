"""Anatomy Deep Dives: the deep dive slot posts the next finished video in index order, never twice; with none
ready it posts a quiz; captions put the answer at the very bottom; quizzes keep their organ rotation around them."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from anatomy import buffer, hits, publish, series

TZ = ZoneInfo("America/New_York")
VIDEOS = [{"id": f"dd-{n}", "title": t, "hook": "Your kidneys filter about 180 liters a day.",
           "question": "Which part makes your urine concentrated?",
           "choices": ["Proximal tubule", "Loop of Henle", "Distal tubule", "Collecting duct"], "answer": "D",
           "why": "ADH adds water channels in the collecting duct.", "seconds": 51.2, "music": "ambient-2"}
          for n, t in (("nephron", "Inside a nephron"), ("na-k-pump", "The sodium-potassium pump"))]


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "HISTORY", tmp_path / "history.json")
    monkeypatch.setattr(hits, "PATH", tmp_path / "hits.json")  # no real hits in these plans
    monkeypatch.setattr(series, "_INDEX", {"deepdive": list(VIDEOS), "formats": []})
    monkeypatch.setitem(publish.CONFIG, "deepdive", {"slots": ["18:00"], "from": "2000-01-01"})
    monkeypatch.setitem(publish.CONFIG, "formats", {})
    monkeypatch.setattr(series, "CONFIG", publish.CONFIG)


def test_the_deep_dive_slot_posts_videos_in_order_then_quizzes(setup, monkeypatch):
    now = datetime(2030, 1, 1, 6, 0, tzinfo=TZ)
    plan = publish.plan(now)
    dives = [(at, q) for at, q in plan if q.get("kind") == "deepdive"]
    assert [f"{at:%H:%M}" for at, _ in dives] == ["18:00", "18:00"]
    assert [q["id"] for _, q in dives] == ["dd-nephron", "dd-na-k-pump"]
    monkeypatch.setitem(series._INDEX, "deepdive", VIDEOS[:1])  # only one ready: the next day's 18:00 is a quiz
    plan = publish.plan(now)
    dives = [(at, q) for at, q in plan if q.get("kind") == "deepdive"]
    later = [q for at, q in plan if f"{at:%H:%M}" == "18:00" and at > dives[-1][0]]
    assert later and all(q.get("kind") != "deepdive" and q["organ"] for q in later), "none left: quizzes fill in"
    quizzes = [q["organ"] for _, q in plan if q.get("kind") != "deepdive"]
    order = publish.CONFIG["rotation"]
    assert quizzes == [order[k % len(order)] for k in range(len(quizzes))], "deep dives don't break the rotation"
    days = [q["day"] for _, q in plan]
    assert days == list(range(1, len(plan) + 1))


def test_an_unreachable_index_means_quizzes(setup, monkeypatch):
    monkeypatch.setattr(series, "_INDEX", {})
    monkeypatch.setattr(series, "fetch", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    plan = publish.plan(datetime(2030, 1, 1, 6, 0, tzinfo=TZ))
    assert plan and all(q.get("kind") != "deepdive" for _, q in plan)


def test_the_caption_hides_the_answer_at_the_bottom():
    q = {**VIDEOS[0], "kind": "deepdive", "series": "deepdive", "day": 9}
    text = publish.caption(q)
    assert text.startswith(q["hook"]) and "Comment your answer" in text
    assert text.index("Comment your answer") < text.index("Answer: D) Collecting duct")
    assert text.count("#") <= 5 and "not medical advice" in text
    assert len(publish.youtube_title(q)) <= 100 and publish.youtube_title(q).endswith("#shorts")


def test_a_failed_deep_dive_is_queued_again_with_its_caption(setup, monkeypatch):
    slot = (datetime.now(ZoneInfo("UTC")) - timedelta(hours=2)).isoformat()
    hist = [{"slot": slot, "day": 3, "id": "dd-nephron", "organ": None, "kind": "deepdive", "title": "Inside a nephron",
             "video_url": "https://x/v.mp4", "video_seconds": 51.2, "buffer": {"tiktok": "old"}}]
    monkeypatch.setattr(buffer, "post_status", lambda pid: {"status": "error" if pid == "old" else "sent"})
    monkeypatch.setattr(buffer, "channel_for", lambda s, c, p: {"id": "c", "service": s})
    sent = []
    monkeypatch.setattr(buffer, "schedule_video", lambda ch, text, url, due, **k: sent.append(text) or "new1")
    assert publish.retry_failed(hist, []) == 0
    assert sent and sent[0].startswith(VIDEOS[0]["hook"]) and hist[0]["buffer"]["tiktok"] == "new1"


CYCLE = ["missing", "zoom", "diagnose", "myth", "rank"]
FORMATS = [{"id": f"fmt-{f}-0{k}", "format": f, "title": f.title(), "hook": "Find it.", "question": "Which one?",
            "choices": ["Myth", "Fact"] if f == "myth" else ["Liver", "Brain", "Lungs", "Heart"],
            "answer": "C, A, D, B" if f == "rank" else "A", "why": "Because.", "seconds": 24.0}
           for f in CYCLE for k in (1, 2, 3)]


@pytest.fixture
def formats(setup, monkeypatch):
    monkeypatch.setitem(series._INDEX, "formats", list(FORMATS))
    monkeypatch.setitem(publish.CONFIG, "formats", {"slots": ["12:30", "16:00"], "from": "2030-01-01", "cycle": CYCLE})


def test_two_formats_a_day_cycling_through_all_five(formats):
    days = {}
    for d in range(5):
        at = datetime(2030, 1, 1 + d, 12, 30, tzinfo=TZ)
        days[d] = [series.wanted_format("formats", at), series.wanted_format("formats", at.replace(hour=16, minute=0))]
    assert all(a != b for a, b in days.values()), "never the same format twice in a day"
    seen = [f for pair in days.values() for f in pair]
    assert sorted(seen) == sorted(CYCLE * 2), "every format twice in five days"


def test_the_format_slots_post_in_rotation_and_fall_through(formats, monkeypatch):
    plan = publish.plan(datetime(2030, 1, 1, 6, 0, tzinfo=TZ))
    fmts = [(f"{at:%m-%d %H:%M}", q["format"]) for at, q in plan if q.get("kind") == "formats"]
    assert fmts[:2] == [("01-01 12:30", "missing"), ("01-01 16:00", "zoom")]
    assert all(q.get("kind") in ("formats", "deepdive") or q["organ"] for _, q in plan)
    # nothing left in "missing": its turn passes to the next format in the cycle
    monkeypatch.setitem(series._INDEX, "formats", [v for v in FORMATS if v["format"] != "missing"])
    plan = publish.plan(datetime(2030, 1, 1, 6, 0, tzinfo=TZ))
    assert [q["format"] for at, q in plan if q.get("kind") == "formats"][:2] == ["zoom", "diagnose"], "no repeat in a day"
    # only one format has anything: it fills both slots rather than leaving one to a quiz
    monkeypatch.setitem(series._INDEX, "formats", [v for v in FORMATS if v["format"] == "myth"])
    plan = publish.plan(datetime(2030, 1, 1, 6, 0, tzinfo=TZ))
    assert [q["format"] for at, q in plan if q.get("kind") == "formats"][:2] == ["myth", "myth"]


def test_a_hook_that_repeats_the_question_isnt_printed_twice():
    q = {**FORMATS[-1], "hook": "Which one?", "kind": "formats", "series": "formats"}
    assert publish.caption(q).count("Which one?") == 1


def test_format_captions_rank_and_diagnose():
    rank = {**FORMATS[-1], "kind": "formats", "series": "formats"}
    assert "Answer: C, A, D, B (Lungs, Liver, Heart, Brain)" in publish.caption(rank)
    diag = {**FORMATS[6], "kind": "formats", "series": "formats"}
    assert publish.caption(diag).rstrip().endswith("Educational, not medical advice.")
    missing = {**FORMATS[0], "kind": "formats", "series": "formats"}
    assert "Z-Anatomy" in publish.caption(missing) and "new anatomy challenge" in publish.caption(missing)


def test_the_8pm_instagram_post_is_a_notify_me_post(setup, monkeypatch):
    monkeypatch.setitem(publish.CONFIG, "notify", {"service": "instagram", "slots": ["20:00"], "from": "2030-01-01",
                                                   "note": "Add a trending sound."})
    assert publish.notify_for(datetime(2030, 1, 2, 20, 0, tzinfo=TZ))["service"] == "instagram"
    assert publish.notify_for(datetime(2030, 1, 2, 9, 30, tzinfo=TZ)) is None
    assert publish.notify_for(datetime(2029, 12, 31, 20, 0, tzinfo=TZ)) is None


def test_rerender_queued_swaps_the_video_into_the_same_posts(setup, monkeypatch, tmp_path):
    """The rerender-queued action: only posts still waiting are re-rendered, and each new video replaces the old one
    in the same Buffer posts (same IDs), so the time and caption stay the same."""
    from anatomy import storage
    now = datetime.now(ZoneInfo("UTC"))
    hist = [{"slot": (now - timedelta(hours=3)).isoformat(), "day": 1, "id": "dd-nephron", "kind": "deepdive",
             "organ": None, "title": "t", "video_url": "old", "video_seconds": 50, "buffer": {"tiktok": "p0"}},
            {"slot": (now + timedelta(hours=5)).isoformat(), "day": 2, "id": "dd-na-k-pump", "kind": "deepdive",
             "organ": None, "title": "t", "video_url": "old", "video_seconds": 50,
             "buffer": {"tiktok": "p1", "youtube": "p2"}}]
    publish.HISTORY.write_text(json.dumps(hist))
    assert [h["id"] for h in publish.queued()] == ["dd-na-k-pump"]
    monkeypatch.setattr(publish, "ROOT", tmp_path)
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(series, "download", lambda q, out: (out.write_bytes(b"v"), 51.2)[1])
    assert publish.render_queued(hist[1]["slot"]) == 0
    monkeypatch.setattr(storage, "upload_to_r2", lambda path, key, r2: f"https://r2/{key}")
    swapped = []
    monkeypatch.setattr(buffer, "replace_video", lambda pid, service, url, ms, title="": swapped.append((pid, url, ms)))
    assert publish.swap_queued() == 0
    assert sorted(p for p, _, _ in swapped) == ["p1", "p2"] and all(ms == 50950 for _, _, ms in swapped)
    after = json.loads(publish.HISTORY.read_text())
    assert after[1]["video_url"].startswith("https://r2/") and after[1]["buffer"] == {"tiktok": "p1", "youtube": "p2"}
    assert after[0]["video_url"] == "old"


def test_plan_json_stays_pure_json_when_the_plan_warns(setup, monkeypatch, capsys):
    """Warnings go to stderr: on Nov 10, 2026 a "few videos left" warning landed in plan-json's output, the workflow
    couldn't read the slots, and nothing was queued for a day."""
    import sys
    monkeypatch.setattr(sys, "argv", ["publish", "plan-json"])
    monkeypatch.setattr(publish, "plan_now", lambda: datetime(2030, 1, 1, 6, 0, tzinfo=TZ))
    publish.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out), "stdout is only the JSON list of slots"
    assert "few videos left" in captured.err
