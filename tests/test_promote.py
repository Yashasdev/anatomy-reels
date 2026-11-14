"""Sequels after a hit: a queued post becomes a series video in place (same Buffer posts, time and day number)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from anatomy import buffer, publish, series, storage


def test_promote_swaps_a_queued_post_for_a_series_video(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "HISTORY", tmp_path / "history.json")
    monkeypatch.setattr(publish, "ROOT", tmp_path)
    slot = "2026-11-14T12:30:00-05:00"
    old = {"slot": slot, "day": 71, "id": "fmt-missing-03", "title": "Which bone is missing?", "kind": "formats",
           "format": "missing", "video_url": "https://x/old.mp4", "video_seconds": 20, "buffer": {"instagram": "p1", "youtube": "p2"}}
    (tmp_path / "history.json").write_text(json.dumps([old]))
    video = {"id": "fmt-types-02", "format": "types", "title": "5 knee injuries athletes get", "hook": "Most ACL tears happen with nobody touching you.",
             "question": "5 knee injuries athletes get. Which one have you had?", "choices": [], "answer": "",
             "why": "ACL tear.", "seconds": 54.07, "music": "pop-2", "hashtags": ["#acl"], "send": "Send this."}
    monkeypatch.setattr(series, "index", lambda name: [video] if name == "formats" else [])
    monkeypatch.setattr(publish, "render", lambda q, out: 54.07)
    monkeypatch.setattr(storage, "upload_to_r2", lambda path, name, r2: f"https://r2/{name}")
    edits = []
    monkeypatch.setattr(buffer, "replace_video", lambda pid, service, url, ms, title="", text=None, **k: edits.append((pid, url, text)) or pid)
    now = datetime(2026, 11, 14, 1, 0, tzinfo=ZoneInfo("UTC"))
    assert publish.promote("2026-11-14 12:30=fmt-types-02", now) == 0
    assert [e[0] for e in edits] == ["p1", "p2"] and all(e[2] for e in edits)
    h = json.loads((tmp_path / "history.json").read_text())[0]
    assert (h["id"], h["day"], h["slot"], h["buffer"], h["replaced"], h["kind"], h["format"]) == \
        ("fmt-types-02", 71, slot, old["buffer"], "fmt-missing-03", "formats", "types")
    # the same video again, or a slot that isn't queued, changes nothing
    assert publish.promote("2026-11-14 12:30=fmt-types-02", now) == 1
    assert publish.promote("2026-11-14 18:00=fmt-types-02", now) == 1


def test_captions_drop_pronunciation_marks():
    q = {"format": "types", "hook": "Hook.", "question": "Q?", "why": "a ligament [tears](tˈɛɹz) here", "hashtags": ["#a"]}
    assert "[tears]" not in series.caption(q) and "ligament tears here" in series.caption(q)
