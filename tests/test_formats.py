"""The "missing" and "zoom" formats (banks/formats/): real part names, one answer, a trap, lines that fit."""

import json
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from anatomy import formats, music
from anatomy.make import FORMATS, SANS, SERIF

ROOT = Path(__file__).resolve().parent.parent
PARTS = json.loads((ROOT / "assets" / "models" / "parts.json").read_text())
ITEMS = formats.items()
HOOKS = {"missing": "One bone is missing. Find it.", "zoom": "Comment the second you know what this is."}
d = ImageDraw.Draw(Image.new("RGB", (10, 10)))


def test_ids():
    for kind in FORMATS:
        bank = [q for q in ITEMS if q["kind"] == kind]
        assert [q["id"] for q in bank] == [f"fmt-{kind}-{k:02d}" for k in range(1, len(bank) + 1)]


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_item(q):
    parts = PARTS[q["model"]]
    named = q["reveal"] + q.get("hide", []) + q.get("focus_on", []) + q.get("zoom", {}).get("target", [])
    assert named and all(n in parts for n in named), "part names must be exact names from parts.json"
    if q["kind"] == "missing":
        assert q["hide"] == q["reveal"], "the missing bone is the one that fades back in"
        assert len(q["sway"]) == 2 and 20 <= q["sway"][0] <= 90, "swing around the view that shows the gap"
    else:
        assert "hide" not in q and set(q["zoom"]) <= {"target", "aim", "start", "orbit", "early"}
        assert 0.02 <= q["zoom"]["start"] <= 0.3
    c = q["choices"]
    assert len(c) == 4 and len(set(c)) == 4 and q["answer_index"] != q["trap_index"]
    assert d.textlength(q["question"], font=SERIF(50)) < 1000
    assert all(d.textlength(x, font=SERIF(36)) < 440 for x in c)
    assert d.textlength(q["title"], font=SERIF(42)) < 900
    hook = [x.strip() for x in re.findall(r"[^.?!]+[.?!]?", q["lines"][0].upper()) if x.strip()]
    assert len(hook) <= 2 and all(d.textlength(x, font=SANS(62)) < (900 if len(hook) == 2 else 1700) for x in hook), \
        "the hook banner is two rows: one per sentence, or one sentence split in two"
    if q.get("note"):
        assert d.textlength(q["note"], font=SERIF(34)) < 1000
    lines = q["lines"]
    assert lines[0] == HOOKS[q["kind"]]
    assert 5 <= len(lines) <= 9 and all(len(x) <= 75 for x in lines)
    assert 0 < q["ask_line"] < q["answer_line"] < len(lines)
    assert re.match(rf"It's {'ABCD'[q['answer_index']]}\b", lines[q["answer_line"]])
    assert lines[-1].startswith("Why it matters:" if q["kind"] == "missing" else "Fun fact:")
    assert q["why"].startswith(f"{'ABCD'[q['answer_index']]}) ") and len(q["why"]) <= 300
    assert 1 <= len(q["hashtags"]) <= 5 and all(t.startswith("#") for t in q["hashtags"])
    assert q["sources"] and all(s.startswith("https://openstax.org/books/anatomy-and-physiology-2e/") for s in q["sources"])
    assert -180 <= q.get("start_degrees", -20) <= 180 and (1.0 if q.get("focus") else 2.0) <= q.get("distance", 4.2) <= 6.0


def test_answers_are_spread():
    for kind in FORMATS:
        letters = "".join("ABCD"[q["answer_index"]] for q in ITEMS if q["kind"] == kind)
        assert not re.search(r"(.)\1\1", letters), letters
        assert len(set(letters)) == 4, f"{kind}: use every letter ({letters})"


def test_music_is_original_and_varied():
    picked = formats.tracks(ITEMS)
    assert all(t in music.TRACKS for t in picked.values())
    order = list(picked.values())
    assert all(t not in order[max(0, k - 8):k] for k, t in enumerate(order))
