"""The "types" format (anatomy/types.py, banks/types/): every type is one Blender can draw, lines fit on screen, and
the published fracture video still renders to exactly what it did."""

import hashlib
import json
import re
import sys
from pathlib import Path

import PIL
import pytest
from PIL import Image, ImageDraw

from anatomy import make, publish, series, types

ROOT = Path(__file__).resolve().parent.parent
BUILT = set(re.findall(r'"(\w+)": \w+', re.search(r"BUILDERS = \{(.*?)\}", (ROOT / "render" / "fracture_scene.py")
                                                             .read_text(), re.S).group(1)))
PARTS = json.loads((ROOT / "assets" / "models" / "parts.json").read_text())
ITEMS = types.items()
FRACTURE = next(q for q in ITEMS if q["id"] == "fmt-types-01")
PARTS_ITEMS = [q for q in ITEMS if q.get("scene") == "parts"]
d = ImageDraw.Draw(Image.new("RGB", (10, 10)))


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_item(q):
    names = [t["name"] for t in q["types"]]
    assert len(set(names)) == len(names), "each type once"
    if q.get("scene") != "parts":
        assert set(names) <= BUILT, "a type the fracture script builds"
    assert set(q["flash"]) <= set(names) and 4 <= len(q["flash"]) <= 6
    assert len(names) <= 11, "the closing chart has 11 places (rows of 4, 4 and 3)"
    assert str(len(names)) in q["intro"] and str(len(names)) in q["title"]
    for t in q["types"]:
        assert types.shown(t["lines"][0]).split(".")[0].split(",")[0].upper().startswith(t["label"].split()[0]), \
            "say the name first"
        for label in (t["label"], t.get("label2", "")):  # parts items' labels are placed inside x 120-960 (840 wide)
            assert d.textlength(label, font=types.LABEL(70)) < (480 if q.get("scene") == "parts" else 400)
        if t.get("label2"):  # a pair: its second line names the second term, and starts its moves' "keys2"
            assert types.shown(t["lines"][t.get("switch_line", 1)]).upper().startswith(t["label2"].split()[0])
    for line in q["script"]:
        assert len(types.wrap(d, types.shown(line), types.CAPTION(52), types.CAPTION_W)) <= 3, line
        assert not set("*[]()") & set(types.shown(line)), "markup must be well formed"
    assert len(q["hashtags"]) <= 5 and q["sources"]
    assert q["send"].startswith("Send this to") and types.shown(q["outro"][-1]).startswith("Send this to")
    assert re.fullmatch(r"fmt-types-\d\d", q["id"])
    assert set(q.get("flash_mystery", [])) <= set(q["flash"])
    if "?" in types.shown(q["hook"]) or "guess" in q["hook"].lower():  # a hook that asks never shows the answer
        assert q.get("flash_mystery"), "name the asked-about type in flash_mystery so the montage shows '?'"


def points(show: dict):
    """Every point spec in a show block."""
    for key in ("pin", "focus"):
        if key in show:
            yield show[key]
    for mv in show.get("moves", []):
        yield mv["pivot"]
    for b in show.get("bands", []) + show.get("spans", []):
        yield b["from"]
        yield b["to"]
    for t in show.get("tears", []):
        yield t["at"]


@pytest.mark.parametrize("q", PARTS_ITEMS, ids=[q["id"] for q in PARTS_ITEMS])
def test_parts_items_name_real_parts(q):
    """Every part a show uses is in its model (assets/models/parts.json) or is one of its own straps."""
    for t in q["types"]:
        s = t["show"]
        assert (ROOT / "assets" / "models" / f"{s['model']}.blend").exists()
        parts = set(s.get("parts") or PARTS[s["model"]])
        assert parts <= set(PARTS[s["model"]]), t["name"]
        bands = {b["name"] for b in s.get("bands", [])}
        known = parts | bands
        for key in ("smooth", "lit", "hurt", "ghost"):
            assert set(s.get(key, [])) <= known, (t["name"], key)
        for mv in s.get("moves", []):
            assert set(mv["parts"]) <= parts and all(len(k) in (4, 7) for k in mv["keys"])
            assert [k[0] for k in mv["keys"]] == sorted(k[0] for k in mv["keys"]), "keys in time order"
        for x in s.get("spans", []) + s.get("tears", []):
            assert x["part"] in parts
        for p in points(s):
            if "xyz" in p:
                continue
            assert p.get("part", p.get("fit")) in known and len(p["at"]) == 3 and all(0 <= f <= 1 for f in p["at"])
        assert t.get("sound", "thud") in ("pop", "thud", "snap", "none")
        for j, row in enumerate(t.get("chart") or [t["label"].title()]):  # fits under its picture (3 across)
            assert d.textlength(row, font=types.BOLD(30) if j == 0 else types.CAPTION(23)) < 270, row
    assert q["credit"] == "3D model: Z-Anatomy / BodyParts3D (CC BY-SA 4.0)"


