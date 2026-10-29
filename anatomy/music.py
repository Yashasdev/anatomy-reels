"""Original background music, composed and played by this code: nothing is sampled, downloaded or licensed.

Why: a royalty-free library track can still be claimed. Anyone can register a track (even a free or public-domain
one) with YouTube's Content ID or the matching systems on Instagram and TikTok, and the claim lands on every video
that uses it. Music generated here exists nowhere else and is registered with no one, so there is nothing for those
systems to match. Chord progressions, scales and drum patterns are common musical building blocks, not anyone's song.

A track is a style plus a number ("lofi-3"): the same name always plays the same music, so a video re-renders the
same way. `TRACKS` is the library; `pick(seed)` chooses one for a video; `render(name, seconds)` returns stereo audio.
"""

from __future__ import annotations

import zlib

import numpy as np

SR = 44100
STYLES = ("lofi", "house", "ambient", "trap", "pop")
TRACKS = [f"{s}-{i}" for s in STYLES for i in range(1, 6)]  # 25 tracks

# Common progressions as scale degrees (0 = the key's first chord); used by thousands of songs, owned by none.
MINOR_PROGS = [(0, 5, 2, 6), (0, 3, 5, 4), (0, 6, 5, 6), (0, 5, 3, 4), (0, 3, 6, 2)]
MAJOR_PROGS = [(0, 4, 5, 3), (0, 5, 3, 4), (3, 0, 4, 5), (1, 4, 0, 5), (0, 3, 4, 3)]
MINOR, MAJOR = (0, 2, 3, 5, 7, 8, 10), (0, 2, 4, 5, 7, 9, 11)
SETTINGS = {  # tempo range, mode, swing, which parts play
    "lofi": dict(bpm=(72, 86), minor=0.7, swing=0.18, drums="lofi", keys="epiano", lead="epiano", bass="round"),
    "house": dict(bpm=(112, 122), minor=0.6, swing=0.0, drums="four", keys="pad", lead="pluck", bass="offbeat"),
    "ambient": dict(bpm=(64, 76), minor=0.5, swing=0.0, drums=None, keys="pad", lead="bell", bass="sub"),
    "trap": dict(bpm=(136, 148), minor=0.9, swing=0.0, drums="trap", keys="pad", lead="bell", bass="808"),
    "pop": dict(bpm=(96, 108), minor=0.3, swing=0.0, drums="pop", keys="piano", lead="pluck", bass="round"),
}


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def _t(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def _adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    a, d, r = int(a * SR), int(d * SR), int(r * SR)
    env = np.full(n, s, np.float32)
    if a:
        env[:min(a, n)] = np.linspace(0, 1, a)[:n]
    if d and a < n:
        env[a:a + d] = np.linspace(1, s, d)[: max(0, min(d, n - a))]
    if r:
        env[-min(r, n):] *= np.linspace(1, 0, min(r, n))
    return env


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    alpha = 1 - np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    # one-pole filter; written as a cumulative form so it runs at numpy speed
    from itertools import accumulate
    y[:] = np.fromiter(accumulate(x, lambda a, v: a + alpha * (v - a), initial=acc), np.float32, len(x) + 1)[1:]
    return y


# --- instruments -------------------------------------------------------------------------------------------------
def epiano(f: float, dur: float) -> np.ndarray:
    """An electric piano: FM bell attack over a warm sine, slowly fading."""
    t = _t(dur)
    index = 1.8 * np.exp(-t * 6)
    tone = np.sin(2 * np.pi * f * t + index * np.sin(2 * np.pi * f * t)) + 0.25 * np.sin(4 * np.pi * f * t)
    tone *= 1 + 0.004 * np.sin(2 * np.pi * 5 * t)  # a touch of tremolo
    return (tone * np.exp(-t * 1.6) * _adsr(len(t), 0.004, 0, 1, 0.08)).astype(np.float32)


def piano(f: float, dur: float) -> np.ndarray:
    t = _t(dur)
    tone = sum(np.sin(2 * np.pi * f * k * t) * np.exp(-t * (1.5 + k)) / k for k in (1, 2, 3, 4))
    return (tone * _adsr(len(t), 0.003, 0, 1, 0.05)).astype(np.float32)


def pad(f: float, dur: float) -> np.ndarray:
    """Two detuned voices with a few harmonics each, slow in and out."""
    t = _t(dur)
    tone = sum(np.sin(2 * np.pi * f * d * k * t) / k ** 1.4 for d in (0.996, 1.004) for k in (1, 2, 3, 4, 5))
    return (tone * _adsr(len(t), min(0.6, dur / 3), 0, 1, min(0.6, dur / 3)) / 4).astype(np.float32)


def pluck(f: float, dur: float) -> np.ndarray:
    t = _t(dur)
    tone = sum(np.sin(2 * np.pi * f * k * t) * np.exp(-t * (4 + 5 * k)) / k for k in range(1, 7))
    return (tone * _adsr(len(t), 0.002, 0, 1, 0.03)).astype(np.float32)


def bell(f: float, dur: float) -> np.ndarray:
    t = _t(dur)
    tone = np.sin(2 * np.pi * f * t + 2.5 * np.exp(-t * 3) * np.sin(2 * np.pi * f * 3.5 * t))
    return (tone * np.exp(-t * 2.2) * _adsr(len(t), 0.002, 0, 1, 0.05)).astype(np.float32)


def bass(f: float, dur: float, kind: str) -> np.ndarray:
    t = _t(dur)
    if kind == "808":
        glide = f * (1 + 0.6 * np.exp(-t * 30))
        tone = np.tanh(2.2 * np.sin(2 * np.pi * np.cumsum(glide) / SR)) * np.exp(-t * 1.2)
    else:
        tone = np.tanh(1.6 * (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)))
        tone *= np.exp(-t * (0.8 if kind == "sub" else 2.5))
    return (tone * _adsr(len(t), 0.005, 0, 1, 0.04)).astype(np.float32)


