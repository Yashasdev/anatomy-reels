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


def test_shares_per_reach_is_the_main_score():
    """Shares per person reached, pooled over a group, sorts the tables and gets its own top 10."""
    from anatomy import track

    def rec(i, kind, shares, reach):
        n = {"views": reach + 50, "reach": reach, "shares": shares, "saves": 1, "averageTimeWatched": 5.0}
        return {"day": i, "id": f"x{i}", "type": kind, "title": kind, "platform": "instagram", "video_seconds": 20,
                "latest": n, "snapshots": {"1d": n}}
    data = {"posts": {"a": rec(1, "quiz", 1, 1000), "b": rec(2, "deepdive", 20, 1000), "c": rec(3, "quiz", 3, 1000)}}
    assert abs(track.per_reach(list(data["posts"].values()), "shares", "1d") - 24 / 3000) < 1e-9
    text = track.scorecard(data)
    table = text.split("### By type")[1]
    assert table.index("| deepdive | 1 | 2.00%") < table.index("| quiz | 2 | 0.20%"), "best sharer first"
    top = text.split("by shares per person reached")[1]
    assert top.index("| 2 |") < top.index("| 3 |") < top.index("| 1 |")
