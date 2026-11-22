"""The "How it works on your body" format (anatomy/howitworks.py, banks/howitworks/): every item's shots, labels and
chart fit what render/skin_scene.py draws, every line fits on screen, and the timeline lands in 35-50 s."""

import json
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from anatomy import howitworks as hiw
from anatomy import series, types

ROOT = Path(__file__).resolve().parent.parent
SCENE = (ROOT / "render" / "skin_scene.py").read_text()
PINS = set(re.findall(r'^    "(\w+)": ', SCENE.split("PINS = {")[1].split("}")[0], re.M))
ITEMS = hiw.items()
d = ImageDraw.Draw(Image.new("RGB", (10, 10)))


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_item(q):
    assert re.fullmatch(r"fmt-hiw-\d\d", q["id"])
    assert list(q["shots"]) == list(hiw.ORDER), "the scene draws these shots, in this order"
    said = sorted(i for ls in q["shots"].values() for i in ls)
    assert said == list(range(len(q["lines"]))), "every line belongs to exactly one shot, in order"
    for line in q["lines"]:
        assert len(types.wrap(d, types.shown(line), types.CAPTION(52), types.CAPTION_W)) <= 3, line
        assert not set("*[]()") & set(types.shown(line)), "markup must be well formed"
    for lb in q["labels"]:
        assert lb["pin"] in PINS, lb
        assert d.textlength(lb["text"], font=types.LABEL(74)) < 760, "inside x 120-960 with its leader"
        assert lb["from"] < lb["to"]
    assert len(q["hashtags"]) <= 5 and q["sources"]
    assert q["send"].startswith("Send this to") and types.shown(q["lines"][-1]).startswith("Send this to")
    assert types.shown(q["lines"][0]) == q["hook"]
    assert {c["shot"] for c in q["chart"]} <= set(hiw.ORDER)


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_length(q):
    """At the types pace, the video runs 35-50 s."""
    words = [len(types.shown(x).split()) for x in q["lines"]]
    lines = [(Path("x"), w / 2.95) for w in words]  # af_heart at 0.95 says about 3 words a second
    shots, cues, length = hiw.plan(q, lines)
    assert 35 <= length + hiw.COVER_TAIL <= 50, length
    assert shots[0]["start"] == 0 and all(a["end"] == b["start"] for a, b in zip(shots, shots[1:]))
    assert all(s["end"] > s["start"] for s in shots)


def test_posts_as_types():
    """It goes out in the types slot with the types caption: hook, the comment question, the send line."""
    q = {**ITEMS[0], "music": "ambient-2"}
    v = hiw.info(q, 45.0)
    assert v["format"] == "types" and v["choices"] == []
    text = series.caption(v)
    assert text.startswith(q["hook"]) and q["question"] in text and q["send"] in text
