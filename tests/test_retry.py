"""A post a platform failed to publish is queued again once; a second failure is reported once, never looped."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from anatomy import buffer, publish


def test_retry_once_then_report_once(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "HISTORY", tmp_path / "history.json")
    slot = (datetime.now(ZoneInfo("UTC")) - timedelta(hours=2)).isoformat()
    hist = [{"slot": slot, "day": 1, "id": "heart-01", "organ": "heart", "title": "The Heart",
             "video_url": "https://x/v.mp4", "video_seconds": 18.5, "buffer": {"tiktok": "old", "youtube": "ok"}}]
    monkeypatch.setattr(buffer, "post_status", lambda pid: {"status": "error" if pid in ("old", "new1") else "sent"})
    monkeypatch.setattr(buffer, "channel_for", lambda s, c, p: {"id": "c", "service": s})
    sent = []
    monkeypatch.setattr(buffer, "schedule_video", lambda ch, text, url, due, **k: sent.append((ch["service"], url)) or "new1")
    assert publish.retry_failed(hist, []) == 0 and sent == [("tiktok", "https://x/v.mp4")]
    assert hist[0]["buffer"]["tiktok"] == "new1" and hist[0]["retried"] == {"tiktok": "old"}
    assert publish.retry_failed(hist, []) == 1 and hist[0]["gave_up"] == ["tiktok"]
    assert publish.retry_failed(hist, []) == 0 and len(sent) == 1
