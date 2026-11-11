# Anatomy reels (3D)

Short vertical quiz videos about human anatomy, made from real 3D anatomy models with Blender. A part of an
organ glows; viewers name it; the video explains it. Separate from the act-reels engine on purpose: Blender is a
big, different install, and 3D rendering is slow, so it lives in its own repo.

    python -m anatomy.make heart-01      # renders out/heart-01.mp4 (needs Blender, see requirements.txt)

- `banks/*.json`: the questions (organ model, the part to light up, four choices, the trap, the narration).
- `render/blender_scene.py`: runs inside Blender; renders the organ turning, one part lit, as transparent frames.
- `anatomy/make.py`: the narration (Kokoro), the quiz layout on top, sound, and the final MP4.
- `banks/formats/` and `anatomy/formats.py`: two more formats drawn by the same code, rendered ahead on a Mac
  (`python -m anatomy.formats release DIR`): "Which bone is missing?" (`missing.json`: the region swings with one bone
  hidden, which fades back in glowing at the answer) and "Zoom out: guess the body part" (`zoom.json`: the camera starts
  on an extreme close-up of one part and pulls back; the part lights up at the answer). Rules are in tests/test_formats.py.
- `banks/types/` and `anatomy/types.py` (+ `render/fracture_scene.py`): the "types" format, a sixth rotating format
  copied from a studio-style breakdown reel: one femur on a gray studio sweep breaks 11 ways (booleans in Blender),
  with chips flying, a slow push-in, a typed yellow label pinned to each break, captions read by Kokoro, whip cuts
  between types and a closing chart that is also the cover. Rendered on a Mac (`python -m anatomy.types release DIR`,
  about an hour at full size; `preview ID DIR` makes a quick half-size check), then published with
  `python -m anatomy.series publish formats DIR`. Other topics need no new Blender script: an item with
  `"scene": "parts"` (banks/types/knee.json, joints.json, shoulder.json) is drawn by `render/types_scene.py` from
  Z-Anatomy parts, each type saying which parts show, how they move (joints through their range), tear, stretch
  (drawn straps for tendons the atlas lacks), light up or turn red, and where the label pins. `python -m anatomy.types
  say ID` voices a script and prints what whisper hears, to catch mispronounced words before rendering.
  `scripts/extract_organ.py` has the `knee` and `shoulder` models (bones, cruciates, menisci, rotator cuff, labrum).
- `anatomy/hits.py` and `hits.json`: the daily hit check (after the tracker). An Instagram post 12-72 hours old with 3x
  the median views of the last 30 Instagram posts of its own type (quizzes, deep dives, or that format) and 1,000+, or
  3x their median shares per person reached (and 2+ shares), makes its series hot for 5 days. A type with under 6
  posts of its own gets no verdict yet. Series: a format, or for deep dives `series.json` (id or
  `dd-onetake-*` -> name), else a `"series_name"` in the video's json, else the id family; one-offs are their own id. Hot series post first in their slots (a hot format at most once
  a day); quizzes are reported only. Under 3 left in stock: a "make more" warning and `status.json` `"hot"`.
- `hints.json`: id -> "Hint: ..." posted as the Instagram first comment (config `"first_comment"`, off until approved;
  a video's own `"hint"` works too). Never on Notify-me posts. Each post is read back from Buffer; a dropped comment
  only warns. New hints get a separate check: true, and not giving the answer away.
- `scripts/extract_organ.py`: pulls one organ out of the 300 MB Z-Anatomy atlas into a small model file.
- `ATTRIBUTION.md`: model licenses (CC BY-SA) and credits every caption must carry.

Facts must be standard textbook anatomy, checked by a separate blind pass like the other channels. Nothing is
medical advice.
