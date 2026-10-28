"""Every question must render and read right: real part names, one answer, a trap, lines that fit the screen."""

import json
import re
from pathlib import Path

import pytest
from PIL import ImageDraw, Image

from anatomy.make import SANS, SERIF

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
PARTS = json.loads((ROOT / "assets" / "models" / "parts.json").read_text())
BANKS = {p.stem: json.loads(p.read_text()) for p in sorted((ROOT / "banks").glob("*.json"))}
ITEMS = [(name, q) for name, bank in BANKS.items() for q in bank]
KEYS = {"id", "model", "title", "highlight", "question", "choices", "answer_index", "trap_index",
        "lines", "ask_line", "answer_line"}
d = ImageDraw.Draw(Image.new("RGB", (10, 10)))


def width(text, font):
    return d.textlength(text, font=font)


def test_every_bank_is_in_the_rotation():
    assert set(BANKS) == set(CONFIG["rotation"]), "add new banks to config.json rotation (and remove nothing)"


def test_ids_are_unique_and_numbered():
    ids = [q["id"] for _, q in ITEMS]
    assert len(ids) == len(set(ids))
    for name, bank in BANKS.items():
        for k, q in enumerate(bank, 1):
            assert q["id"] == f"{name}-{k:02d}", f"{q['id']}: ids continue the bank's sequence ({name}-{k:02d})"


@pytest.mark.parametrize("name,q", ITEMS, ids=[q["id"] for _, q in ITEMS])
def test_item(name, q):
    assert KEYS <= set(q), f"missing {KEYS - set(q)}"
    assert q["model"] == name and name in PARTS, "a bank's items use its own model (assets/models/<name>.blend)"
    hl = q["highlight"] if isinstance(q["highlight"], list) else [q["highlight"]]
    assert hl and all(h in PARTS[name] for h in hl), f"highlight must be exact names from parts.json: {hl}"
    c = q["choices"]
    assert len(c) == 4 and len(set(c)) == 4
    assert 0 <= q["answer_index"] < 4 and 0 <= q["trap_index"] < 4 and q["answer_index"] != q["trap_index"]
    # fits on screen: header, question, choice boxes (they shrink to size 36 when long)
    assert width(q["title"], SERIF(42)) < 700
    assert width(q["question"], SERIF(50)) < 1000, "question too long for one line"
    assert width(c[q["answer_index"]], SANS(52)) < 1000
    assert all(width(x, SERIF(36)) < 440 for x in c), "a choice is too long for its box"
    lines = q["lines"]
    assert 5 <= len(lines) <= 9 and all(len(x) <= 75 for x in lines), "5 to 9 narration lines, 75 characters max"
    assert 0 < q["ask_line"] < q["answer_line"] < len(lines)
    letter = "ABCD"[q["answer_index"]]
    assert re.match(rf"It's {letter}\b", lines[q["answer_line"]]), f"the answer line says \"It's {letter}. ...\""
    assert lines[-1].startswith("Why it matters:")
    assert -180 <= q.get("start_degrees", -20) <= 180 and 2.0 <= q.get("distance", 4.2) <= 6.0


def test_answer_letters_vary():
    for name, bank in BANKS.items():
        letters = "".join("ABCD"[q["answer_index"]] for q in bank)
        assert not re.search(r"(.)\1\1", letters), f"{name}: the same answer letter three times in a row ({letters})"
