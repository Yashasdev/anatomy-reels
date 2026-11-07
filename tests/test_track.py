"""The tracker snapshots each post at fixed ages and the scorecard compares quizzes, deep dives and formats."""

import json
from datetime import datetime, timedelta, timezone

from anatomy import track


def test_snapshots_and_scorecard_by_type(tmp_path, monkeypatch):
    monkeypatch.setattr(track, "ROOT", tmp_path)
    now = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)
    sent = (now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hist = [{"slot": "2030-01-09T05:00:00+00:00", "day": 1, "id": "leg-03", "organ": "leg", "title": "The Leg",
             "video_seconds": 20.0, "buffer": {"instagram": "p1"}},
            {"slot": "2030-01-09T05:00:00+00:00", "day": 2, "id": "fmt-myth-01", "kind": "formats", "format": "myth",
             "title": "Myth or fact?", "video_seconds": 22.0, "buffer": {"instagram": "p2", "tiktok": "p3"}},
            {"slot": "2030-01-12T05:00:00+00:00", "day": 3, "id": "dd-x", "kind": "deepdive", "title": "X",
             "video_seconds": 50.0, "buffer": {"instagram": "p4"}}]
    (tmp_path / "history.json").write_text(json.dumps(hist))
    metrics = lambda views: {"status": "sent", "sentAt": sent, "metrics": [{"type": "views", "value": views},  # noqa: E731
                                                                          {"type": "averageTimeWatched", "value": 11.0}]}
    asked = []
    def fetch(ids):
        asked.extend(ids)
        return {"p1": metrics(100), "p2": metrics(300), "p3": metrics(500)}
    assert track.run(now, fetch) == []
    assert sorted(asked) == ["p1", "p2", "p3"], "a post not out yet isn't asked about"
    data = json.loads((tmp_path / "metrics.json").read_text())
    assert data["posts"]["p2"]["type"] == "myth" and "1d" in data["posts"]["p2"]["snapshots"]
    card = (tmp_path / "scorecard.md").read_text()
    assert "| myth | 2 | 400 |" in card and "| quiz | 1 | 100 |" in card
    assert "## Music style" not in card  # no post here has a music track
