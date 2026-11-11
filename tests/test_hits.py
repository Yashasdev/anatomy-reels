"""The hit check (anatomy/hits.py): a breakout Instagram post makes its series hot for 5 days, and the plan posts
more of that series first while it has stock; nothing else about the plan, or history, changes."""

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from anatomy import hits, publish, series

NOW = datetime(2030, 1, 20, 12, tzinfo=timezone.utc)
TZ = ZoneInfo("America/New_York")


def rec(pid, age_hours, views, *, platform="instagram", kind="quiz", vid=None, shares=1, reach=None, one_day=True):
    """A metrics.json record sent age_hours before NOW; one_day: its 1d snapshot equals its latest numbers."""
    reach = reach if reach is not None else views
    n = {"views": views, "reach": reach, "shares": shares}
    return pid, {"id": vid or pid, "day": 1, "title": "t", "platform": platform, "type": kind,
                 "sent_at": (NOW - timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "latest": n, "snapshots": {"1d": n} if one_day and age_hours >= 24 else {}}


def metrics(*extra, base_views=1000):
    """30 ordinary Instagram posts (1,000 views, 1 share per 1,000 reached) a day apart, plus `extra`."""
    posts = dict(rec(f"b{k}", 100 + 24 * k, base_views) for k in range(30))
    posts.update(dict(extra))
    return {"posts": posts}


def found(*extra, **kw):
    return {h["buffer_id"]: h["by"] for h in hits.detect(metrics(*extra, **kw), NOW)}


def test_views_need_3x_the_median_and_1000():
    assert found(rec("p", 30, 3000)) == {"p": ["views"]}
    assert found(rec("p", 30, 2999)) == {}
    # 3x a small median isn't enough under 1,000 views
    assert found(rec("p", 30, 900), base_views=200) == {}
    assert found(rec("p", 30, 1000), base_views=200) == {"p": ["views"]}


def test_shares_per_reach_need_3x_the_median_and_2_shares():
    assert found(rec("p", 30, 400, shares=2, reach=400)) == {"p": ["shares"]}  # 0.5% vs a 0.1% median
    assert found(rec("p", 30, 100, shares=1, reach=100)) == {}, "one share is never a hit"
    assert found(rec("p", 30, 3000, shares=10, reach=1000)) == {"p": ["views", "shares"]}


def test_only_instagram_posts_12_to_72_hours_old():
    assert found(rec("p", 11, 5000)) == {}
    assert found(rec("p", 13, 5000)) == {"p": ["views"]}
    assert found(rec("p", 71, 5000)) == {"p": ["views"]}
    assert found(rec("p", 73, 5000)) == {}
    assert found(rec("p", 30, 5000, platform="tiktok")) == {}


def test_the_baseline_is_the_last_30_at_one_day_old():
    m = metrics()
    for k in range(30, 60):  # older posts beyond the last 30 don't count
        m["posts"].update(dict([rec(f"old{k}", 100 + 24 * k, 50)]))
    m["posts"]["b0"]["latest"] = {"views": 99999, "reach": 99999, "shares": 1}  # grew later: its 1d snapshot counts
    young = dict([rec("y", 3, 0)])  # a post 3 hours old isn't part of the baseline either
    m["posts"].update(young)
    m["posts"].update(dict([rec("p", 30, 3000)]))
    out = hits.detect(m, NOW)
    assert [h["buffer_id"] for h in out] == ["p"] and out[0]["baseline"] == 1000
    # without a 1d snapshot, a post 12+ hours old counts with its latest numbers
    m2 = metrics(rec("p", 30, 3000))
    for k in range(30):
        m2["posts"][f"b{k}"]["snapshots"] = {}
        m2["posts"][f"b{k}"]["latest"] = {"views": 2000, "reach": 2000, "shares": 2}
    assert not hits.detect(m2, NOW), "3,000 isn't 3x a 2,000 median"
    m2["posts"]["p"]["latest"]["views"] = 6000
    assert [h["baseline"] for h in hits.detect(m2, NOW)] == [2000]


def test_too_few_posts_to_compare_is_no_verdict():
    posts = dict(rec(f"b{k}", 100 + 24 * k, 100) for k in range(5))
    posts.update(dict([rec("p", 30, 50000)]))
    assert hits.detect({"posts": posts}, NOW) == []


def test_each_type_is_compared_with_its_own_kind():
    """Deep dives are shared about 10x as much as quizzes: a deep dive is a hit only against other deep dives."""
    dives = [rec(f"d{k}", 100 + 24 * k, 2000, kind="deepdive", shares=20, reach=2000) for k in range(6)]  # 1% shares
    assert found(*dives, rec("p", 30, 2000, kind="deepdive", shares=24, reach=2000)) == {}, "1.2%: usual for a deep dive"
    assert found(*dives, rec("p", 30, 2000, kind="deepdive", shares=60, reach=2000)) == {"p": ["shares"]}, "3%: 3x"
    assert found(*dives, rec("p", 30, 5000, kind="deepdive")) == {}, "5,000 isn't 3x the deep dives' 2,000"
    assert found(*dives, rec("p", 30, 6000, kind="deepdive")) == {"p": ["views"]}
    # quizzes keep their own baseline (1,000 views, 0.1%), deep dives don't move it
    assert found(*dives, rec("p", 30, 3000)) == {"p": ["views"]}
    out = hits.detect(metrics(*dives, rec("p", 30, 6000, kind="deepdive")), NOW)
    assert out[0]["compared_with"] == "deepdive (6 posts)" and out[0]["baseline"] == 2000 and out[0]["factor"] == 3


def test_a_new_type_is_compared_with_everything_at_2x():
    few = [rec(f"m{k}", 100 + 24 * k, 5000, kind="myth") for k in range(5)]  # only 5 myths: not enough of its own
    assert found(*few, rec("p", 30, 2000, kind="myth")) == {"p": ["views"]}, "2x the overall median (1,000)"
    assert found(*few, rec("p", 30, 1900, kind="myth")) == {}
    assert found(*few, rec("p", 30, 500, kind="myth", shares=2, reach=500)) == {"p": ["shares"]}, "0.4% vs 0.1%"
    assert found(*few, rec("p", 30, 1000, kind="myth", shares=2, reach=1000)) == {"p": ["shares"]}, "0.2% is 2x"
    assert found(*few, rec("p", 30, 1000, kind="myth", shares=1, reach=1000)) == {}
    out = hits.detect(metrics(*few, rec("p", 30, 2000, kind="myth")), NOW)
    assert out[0]["compared_with"].startswith("all Instagram") and out[0]["factor"] == 2


DD = [{"id": i} for i in ("dd-nephron", "dd-onetake-rbc", "dd-onetake-heart", "dd-krebs-cycle", "dd-folic-acid")]


def test_series_names(monkeypatch):
    monkeypatch.setattr(series, "_MAP", {})
    assert series.series_name("deepdive", "dd-onetake-rbc", DD) == "onetake", "a family shares the id prefix"
    assert series.series_name("deepdive", "dd-nephron", DD) == "dd-nephron", "a one-off is its own series"
    assert series.series_name("deepdive", "dd-krebs-cycle", DD) == "dd-krebs-cycle"
    named = DD + [{"id": "dd-honey-baby", "series_name": "future-parents"}]
    named[4] = {"id": "dd-folic-acid", "series_name": "future-parents"}
    assert series.series_name("deepdive", "dd-folic-acid", named) == "future-parents", "a json's series_name"
    assert series.series_name("formats", {"id": "fmt-types-02", "format": "types"}, []) == "types"
    # the repo's series.json wins: exact ids, then patterns
    monkeypatch.setattr(series, "_MAP", {"dd-x-*": "xs", "dd-folic-acid": "parents", "dd-x-special": "special"})
    assert series.series_name("deepdive", "dd-folic-acid", named) == "parents"
    assert series.series_name("deepdive", "dd-x-one", []) == "xs" and series.series_name("deepdive", "dd-x-special", []) == "special"


def test_the_repo_series_map(monkeypatch):
    monkeypatch.setattr(series, "_MAP", None)  # read the real series.json
    only = [{"id": "dd-onetake-rbc"}, {"id": "dd-folic-acid"}, {"id": "dd-honey-baby"}, {"id": "dd-nephron"}]
    assert [series.series_name("deepdive", v["id"], only) for v in only] == \
        ["onetake", "future-parents", "future-parents", "dd-nephron"]
    assert series.series_name("deepdive", "dd-onetake-heart", only) == "onetake", "any dd-onetake-*"


def test_a_hit_is_recorded_once_and_hot_for_5_days(monkeypatch, tmp_path):
    monkeypatch.setattr(series, "_MAP", {})
    monkeypatch.setattr(series, "_INDEX", {"deepdive": DD, "formats": []})
    data = {"hits": []}
    f = hits.detect(metrics(rec("p", 30, 5000, kind="deepdive", vid="dd-onetake-rbc"),
                            rec("q", 30, 5000, kind="quiz", vid="leg-03")), NOW)
    new = hits.record(data, f, date(2030, 1, 20))
    assert {(h["post"], h["series"], h["until"]) for h in new} == {("dd-onetake-rbc", "onetake", "2030-01-24"),
                                                                    ("leg-03", None, "2030-01-24")}
    assert hits.record(data, f, date(2030, 1, 21)) == [] and len(data["hits"]) == 2, "seen again: not a new hit"
    assert hits.hot("deepdive", date(2030, 1, 20), data) == ("onetake",)
    assert hits.hot("deepdive", date(2030, 1, 24), data) == ("onetake",)
    assert hits.hot("deepdive", date(2030, 1, 25), data) == (), "expired after 5 days"
    assert hits.hot("formats", date(2030, 1, 20), data) == (), "a quiz hit changes nothing"


def test_run_saves_hits_json(monkeypatch, tmp_path):
    monkeypatch.setattr(hits, "ROOT", tmp_path)
    monkeypatch.setattr(hits, "PATH", tmp_path / "hits.json")
    monkeypatch.setattr(series, "_INDEX", {"deepdive": [], "formats": []})
    (tmp_path / "config.json").write_text(json.dumps({"timezone": "America/New_York"}))
    m = metrics(rec("p", 30, 5000, kind="myth", vid="fmt-myth-03"))
    (tmp_path / "metrics.json").write_text(json.dumps(m))
    hits.run(NOW)
    saved = json.loads((tmp_path / "hits.json").read_text())["hits"]
    assert [(h["series"], h["post"], h["views"], h["baseline"], h["date"], h["until"]) for h in saved] == \
        [("myth", "fmt-myth-03", 5000, 1000, "2030-01-20", "2030-01-24")]


# --- the plan --------------------------------------------------------------------------------------------------

VIDEOS = [{"id": i, "title": "t", "hook": "h", "question": "q?", "choices": ["a", "b", "c", "d"], "answer": "A",
           "why": "w", "seconds": 40.0}
          for i in ("dd-nephron", "dd-onetake-rbc", "dd-caffeine", "dd-blind-spot", "dd-onetake-heart",
                    "dd-onetake-lungs")]
CYCLE = ["missing", "zoom", "myth"]
FORMATS = [{"id": f"fmt-{f}-0{k}", "format": f, "title": f, "hook": "h", "question": "q?",
            "choices": ["a", "b", "c", "d"], "answer": "A", "why": "w", "seconds": 20.0}
           for f in CYCLE for k in (1, 2, 3)]


def hit(post, kind, series_, day, **kw):
    d = date.fromisoformat(day)
    return {"post": post, "buffer_id": post, "kind": kind, "series": series_, "views": 5000, "baseline": 1000,
            "by": ["views"], "date": day, "until": (d + timedelta(days=4)).isoformat(), **kw}


@pytest.fixture
def plan_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "HISTORY", tmp_path / "history.json")
    monkeypatch.setattr(hits, "PATH", tmp_path / "hits.json")
    monkeypatch.setattr(series, "_MAP", {})  # series from the id-family rule here
    monkeypatch.setattr(series, "_INDEX", {"deepdive": list(VIDEOS), "formats": list(FORMATS)})
    monkeypatch.setitem(publish.CONFIG, "deepdive", {"slots": ["18:00"], "from": "2030-01-01"})
    monkeypatch.setitem(publish.CONFIG, "formats", {"slots": ["12:30", "16:00"], "from": "2030-01-01", "cycle": CYCLE})
    monkeypatch.setitem(publish.CONFIG, "max_queued", 15)  # three days of five
    monkeypatch.setattr(series, "CONFIG", publish.CONFIG)
    posted = [{"slot": "2029-12-31T18:00:00-05:00", "day": 1, "id": "dd-onetake-rbc", "kind": "deepdive",
               "organ": None, "title": "t", "video_url": "u", "video_seconds": 40, "buffer": {"instagram": "p1"}}]
    publish.HISTORY.write_text(json.dumps(posted))
    return tmp_path


