"""The Instagram "hint" first comment: only on Instagram, only when switched on and the video has a hint, never on
Notify-me posts; Buffer is asked afterwards whether it kept the comment, and a miss only warns (once a run)."""

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from anatomy import buffer, publish

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/New_York")
AT = datetime(2030, 1, 5, 18, 0, tzinfo=TZ)
Q = {"id": "dd-caffeine", "title": "Caffeine", "hook": "h", "question": "What does caffeine block?",
     "choices": ["a", "b", "c", "d"], "answer": "B", "why": "w", "kind": "deepdive", "series": "deepdive", "day": 3}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setitem(publish.CONFIG, "first_comment", {"instagram": True, "from": "2030-01-01"})
    monkeypatch.setattr(publish, "_HINTS", {"dd-caffeine": "Hint: think about what builds up while you're awake."})
    monkeypatch.setattr(publish, "_COMMENT_WARNED", False)


@pytest.fixture
def sent(monkeypatch):
    """Every createPost input sent to Buffer."""
    inputs = []
    def gql(query, variables=None):
        if "createPost" in query:
            inputs.append(variables["input"])
            return {"createPost": {"post": {"id": f"p{len(inputs)}"}}}
        raise AssertionError(query)
    monkeypatch.setattr(buffer, "_gql", gql)
    return inputs


def test_first_comment_goes_on_instagram_only(sent):
    for service in ("instagram", "tiktok", "youtube"):
        buffer.schedule_video({"id": "c", "service": service}, "text", "https://v", "2030-01-05T23:00:00Z",
                              title="t", first_comment="Hint: x")
    ig, tt, yt = sent
    assert ig["metadata"]["instagram"]["firstComment"] == "Hint: x" and ig["metadata"]["instagram"]["type"] == "reel"
    assert "metadata" not in tt and "firstComment" not in json.dumps(yt)
    buffer.schedule_video({"id": "c", "service": "instagram"}, "text", "https://v", "2030-01-05T23:00:00Z")
    assert "firstComment" not in sent[-1]["metadata"]["instagram"], "no comment, no field"


def test_notify_me_posts_get_no_first_comment(sent):
    buffer.schedule_video({"id": "c", "service": "instagram"}, "text", "https://v", "2030-01-05T23:00:00Z",
                          notify="Add a trending sound.", first_comment="Hint: x")
    meta = sent[0]["metadata"]["instagram"]
    assert "firstComment" not in meta and meta["stickerFields"] == {"music": "Add a trending sound."}


def test_the_switch_the_date_and_the_hint(on, monkeypatch):
    assert publish.first_comment_for(AT, Q, "instagram") == "Hint: think about what builds up while you're awake."
    assert publish.first_comment_for(AT, Q, "tiktok") is None
    assert publish.first_comment_for(AT, Q, "instagram", notify="Add a sound.") is None
    assert publish.first_comment_for(AT.replace(year=2029), Q, "instagram") is None, "before the from date"
    assert publish.first_comment_for(AT, {**Q, "id": "dd-other"}, "instagram") is None, "no hint, no comment"
    assert publish.first_comment_for(AT, {**Q, "id": "leg-09", "hint": "count the bones"}, "instagram") == \
        "Hint: count the bones", "a bank item's own hint, with the Hint: label added"
    monkeypatch.setitem(publish.CONFIG, "first_comment", {"instagram": False, "from": "2030-01-01"})
    assert publish.first_comment_for(AT, Q, "instagram") is None, "switched off"
    monkeypatch.delitem(publish.CONFIG, "first_comment")
    assert publish.first_comment_for(AT, Q, "instagram") is None, "off when the config has no switch"


def test_a_read_back_miss_only_warns_once(on, sent, monkeypatch, capsys):
    kept = {"p1": "Hint: think about what builds up while you're awake."}
    monkeypatch.setattr(buffer, "first_comment", lambda pid: kept.get(pid))
    ch = {"id": "c", "service": "instagram"}
    comment = publish.first_comment_for(AT, Q, "instagram")
    assert publish.queue_post(ch, Q, "https://v", "2030-01-05T23:00:00Z", 100, comment=comment) == ("p1", True)
    assert publish.queue_post(ch, Q, "https://v", "2030-01-05T23:00:00Z", 100, comment=comment) == ("p2", False)
    assert publish.queue_post(ch, Q, "https://v", "2030-01-05T23:00:00Z", 100, comment=comment) == ("p3", False)
    assert capsys.readouterr().err.count("::warning::") == 1, "one warning a run"
    monkeypatch.setattr(buffer, "first_comment", lambda pid: (_ for _ in ()).throw(buffer.BufferError("down")))
    assert publish.queue_post(ch, Q, "https://v", "2030-01-05T23:00:00Z", 100, comment=comment) == ("p4", None)


def test_notify_me_through_queue_post_sends_no_comment(on, sent, monkeypatch):
    monkeypatch.setattr(buffer, "first_comment", lambda pid: pytest.fail("nothing to read back"))
    ch = {"id": "c", "service": "instagram"}
    assert publish.queue_post(ch, Q, "https://v", "2030-01-05T23:00:00Z", 100, note="Add a sound.",
                              comment="Hint: x") == ("p1", None)
    assert "firstComment" not in json.dumps(sent[0])


def test_a_retried_instagram_post_keeps_its_comment(on, monkeypatch, tmp_path):
    from datetime import timedelta
    monkeypatch.setattr(publish, "HISTORY", tmp_path / "history.json")
    slot = (datetime.now(ZoneInfo("UTC")) - timedelta(hours=2)).isoformat()
    hist = [{"slot": slot, "day": 3, "id": "leg-03", "organ": "leg", "title": "The Leg", "video_url": "https://x/v.mp4",
             "video_seconds": 20.0, "buffer": {"instagram": "old"}, "first_comment": "Hint: x"}]
    monkeypatch.setattr(buffer, "post_status", lambda pid: {"status": "error" if pid == "old" else "sent"})
    monkeypatch.setattr(buffer, "channel_for", lambda s, c, p: {"id": "c", "service": s})
    monkeypatch.setattr(buffer, "first_comment", lambda pid: "Hint: x")
    got = []
    monkeypatch.setattr(buffer, "schedule_video", lambda ch, text, url, due, **k: got.append(k) or "new1")
    assert publish.retry_failed(hist, []) == 0 and got[0]["first_comment"] == "Hint: x"


def test_the_hints_file():
    hints = json.loads((ROOT / "hints.json").read_text())
    assert hints
    for vid, text in hints.items():
        assert re.fullmatch(r"(dd|fmt)-[a-z0-9-]+", vid), vid
        assert text.startswith("Hint: ") and len(text) <= 140, vid
        assert len(re.findall(r"[.?!](\s|$)", text)) == 1 and text[-1] in ".?!", f"{vid}: one sentence"