def test_parts_items_use_the_generic_scene_and_the_fracture_keeps_its_own():
    script, spec = types.scene_for(FRACTURE, [], 10, Path("/tmp/x"), 1080, 1920, 32)
    assert script.name == "fracture_scene.py"
    assert spec == {"root": str(ROOT), "out": "/tmp/x", "fps": 30, "width": 1080, "height": 1920, "samples": 32,
                    "frames": 10, "timeline": []}, "exactly the spec the published video was rendered with"
    for q in PARTS_ITEMS:
        script, spec = types.scene_for(q, [], 10, Path("/tmp/x"), 1080, 1920, 32)
        assert script.name == "types_scene.py" and list(spec["shows"]) == [t["name"] for t in q["types"]]


def test_the_fracture_video_is_unchanged():
    """Golden values from before the engine was generalized (Nov 11, 2026): its timeline, its Blender script and
    the 2D layer drawn over it. If one of these changes, the published fracture video would no longer rebuild."""
    lines = [(Path("x"), 1.0 + 0.137 * (i % 7)) for i in range(len(FRACTURE["script"]))]
    segs, cues, length = types.plan(FRACTURE, lines)
    assert hashlib.sha256(json.dumps([segs, cues, length]).encode()).hexdigest() == \
        "2786b1a5732effe0f558ec3ddc3b90423fe5ceb60bb6ff1522d323e0ef7c3954"
    assert hashlib.sha256((ROOT / "render" / "fracture_scene.py").read_bytes()).hexdigest() == \
        "d3dd3dec43a10f80fbeea2dcf1be538029d22c0b3d5fc0a48e760663ce665e9c"
    s = 0.5
    img = types.studio(540, 960, True)
    types.callout(img, (300, 700), "TRANSVERSE", 0.5, 1.0, s)
    types.caption(img, "Transverse. A straight break, right across the bone.", s)
    types.watermark(img, s)
    types.small_label(img, (200, 400), "OBLIQUE", s)
    # The 2D layer is checked where the videos are made: on the Mac. Text pixels differ between FreeType builds (CI's
    # Linux Pillow 13 gave two different hashes on Nov 14, 2026 with the same code), so CI checks everything else.
    if sys.platform == "darwin":
        golden = {"12": "af1cca278d84f6674b2fecd66833ed2e2c0bbfb79c773cff064bf67084d240cb"}
        major = PIL.__version__.split(".")[0]
        assert major in golden, f"no golden 2D layer for Pillow {PIL.__version__}: add one after checking a frame by eye"
        assert hashlib.sha256(img.tobytes()).hexdigest() == golden[major]
    assert hashlib.sha256(types.snap(3).tobytes()).hexdigest() == \
        "04672fe431fa9505760730903b9be5aee3b99fbe7d0953e3de5fe52c37ca7cc0"
    assert hashlib.sha256(types.whoosh().tobytes()).hexdigest() == \
        "d9c47636b31d4bec3344369b77b3d313bf18becb305a0c7f13e4d9e502eec636"