def picks(kind):
    return [(f"{at:%m-%d %H:%M}", q["id"], q.get("hot")) for at, q in publish.plan(datetime(2030, 1, 1, 6, tzinfo=TZ))
            if q.get("kind") == kind]


def test_the_deep_dive_slot_posts_the_hot_series_first(plan_setup):
    before = picks("deepdive")
    assert [i for _, i, _ in before] == ["dd-nephron", "dd-caffeine", "dd-blind-spot"]
    hits.PATH.write_text(json.dumps({"hits": [hit("dd-onetake-rbc", "deepdive", "onetake", "2030-01-01")]}))
    after = picks("deepdive")
    assert after == [("01-01 18:00", "dd-onetake-heart", "onetake"), ("01-02 18:00", "dd-onetake-lungs", "onetake"),
                     ("01-03 18:00", "dd-nephron", None)], "the hot series' videos first, then index order again"
    hist = json.loads(publish.HISTORY.read_text())
    assert hist[0]["id"] == "dd-onetake-rbc", "history isn't touched"


def test_a_hot_format_takes_its_turn_first_once_a_day(plan_setup):
    before = picks("formats")
    hits.PATH.write_text(json.dumps({"hits": [hit("fmt-myth-01", "formats", "myth", "2030-01-01", format="myth")]}))
    after = picks("formats")
    days = {}
    for slot, vid, hot in after:
        days.setdefault(slot[:5], []).append((vid.split("-")[1], hot))
    assert days["01-01"][0] == ("myth", "myth"), "the hot format goes first"
    assert all(sum(f == "myth" for f, _ in v) == 1 for v in days.values()), "at most once a day"
    assert before != after


