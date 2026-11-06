"""Anatomy Deep Dives: the deep dive slot posts the next finished video in index order, never twice; with none
ready it posts a quiz; captions put the answer at the very bottom; quizzes keep their organ rotation around them."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from anatomy import buffer, deepdive, publish

TZ = ZoneInfo("America/New_York")
VIDEOS = [{"id": f"dd-{n}", "title": t, "hook": "Your kidneys filter about 180 liters a day.",
           "question": "Which part makes your urine concentrated?",
           "choices": ["Proximal tubule", "Loop of Henle", "Distal tubule", "Collecting duct"], "answer": "D",
           "why": "ADH adds water channels in the collecting duct.", "seconds": 51.2, "music": "ambient-2"}
          for n, t in (("nephron", "Inside a nephron"), ("na-k-pump", "The sodium-potassium pump"))]


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "HISTORY", tmp_path / "history.json")
    monkeypatch.setattr(deepdive, "_INDEX", list(VIDEOS))
    monkeypatch.setitem(publish.CONFIG, "deepdive", {"slots": ["18:00"], "from": "2000-01-01"})
    monkeypatch.setattr(deepdive, "CONFIG", publish.CONFIG)


def test_the_deep_dive_slot_posts_videos_in_order_then_quizzes(setup, monkeypatch):
    now = datetime(2030, 1, 1, 6, 0, tzinfo=TZ)
    plan = publish.plan(now)
    dives = [(at, q) for at, q in plan if q.get("kind") == "deepdive"]
    assert [f"{at:%H:%M}" for at, _ in dives] == ["18:00", "18:00"]
    assert [q["id"] for _, q in dives] == ["dd-nephron", "dd-na-k-pump"]
    monkeypatch.setattr(deepdive, "_INDEX", VIDEOS[:1])  # only one ready: the next day's 18:00 is a quiz
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
    monkeypatch.setattr(deepdive, "_INDEX", None)
    monkeypatch.setattr(deepdive, "fetch", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    plan = publish.plan(datetime(2030, 1, 1, 6, 0, tzinfo=TZ))
    assert plan and all(q.get("kind") != "deepdive" for _, q in plan)


def test_the_caption_hides_the_answer_at_the_bottom():
    q = {**VIDEOS[0], "kind": "deepdive", "day": 9}
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