def kick(soft: bool) -> np.ndarray:
    t = _t(0.35)
    f = 48 + 110 * np.exp(-t * 32)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * (9 if soft else 7))).astype(np.float32)


def snare(rng, soft: bool) -> np.ndarray:
    t = _t(0.22)
    noise = rng.standard_normal(len(t)) * np.exp(-t * (22 if soft else 16))
    tone = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30)
    return (0.6 * noise + 0.5 * tone).astype(np.float32) * (0.6 if soft else 1)


def clap(rng) -> np.ndarray:
    t = _t(0.2)
    bursts = sum(np.where((t >= o) & (t < o + 0.012), 1.0, 0.0) for o in (0, 0.011, 0.022))
    return (rng.standard_normal(len(t)) * (bursts * 0.7 + np.exp(-t * 18) * 0.5)).astype(np.float32)


def hat(rng, open_: bool = False) -> np.ndarray:
    t = _t(0.25 if open_ else 0.05)
    noise = rng.standard_normal(len(t))
    noise = noise - _lowpass(noise.astype(np.float32), 6000)  # keep the bright part
    return (noise * np.exp(-t * (14 if open_ else 70))).astype(np.float32)


# --- mixing helpers ------------------------------------------------------------------------------------------------
class Mix:
    def __init__(self, seconds: float):
        self.buf = np.zeros((int(seconds * SR) + SR, 2), np.float32)
        self.kicks: list[int] = []

    def add(self, x: np.ndarray, at: float, gain: float = 1.0, pan: float = 0.0) -> None:
        i = int(at * SR)
        if i >= len(self.buf):
            return
        n = min(len(x), len(self.buf) - i)
        self.buf[i:i + n, 0] += x[:n] * gain * (1 - max(0.0, pan))
        self.buf[i:i + n, 1] += x[:n] * gain * (1 + min(0.0, pan))