def test_an_expired_hit_changes_nothing(plan_setup):
    before = publish.plan(datetime(2030, 1, 1, 6, tzinfo=TZ))
    hits.PATH.write_text(json.dumps({"hits": [hit("dd-onetake-rbc", "deepdive", "onetake", "2029-12-27")]}))
    assert hits.hot("deepdive", date(2029, 12, 31)) == ("onetake",)
    assert publish.plan(datetime(2030, 1, 1, 6, tzinfo=TZ)) == before, "hot Dec 27-31 only"


def test_a_hot_series_with_no_stock_changes_nothing(plan_setup, monkeypatch):
    monkeypatch.setitem(series._INDEX, "deepdive", [v for v in VIDEOS if v["id"] not in ("dd-onetake-heart", "dd-onetake-lungs")])
    before = publish.plan(datetime(2030, 1, 1, 6, tzinfo=TZ))
    hits.PATH.write_text(json.dumps({"hits": [hit("dd-onetake-rbc", "deepdive", "onetake", "2030-01-01"),
                                              hit("leg-03", "quiz", None, "2030-01-01")]}))
    assert hits.hot("deepdive", date(2030, 1, 1)) == ("dd-onetake-rbc",), "a one-off again: nothing left of it"
    assert publish.plan(datetime(2030, 1, 1, 6, tzinfo=TZ)) == before


def test_low_stock_warns_and_shows_in_status(plan_setup, capsys):
    data = {"hits": [hit("dd-onetake-rbc", "deepdive", "onetake", "2030-01-01"),
                     hit("fmt-zoom-01", "formats", "zoom", "2030-01-01", format="zoom")]}
    rows = hits.report(date(2030, 1, 2), ["dd-onetake-rbc", "fmt-zoom-01"], data)
    assert {(r["series"], r["left"], r["make_more"]) for r in rows} == {("onetake", 2, True), ("zoom", 2, True)}
    assert "onetake is a hit: make more" in capsys.readouterr().err
    assert hits.report(date(2030, 1, 9), [], data) == [], "nothing hot after it expires"
