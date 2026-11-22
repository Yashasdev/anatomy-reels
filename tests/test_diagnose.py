"""The gray-studio "Diagnose this" cases (anatomy/diagnose.py, banks/diagnose/): every show names real parts, the
answers are spread across A-D, the reveal and trap lines name the right choices, every line and label fits, and the
caption carries the send line and the model credit without giving the answer away above the fold."""

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from anatomy import diagnose, series, types
from tests.test_types import points

ROOT = Path(__file__).resolve().parent.parent
PARTS = json.loads((ROOT / "assets" / "models" / "parts.json").read_text())
ITEMS = diagnose.items()
d = ImageDraw.Draw(Image.new("RGB", (10, 10)))


def test_the_bank_is_what_its_script_writes():
    import runpy
    before = (ROOT / "banks" / "diagnose" / "studio.json").read_text()
    runpy.run_path(str(ROOT / "scripts" / "diagnose_bank.py"))
    assert (ROOT / "banks" / "diagnose" / "studio.json").read_text() == before, "rerun scripts/diagnose_bank.py"


def test_answers_are_spread_and_ids_are_unique():
    assert len({q["id"] for q in ITEMS}) == len(ITEMS)
    letters = [q["answer"] for q in ITEMS]
    assert set(letters[:4]) == set("ABCD"), "the first four use every letter once"


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_item(q):
    assert q["id"].startswith("fmt-diagnose-") and len(q["choices"]) == 4
    assert q["answer"] in "ABCD" and q["trap"] in "ABCD" and q["answer"] != q["trap"]
    answer, trap = (q["choices"]["ABCD".index(x)] for x in (q["answer"], q["trap"]))
    L = {k: [types.shown(x) for x in v] for k, v in q["lines"].items()}
    assert L["reveal"][0].startswith(f"It's {q['answer']}, the ")
    assert answer.split(" (")[0].lower() in L["reveal"][0].lower()
    assert trap.split(" (")[0].lower() in L["trap"][0].lower() and "trap" in L["trap"][0].lower()
    assert L["ask"] == [q["question"], "Comment your answer."]
    assert len(L["send"]) == 1 and L["send"][0].startswith("Send this to") and q["send"].startswith("Send this to")
    for line in q["script"]:
        assert not set("*[]()") & set(types.shown(line)), "markup must be well formed"
        assert len(types.wrap(d, types.shown(line), types.CAPTION(52), types.CAPTION_W)) <= 3, line
    assert len(q["hashtags"]) <= 5 and q["sources"] and q["credit"]
    for label in (q["symptom_label"], q["answer_label"], q["trap_label"]):  # shrinks to 44 px at most
        assert d.textlength(label, font=types.LABEL(44)) <= 760, label
    assert q["trap_label"].startswith("TRAP: ")


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_shows_name_real_parts(q):
    assert set(q["shows"]) == set(diagnose.SHOTS)
    for name, s in q["shows"].items():
        model = PARTS[s["model"]]
        assert (ROOT / "assets" / "models" / f"{s['model']}.blend").exists()
        parts = set(s.get("parts") or model)
        assert parts <= set(model), name
        known = parts | {b["name"] for b in s.get("blobs", [])}
        for key in ("lit", "hurt", "ghost"):
            assert set(s.get(key, [])) <= known, (name, key)
        for mv in s.get("moves", []):
            assert set(mv["parts"]) <= parts
        for p in points(s):
            if "xyz" not in p:
                assert p["part"] in known and all(0 <= f <= 1 for f in p["at"]), (name, p)
        if any(p.get("part") in {b["name"] for b in s.get("blobs", [])} for p in [s["pin"]]):
            assert "focus" in s, "a pin on a blob needs its own focus (else the camera aims at the origin)"
    assert q["shows"]["answer"].get("lit") and q["shows"]["trap"].get("hurt")


def test_the_timeline_follows_the_narration():
    q = ITEMS[0]
    lines = [(Path("x"), 2.0)] * len(q["script"])
    segs, cues, marks = diagnose.plan(q, lines)
    assert [s["name"] for s in segs] == list(diagnose.SHOTS)
    assert all(a["end"] == b["start"] for a, b in zip(segs, segs[1:]))
    assert cues[0]["at"] < 0.2, "the case is said from the first frame"
    comment = next(c for c in cues if c["text"] == "Comment your answer.")
    assert comment["at"] == marks["count"], "the countdown starts with the spoken call to comment"
    assert marks["count"] + diagnose.COUNT < marks["answer"] + 0.2
    assert all(segs[i]["start"] <= c["at"] < segs[i]["end"] for c in cues for i in [diagnose.SHOTS.index(c["shot"])])


def test_the_card_stays_in_the_phone_safe_area():
    x0, y0, x1, y1 = diagnose.CARD
    assert x0 >= 60 and x1 <= 900 and y0 >= diagnose.ZONE[1] and y1 + 50 <= diagnose.CAPTION_LOW - 62


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_the_caption_has_the_send_line_and_credit_and_hides_the_answer(q):
    info = diagnose.info({**q, "music": "lofi-1"}, 25.0)
    assert info["hold"] is True and "voice" not in info and "credit_voice" not in info
    text = series.caption({**info, "series": "formats"})
    assert q["send"] in text and text.rstrip().endswith(q["credit"] + ".")
    assert text.index(q["send"]) < text.index("✅ Answer")
    assert "clone" not in text.lower()
