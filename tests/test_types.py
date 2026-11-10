"""The "types" format (anatomy/types.py, banks/types/): every type is one Blender can break, lines fit on screen."""

import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from anatomy import publish, series, types

ROOT = Path(__file__).resolve().parent.parent
BUILT = set(re.findall(r'"(\w+)": \w+', re.search(r"BUILDERS = \{(.*?)\}", (ROOT / "render" / "fracture_scene.py")
                                                             .read_text(), re.S).group(1)))
ITEMS = types.items()
d = ImageDraw.Draw(Image.new("RGB", (10, 10)))


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_item(q):
    names = [t["name"] for t in q["types"]]
    assert len(set(names)) == len(names) and set(names) <= BUILT, "each type once, and one the Blender script builds"
    assert set(q["flash"]) <= set(names) and 4 <= len(q["flash"]) <= 6
    assert len(names) <= 11, "the closing chart has 11 places (rows of 4, 4 and 3)"
    assert str(len(names)) in q["intro"] and str(len(names)) in q["title"]
    for t in q["types"]:
        assert types.shown(t["lines"][0]).split(".")[0].split(",")[0].upper().startswith(t["label"].split()[0]), \
            "say the name first"
        assert d.textlength(t["label"], font=types.LABEL(70)) < 400
    for line in q["script"]:
        assert len(types.wrap(d, types.shown(line), types.CAPTION(52), types.CAPTION_W)) <= 3, line
        assert not set("*[]()") & set(types.shown(line)), "markup must be well formed"
    assert len(q["hashtags"]) <= 5 and q["sources"]


def test_the_caption_has_no_answer_key_and_credits_the_model():
    q = types.info({**ITEMS[0], "music": "lofi-1"}, 64.0)
    text = publish.caption({**q, "kind": "formats", "series": "formats"})
    assert text.startswith(types.shown(ITEMS[0]["hook"])) and "Comment below" in text and "Answer:" not in text
    assert "NIH 3D" in text and "not medical advice" in text
    assert series.youtube_title(q).endswith("#shorts") and len(series.youtube_title(q)) <= 100


def test_the_timeline_follows_the_narration():
    q = ITEMS[0]
    lines = [(Path("x"), 2.0)] * len(q["script"])
    segs, cues, length = types.plan(q, lines)
    assert [s["kind"] for s in segs[:2]] == ["flash", "intro"] and segs[-1]["kind"] == "grid"
    assert [s["name"] for s in segs if s["kind"] == "type"] == [t["name"] for t in q["types"]]
    assert all(a["end"] == b["start"] for a, b in zip(segs, segs[1:])), "no gaps between shots"
    for c, nxt in zip(cues, cues[1:]):
        assert c["at"] + 2.0 <= nxt["at"], "lines never overlap"
    assert length == segs[-1]["end"] and 30 < length < 90


# Kokoro says these wrong on its own (checked Nov 10, 2026: AV-ulsion, co-MIN-uted, IM-pacted, "wind" as in weather,
# trans-VUSS), so any line using them must give the phonemes.
MISSAID = ("comminuted", "avulsion", "impacted", "transverse", "wind around")


def test_words_kokoro_gets_wrong_carry_their_phonemes():
    for q in ITEMS:
        for line in q["script"]:
            plain = types.MARKUP.sub("", line).lower()
            for word in MISSAID:
                assert word.split()[0] not in plain.split(), f"{word!r} needs [word](phonemes) in: {line}"


def test_markup():
    assert types.shown("Which one have **you** had? [Avulsion](əvˈʌlʃən). *Not* every") == \
        "Which one have you had? Avulsion. Not every"
    assert types.stressed("juː", 2) == "ˈjuːːː" and types.stressed("ˈæŋɡəl") == "ˈæːŋɡəl"
