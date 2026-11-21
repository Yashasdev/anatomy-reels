"""The cinematic videos (anatomy/cinematic.py, banks/cinematic/): every line is voiced once, shots cover the whole
video, labels pin to points the scene reports, captions fit, and the caption works without answer choices."""

import json
import re

import pytest
from PIL import Image, ImageDraw

from anatomy import cinematic, series
from anatomy.types import CAPTION, LABEL, shown

ITEMS = cinematic.items()
PINS = {"brain_scene.py": {"amygdala", "hippocampus", "hypothalamus", "pituitary", "pfc", "stream", "gland", "medulla"},
        "blood_scene.py": {"clump", "sugar", "rh", "hero", "plasma", "antibody"}}


def test_there_are_items():
    assert {q["id"] for q in ITEMS} >= {"dd-brain-anger", "fmt-types-09b"}


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_timeline_covers_every_line_and_frame(q):
    lengths = [1.0 + 0.1 * i for i in range(len(q["beats"]))]
    cues, shots, total = cinematic.timeline(q, lengths)
    assert len(cues) == len(q["beats"])
    assert shots[0]["start"] == 0 and shots[-1]["end"] == total
    assert all(a["end"] == b["start"] for a, b in zip(shots, shots[1:])), "shots are back to back"
    assert sum(sh["frames"] for sh in shots) == int(round(total * cinematic.FPS))
    assert all(line.get("shot") in (None, *q["shots"]) for line in q["beats"])
    assert q["beats"][0].get("shot"), "the first line opens a shot"


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_labels_pin_to_points_the_scene_reports(q):
    for line in q["beats"]:
        if line.get("label"):
            assert line["label"][1] in PINS[q["scene"]], line
            w = ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(line["label"][0], font=LABEL(74))
            assert w < 780, f"label too wide: {line['label'][0]}"


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_caption_phrases_fit_in_two_rows(q):
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    from anatomy.cinematic import chunks, wrap
    for line in q["beats"][:-1]:  # the send line is drawn big on its own
        for c in chunks(shown(line["say"])):
            assert len(wrap(d, c, CAPTION(54), 760)) <= 2, c
        assert " ".join(chunks(shown(line["say"]))) == " ".join(shown(line["say"]).split()), "no words lost"


@pytest.mark.parametrize("q", ITEMS, ids=[q["id"] for q in ITEMS])
def test_send_line_last_and_sources(q):
    assert q["beats"][-1]["say"].startswith("Send this to"), "the video ends on the send line"
    assert q["send"].startswith("Send this to")
    assert q["sources"] and all(s.startswith("https://") for s in q["sources"])
    assert len(q["hashtags"]) <= 5


def test_a_deep_dive_without_choices_gets_a_question_caption():
    q = {**cinematic.info(next(x for x in ITEMS if x["id"] == "dd-brain-anger"), 58.0), "series": "deepdive"}
    text = series.caption(q)
    assert q["question"] in text and "Comment below" in text and "Answer:" not in text
    assert series.FOLLOW["deepdive"] in text
    assert not re.search(r"\[[^\]]+\]\(", text), "no pronunciation marks in captions"