def reverb(x: np.ndarray, rng, seconds: float = 1.6, wet: float = 0.22) -> np.ndarray:
    """A plain room: convolution with decaying stereo noise (FFT)."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = x.copy()
    for ch in (0, 1):
        ir = rng.standard_normal(n) * np.exp(-t * 4.5)
        ir[: int(0.012 * SR)] = 0  # a short pre-delay
        size = 1 << int(np.ceil(np.log2(len(x) + n)))
        wet_sig = np.fft.irfft(np.fft.rfft(x[:, ch], size) * np.fft.rfft(ir, size), size)[: len(x)]
        out[:, ch] += wet_sig.astype(np.float32) * wet / (np.abs(ir).sum() ** 0.5 * 0.06)
    return out


# --- the composer --------------------------------------------------------------------------------------------------
def render(name: str, seconds: float) -> np.ndarray:
    """`seconds` of track `name` ("lofi-3") as stereo float32, peak 0.9, gently faded at both ends."""
    style, _ = name.split("-")
    cfg = SETTINGS[style]
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    bpm = int(rng.integers(cfg["bpm"][0], cfg["bpm"][1] + 1))
    beat = 60 / bpm
    bar = beat * 4
    minor = rng.random() < cfg["minor"]
    scale = MINOR if minor else MAJOR
    root = int(rng.integers(45, 53))  # A2 .. C#3
    prog = (MINOR_PROGS if minor else MAJOR_PROGS)[int(rng.integers(5))]
    sevenths = style in ("lofi", "ambient")
    mix = Mix(seconds)
    bars = int(np.ceil(seconds / bar)) + 1

    def chord(degree: int, octave: int = 0) -> list[float]:
        notes = [scale[(degree + k) % 7] + 12 * ((degree + k) // 7) for k in ((0, 2, 4, 6) if sevenths else (0, 2, 4))]
        return [midi(root + 12 + 12 * octave + n) for n in notes]

    # a 2-bar melody motif from the pentatonic notes of the key, repeated with a variation (that's what makes it tune-like)
    penta = [scale[i] for i in ((0, 2, 3, 4, 6) if minor else (0, 1, 2, 4, 5))]
    steps = 8
    rhythms = [[0, 2, 3, 5, 6], [0, 1.5, 3, 4, 6], [0, 2, 4, 5, 6.5], [0, 3, 4, 6]]
    rhythm = rhythms[int(rng.integers(len(rhythms)))]
    walk, motif = int(rng.integers(0, 5)), []
    for r in rhythm:
        walk = int(np.clip(walk + int(rng.choice([-2, -1, 1, 1, 2])), 0, 9))
        motif.append((r, penta[walk % 5] + 12 * (walk // 5)))
    variant = [(r, n + (2 if k == len(motif) - 1 else 0)) for k, (r, n) in enumerate(motif)]

    for b in range(bars):
        at = b * bar
        degree = prog[b % 4]
        intro = b < 1  # the first bar: chords only, then everything comes in
        # chords
        if cfg["keys"] == "pad":
            for f in chord(degree):
                mix.add(pad(f, bar + 0.4), at, 0.10)
        elif cfg["keys"] == "piano":
            for hit in (0, 1.5, 2.5) if style == "pop" else (0,):
                for f in chord(degree):
                    mix.add(piano(f, beat * 1.4), at + hit * beat, 0.11, pan=-0.15)
        else:  # epiano, played a little late and loose (lofi)
            for k, f in enumerate(chord(degree)):
                mix.add(epiano(f, bar), at + 0.012 * k + rng.uniform(0, 0.01), 0.10, pan=-0.2 + 0.13 * k)
        # bass
        bf = midi(root - 12 + scale[degree % 7] + (12 if degree >= 7 else 0))
        if not intro:
            if cfg["bass"] == "offbeat":
                for k in range(4):
                    mix.add(bass(bf, beat * 0.45, "round"), at + (k + 0.5) * beat, 0.22)
            elif cfg["bass"] == "808":
                for hit in (0, 2.5):
                    mix.add(bass(bf, beat * 2.4, "808"), at + hit * beat, 0.30)
            elif cfg["bass"] == "sub":
                mix.add(bass(bf, bar, "sub"), at, 0.20)
            else:
                for hit in (0, 2):
                    mix.add(bass(bf, beat * 1.9, "round"), at + hit * beat, 0.22)
        # melody: the motif on bars 2-3, the variation on bars 4-5, resting every third pair (space for the voice)
        if not intro and (b // 2) % 3 != 2:
            line = motif if (b // 2) % 2 == 0 else variant
            half = b % 2
            for r, n in line:
                if half * 4 <= r < half * 4 + 4:
                    f = midi(root + 24 + n)
                    play = {"epiano": epiano, "pluck": pluck, "bell": bell}[cfg["lead"]]
                    mix.add(play(f, beat * (1.2 if cfg["lead"] != "bell" else 2.0)),
                            at + (r - half * 4) * beat, 0.08 if cfg["lead"] == "bell" else 0.09, pan=0.2)
        # drums
        if intro or not cfg["drums"]:
            continue
        sw = cfg["swing"] * beat
        for k in range(steps):  # eighth notes
            t8 = at + k * beat / 2 + (sw if k % 2 else 0)
            kind = cfg["drums"]
            if kind == "four":
                if k % 2 == 0:
                    mix.add(kick(True), t8, 0.42)
                    mix.kicks.append(int(t8 * SR))
                else:
                    mix.add(hat(rng, open_=k % 4 == 3), t8, 0.05)
                if k in (2, 6):
                    mix.add(clap(rng), t8, 0.12)
            elif kind == "trap":
                if k in (0, 5):
                    mix.add(kick(False), t8, 0.38)
                    mix.kicks.append(int(t8 * SR))
                if k == 4:
                    mix.add(clap(rng), t8, 0.14)
                mix.add(hat(rng), t8, 0.05)
                if k == 7 and b % 2:  # a quick hat roll
                    for r in range(1, 4):
                        mix.add(hat(rng), t8 + r * beat / 8, 0.035)
            else:  # lofi and pop: kick on 1 and the "and" of 3, snare on 2 and 4
                if k in (0, 5) or (kind == "pop" and k == 4 and b % 2):
                    mix.add(kick(kind == "lofi"), t8, 0.38 if kind == "pop" else 0.32)
                    mix.kicks.append(int(t8 * SR))
                if k in (2, 6):
                    mix.add(snare(rng, kind == "lofi") if kind == "lofi" else clap(rng), t8, 0.16)
                mix.add(hat(rng), t8, 0.035 if kind == "lofi" else 0.045)

    out = mix.buf
    # pump: everything but the drums dips a little on each kick (the "breathing" of modern mixes)
    if mix.kicks:
        pump = np.ones(len(out), np.float32)
        dip = 1 - 0.25 * np.exp(-np.arange(int(0.18 * SR)) / SR * 20)
        for i in (k for k in mix.kicks if k < len(pump)):
            n = min(len(dip), len(pump) - i)
            pump[i:i + n] = np.minimum(pump[i:i + n], dip[:n])
        out = out * pump[:, None]
    out = reverb(out, rng, wet=0.30 if style in ("ambient", "lofi") else 0.18)
    if style == "lofi":  # dusty top end and a little vinyl crackle
        for ch in (0, 1):
            out[:, ch] = _lowpass(out[:, ch], 5200)
        crackle = (rng.random(len(out)) > 0.9993) * rng.standard_normal(len(out)) * 0.05
        out += crackle[:, None].astype(np.float32)
    out = np.tanh(out * 1.3) / 1.3  # glue
    out = out[: int(seconds * SR)]
    fade = min(int(0.8 * SR), len(out) // 4)
    out[:fade] *= np.linspace(0, 1, fade)[:, None]
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    peak = np.abs(out).max() or 1.0
    return (out / peak * 0.9).astype(np.float32)


def pick(seed: int, avoid: list[str] | None = None, styles: list[str] | None = None) -> str:
    """A track for a video: chosen by seed, skipping the ones used most recently (`avoid`), from `styles` only
    when given (a brand's "music_styles")."""
    pool = [t for t in TRACKS if not styles or t.split("-")[0] in styles]
    choices = [t for t in pool if t not in (avoid or [])] or pool
    return choices[seed % len(choices)]
