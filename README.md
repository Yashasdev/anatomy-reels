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
- `scripts/extract_organ.py`: pulls one organ out of the 300 MB Z-Anatomy atlas into a small model file.
- `ATTRIBUTION.md`: model licenses (CC BY-SA) and credits every caption must carry.

Facts must be standard textbook anatomy, checked by a separate blind pass like the other channels. Nothing is
medical advice.