@pytest.mark.parametrize("n", range(1, 10))
def test_the_chart_stays_in_the_phone_safe_area(n):
    for cx, y, w, h in types.cells(n):
        assert make.SAFE_TOP <= y and y + h + 78 <= types.CHART_BOTTOM + 1
        assert types.CHART_BOTTOM + 2 < types.CHART_CAPTION_Y - 62 * 3 / 2, "the closing caption clears the chart"
        assert types.CHART_CAPTION_Y + 62 * 3 / 2 <= make.SAFE_BOTTOM
        lo, hi = cx - w / 2, cx + w / 2
        assert lo >= make.SAFE_LEFT and hi <= 1020
        if y + h + 78 > 1100:
            assert hi <= make.SAFE_RIGHT_LOW, "clear of the like/comment column"


def test_the_caption_has_no_answer_key_and_credits_the_model():
    for q, credit in [(FRACTURE, "NIH 3D")] + [(x, "Z-Anatomy") for x in PARTS_ITEMS]:
        info = types.info({**q, "music": "lofi-1"}, 64.0)
        text = publish.caption({**info, "kind": "formats", "series": "formats"})
        assert text.startswith(types.shown(q["hook"])) and "Comment below" in text and "Answer:" not in text
        assert credit in text and "not medical advice" in text and "Send this to" in text
        assert series.youtube_title(info).endswith("#shorts") and len(series.youtube_title(info)) <= 100


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_the_timeline_follows_the_narration(q):
    lines = [(Path("x"), 2.0)] * len(q["script"])
    segs, cues, length = types.plan(q, lines)
    assert [s["kind"] for s in segs[:2]] == ["flash", "intro"] and segs[-1]["kind"] == "grid"
    assert [s["name"] for s in segs if s["kind"] == "type"] == [t["name"] for t in q["types"]]
    assert all(a["end"] == b["start"] for a, b in zip(segs, segs[1:])), "no gaps between shots"
    for c, nxt in zip(cues, cues[1:]):
        assert c["at"] + 2.0 <= nxt["at"], "lines never overlap"
    assert length == segs[-1]["end"] and 30 < length < 90


# Kokoro says these wrong on its own (checked Nov 10-11, 2026: AV-ulsion, co-MIN-uted, IM-pacted, "wind" as in weather,
# trans-VUSS, MEN-iscus, PAY-tellar, dislo-CAY-ted, "tear" as in crying), so any line using them must give the phonemes.
MISSAID = ("comminuted", "avulsion", "impacted", "transverse", "wind around", "meniscus", "patellar", "dislocated")


def test_words_kokoro_gets_wrong_carry_their_phonemes():
    for q in ITEMS:
        for line in q["script"]:
            plain = types.MARKUP.sub("", line).lower()
            for word in MISSAID:
                assert word.split()[0] not in re.findall(r"[a-z']+", plain), f"{word!r} needs [word](phonemes) in: {line}"
            # Kokoro reads "tear(s)" as crying almost everywhere (Nov 11: "ACL tear", "stretches or tears",
            # "on top tears"), so every one carries its phonemes: [tear](tˈɛɹ), [tears](tˈɛɹz)
            assert not re.search(r"\btears?\b", plain), f"say 'tear' (a rip) with phonemes: {line}"


def test_markup():
    assert types.shown("Which one have *you* had? [Avulsion](əvˈʌlʃən). Not every") == \
        "Which one have you had? Avulsion. Not every"
    assert types.stressed("juː") == "ˈjuː" and types.stressed("ˌæŋɡəl") == "ˈæŋɡəl"
    assert "ː" * 2 not in "".join(FRACTURE["script"]), "never stretch vowels: it sounds wrong"


@pytest.mark.parametrize("label", ["TOE", "SCAPHOID", "FOREARM (KIDS)", "NIGHTSTICK"])
def test_new_labels_stay_clear_of_tall_phone_crops(label):
    """Tall phones crop about 100 px off each side, so the new items' names stay within LABEL_X wherever they go."""
    import numpy as np
    w = d.textlength(label, font=types.LABEL(74))
    for seed in range(6):
        cover = np.random.default_rng(seed).random((240, 135)).astype(np.float32)
        for pin in [(40, 600), (540, 900), (1040, 400)]:
            (ex, ey), side = types.place_label(cover, pin, w, 1.0)
            t0, t1 = (ex + 6, ex + 6 + w) if side > 0 else (ex - 6 - w, ex - 6)
            assert types.LABEL_X[0] <= t0 and t1 <= types.LABEL_X[1]
