"""Read a Sparta base: tempo, bar grid, chords and the section map.

A remix made on a base has to land on the base's bars and chords, and each
part of the remix has to play the pattern of the matching base section (the
Chorus pattern over the Main Automation, the Awesomeness melody where the
base plays it, the Madness call & response over the breakdown …).  This
module measures what is needed for that:

* tempo and the first downbeat (the base's own drums on a 16th grid);
* the key root and chord progression, one chord per half bar (classic bases:
  "0 1 -2 1" = D, Eb, C, Eb);
* per-bar loudness and texture, grouped into sections and labelled with the
  classic structure (Sparta Remix Wiki): Intro, Chorus, DunDunDenDen (after
  the first Chorus), Epicness (after the Chorus that follows the DunDunDenDen
  and after the Chorus that follows the Madness), Awesomeness 1 (the last
  pattern before the Madness), Madness (the soft breakdown), Awesomeness 2
  (opening the final Chorus), Ending;
* where the intro hits fall and which note they (and the final hit) sit on.

The labels are a best guess from the signal; ``BaseMap.sections`` can be
edited before the remix is fitted to it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

import numpy as np

from . import dsp

Progress = Optional[Callable[[float, str], None]]

SR = 22050
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


@dataclass
class BaseSection:
    kind: str                  # intro | chorus | dundundenden | awesomeness1 | awesomeness2 | madness | epicness | ending
    start_bar: int             # 0-based bar index
    bars: int
    level_db: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BaseMap:
    duration: float
    bpm: float
    offset: float                               # seconds to the first downbeat (bar 1)
    bars: int
    key_pc: int = 2                             # 2 = D
    progression: str = "0 1 -2 1"
    roots: list = field(default_factory=list)   # per half bar: semitones from the key root (None = unclear)
    bar_db: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    intro_hits: list = field(default_factory=list)   # [(step from bar 1, semitone)]
    ending_root: int = 0
    minor: bool = False                         # the key chord is minor (the pitch chords follow it)
    path: str = ""

    @property
    def key(self) -> str:
        return NOTE_NAMES[self.key_pc % 12]

    @property
    def bar_s(self) -> float:
        return 240.0 / self.bpm

    def bar_time(self, bar: float) -> float:
        return self.offset + bar * self.bar_s

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        d["sections"] = [s.to_dict() if isinstance(s, BaseSection) else s for s in self.sections]
        return d

    @staticmethod
    def from_dict(d: dict) -> "BaseMap":
        m = BaseMap(duration=float(d["duration"]), bpm=float(d["bpm"]), offset=float(d["offset"]),
                    bars=int(d["bars"]))
        for k in ("key_pc", "progression", "roots", "bar_db", "intro_hits", "ending_root", "minor", "path"):
            if k in d:
                setattr(m, k, d[k])
        m.sections = [BaseSection(**{k: v for k, v in s.items() if k in BaseSection.__dataclass_fields__})
                      for s in d.get("sections", [])]
        return m


# ── spectra ──────────────────────────────────────────────────────────────────


class _Spec:
    def __init__(self, x: np.ndarray, sr: int, n: int = 2048, hop: int = 256):
        self.sr, self.n, self.hop = sr, n, hop
        x = np.asarray(x, dtype=np.float32)
        if x.shape[0] < n:
            x = np.pad(x, (0, n - x.shape[0]))
        self.x = x
        frames = dsp.block_features(x, n, hop)
        win = np.hanning(n).astype(np.float32)
        mags = []
        for a in range(0, frames.shape[0], 2048):
            mags.append(np.abs(np.fft.rfft(frames[a:a + 2048] * win, axis=1)).astype(np.float32))
        self.mag = np.concatenate(mags) if mags else np.zeros((0, n // 2 + 1), np.float32)
        self.freqs = np.fft.rfftfreq(n, 1.0 / sr)
        self.times = (np.arange(self.mag.shape[0]) * hop + n / 2) / sr

    def fine(self, t0: float, t1: float, n: int = 8192) -> tuple[np.ndarray, np.ndarray]:
        """Median magnitude spectrum of [t0, t1] with a long window (bass notes need ~3 Hz bins)."""
        a = max(0, int(t0 * self.sr))
        b = min(self.x.shape[0], max(a + n, int(t1 * self.sr)))
        seg = self.x[a:b]
        if seg.shape[0] < n:
            seg = np.pad(seg, (0, n - seg.shape[0]))
        hop = max(1, min(n // 4, (seg.shape[0] - n) // 3 or 1))
        frames = dsp.block_features(seg, n, hop)[:8]
        mag = np.median(np.abs(np.fft.rfft(frames * np.hanning(n).astype(np.float32), axis=1)), axis=0)
        return mag, np.fft.rfftfreq(n, 1.0 / self.sr)

    def band(self, lo: float, hi: float) -> np.ndarray:
        m = (self.freqs >= lo) & (self.freqs < hi)
        return self.mag[:, m]

    def frames_between(self, t0: float, t1: float) -> slice:
        a = int(np.searchsorted(self.times, t0))
        b = int(np.searchsorted(self.times, t1))
        return slice(a, max(a + 1, b))


class Onsets:
    """High-resolution onset strength (short window) with exact frame times."""

    def __init__(self, x: np.ndarray, sr: int, n: int = 512, hop: int = 64):
        x = np.asarray(x, dtype=np.float32)
        if x.shape[0] < n:
            x = np.pad(x, (0, n - x.shape[0]))
        frames = dsp.block_features(x, n, hop)
        win = np.hanning(n).astype(np.float32)
        freqs = np.fft.rfftfreq(n, 1.0 / sr)
        w = np.where(freqs < 200, 2.0, 1.0).astype(np.float32)
        prev = None
        out = np.zeros(frames.shape[0], dtype=np.float32)
        for a in range(0, frames.shape[0], 4096):
            lm = np.log1p(10.0 * np.abs(np.fft.rfft(frames[a:a + 4096] * win, axis=1)))
            first = lm[:1] if prev is None else prev
            d = np.maximum(np.diff(np.concatenate([first, lm]), axis=0), 0.0)
            out[a:a + lm.shape[0]] = (d * w).sum(axis=1)
            prev = lm[-1:]
        trend = np.convolve(out, np.ones(64) / 64.0, mode="same")
        self.strength = np.maximum(out - trend, 0.0).astype(np.float32)
        # The flux of a frame reacts once an attack is well inside the window.
        self.t0 = (0.7 * n) / sr
        self.rate = sr / hop

    def at(self, t: np.ndarray | float, width: float = 0.02) -> np.ndarray:
        """Max strength within ±width of the given time(s)."""
        t = np.atleast_1d(np.asarray(t, dtype=np.float64))
        k = max(1, int(width * self.rate))
        idx = np.round((t - self.t0) * self.rate).astype(int)
        n = self.strength.shape[0]
        offs = np.arange(-k, k + 1)
        j = np.clip(idx[:, None] + offs[None, :], 0, n - 1)
        return self.strength[j].max(axis=1)

    def time(self, i: np.ndarray | int) -> np.ndarray | float:
        return self.t0 + np.asarray(i) / self.rate


# ── tempo & grid ─────────────────────────────────────────────────────────────


def estimate_tempo(on: Onsets, lo: float = 90.0, hi: float = 190.0, prior_bpm: float = 140.0) -> float:
    o = on.strength - on.strength.mean()
    n = o.shape[0]
    size = 1 << int(math.ceil(math.log2(2 * n)))
    f = np.fft.rfft(o, size)
    ac = np.fft.irfft(f * np.conj(f), size)[:n]
    best, best_score = prior_bpm, -np.inf
    for bpm in np.arange(lo, hi, 0.25):
        lag = 60.0 / bpm * on.rate
        score = 0.0
        for mult, w in ((1, 1.0), (2, 0.5), (4, 0.25)):   # beat, half bar, bar
            li = lag * mult
            i = int(li)
            if i + 1 >= n:
                continue
            fr = li - i
            score += w * ((1 - fr) * ac[i] + fr * ac[i + 1])
        score *= math.exp(-0.5 * (math.log2(bpm / prior_bpm) / 0.35) ** 2)
        if score > best_score:
            best, best_score = bpm, score
    return float(best)


def _grid_score(on: Onsets, bpm: float, phases: np.ndarray, duration: float) -> np.ndarray:
    six = 15.0 / bpm
    k = np.arange(max(1, int((duration - phases.max()) / six) - 1))
    wts = np.where(k % 4 == 0, 1.0, 0.35)
    idx = np.round((phases[:, None] + k[None, :] * six - on.t0) * on.rate).astype(int)
    idx = np.clip(idx, 0, on.strength.shape[0] - 1)
    return (on.strength[idx] * wts[None, :]).sum(axis=1)


def refine_grid(on: Onsets, bpm0: float, duration: float, span: float = 0.6) -> tuple[float, float]:
    """(bpm, beat phase in seconds) maximising the onset strength on the 16th grid."""
    phases = np.arange(0.0, 60.0 / (bpm0 - span), 1.0 / on.rate)
    best = (bpm0, 0.0, -np.inf)
    for grid in (np.arange(bpm0 - span, bpm0 + span + 1e-9, 0.02), None):
        if grid is None:
            grid = np.arange(best[0] - 0.03, best[0] + 0.03 + 1e-9, 0.002)
        for bpm in grid:
            s = _grid_score(on, float(bpm), phases[phases < 60.0 / bpm], duration)
            j = int(np.argmax(s))
            if s[j] > best[2]:
                best = (float(bpm), float(phases[j]), float(s[j]))
    return best[0], best[1]


def first_downbeat(on: Onsets, bpm: float, phase: float) -> float:
    """The grid beat closest to the first clear attack of the base."""
    beat = 60.0 / bpm
    thr = 0.25 * float(np.percentile(on.strength, 99.5))
    idx = np.flatnonzero(on.strength > thr)
    first = float(on.time(idx[0])) if idx.size else phase
    k = round((first - phase) / beat)
    return max(0.0, phase + k * beat)


# ── chords ───────────────────────────────────────────────────────────────────


def _chroma(mag: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> np.ndarray:
    m = (freqs >= lo) & (freqs <= hi) & (freqs > 0)
    midi = 69 + 12 * np.log2(freqs[m] / 440.0)
    pcs = np.round(midi).astype(int) % 12
    c = np.zeros(12)
    np.add.at(c, pcs, mag[m])
    return c / (c.sum() + 1e-12)


_TRIADS = []
for _r in range(12):
    for _iv in ((0, 4, 7), (0, 3, 7)):
        v = np.zeros(12)
        for _k, _i in enumerate(_iv):
            v[(_r + _i) % 12] = (1.0, 0.8, 0.9)[_k]
        _TRIADS.append((_r, v / np.linalg.norm(v)))


def half_bar_roots(spec: _Spec, offset: float, bar_s: float, bars: int) -> list[Optional[int]]:
    """Pitch class of the chord root for each half bar (median spectra ignore the kicks)."""
    out: list[Optional[int]] = []
    for h in range(2 * bars):
        t0 = offset + h * bar_s / 2
        sl = spec.frames_between(t0 + 0.03, t0 + bar_s / 2 - 0.03)
        blk = spec.mag[sl]
        if blk.shape[0] < 4 or float(blk.mean()) < 1e-5:
            out.append(None)
            continue
        # Triads above the bass: a base's kick (often tuned) swamps the bass range.
        upper = _chroma(np.median(blk, axis=0), spec.freqs, 180.0, 2000.0)
        score = np.zeros(12)
        for r, tpl in _TRIADS:
            score[r] = max(score[r], float(upper @ tpl))
        out.append(int(np.argmax(score)))
    return out


def key_chord_is_minor(spec: _Spec, offset: float, bar_s: float, roots: list[Optional[int]], key_pc: int,
                       loud: list[bool]) -> bool:
    """Is the key chord minor?  Major and minor third compared over the loud half bars on the key
    root — several pitches play chord lines, and a major third over a minor base clashes."""
    votes = 0.0
    for h, r in enumerate(roots):
        if r != key_pc or not loud[h // 2]:
            continue
        t0 = offset + h * bar_s / 2
        blk = spec.mag[spec.frames_between(t0 + 0.03, t0 + bar_s / 2 - 0.03)]
        if blk.shape[0] < 4:
            continue
        c = _chroma(np.median(blk, axis=0), spec.freqs, 180.0, 2000.0)
        votes += float(c[(key_pc + 3) % 12] - c[(key_pc + 4) % 12])
    return votes > 0.0


def detect_progression(roots: list[Optional[int]], loud: list[bool]) -> tuple[int, list[int]]:
    """(key pitch class, 4 chord roots in semitones from the key) from the two-bar cycle."""
    votes = [np.zeros(12) for _ in range(4)]
    for h, r in enumerate(roots):
        if r is None or not loud[h // 2]:
            continue
        votes[h % 4][r] += 1
    chords = [int(np.argmax(v)) for v in votes]
    key = chords[0]
    rel = [((c - key + 6) % 12) - 6 for c in chords]
    return key, rel


# ── sections ─────────────────────────────────────────────────────────────────


def _bar_features(spec: _Spec, on: Onsets, offset: float, bar_s: float, bars: int):
    edges = np.geomspace(40, spec.sr / 2 * 0.95, 25)
    level, low, shape, rhythm = [], [], [], []
    for b in range(bars):
        t0 = offset + b * bar_s
        sl = spec.frames_between(t0, t0 + bar_s)
        blk = spec.mag[sl]
        p = (blk ** 2).mean(axis=0) + 1e-12
        level.append(10 * math.log10(p.sum()))
        low.append(10 * math.log10(p[spec.freqs < 150].sum() + 1e-12))
        bands = [p[(spec.freqs >= a) & (spec.freqs < z)].sum() for a, z in zip(edges[:-1], edges[1:])]
        shape.append(np.log10(np.asarray(bands) + 1e-12))
        rhythm.append(on.at(t0 + np.arange(16) * bar_s / 16))
    return np.asarray(level), np.asarray(low), np.asarray(shape), np.asarray(rhythm)


def _runs(labels: list) -> list[tuple[object, int, int]]:
    out = []
    a = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[a]:
            out.append((labels[a], a, i))
            a = i
    return out


def _block_split(a: int, z: int, low: np.ndarray, sh: np.ndarray) -> list[tuple[int, int]]:
    """Split bars [a, z) where the texture changes (2-bar steps), keeping parts of 4+ bars."""
    cuts = [a]
    for b in range(a + 2, z - 1, 2):
        l0, l1 = low[max(a, b - 2):b].mean(), low[b:min(z, b + 2)].mean()
        m0, m1 = sh[max(a, b - 2):b].mean(axis=0), sh[b:min(z, b + 2)].mean(axis=0)
        cos = float(m0 @ m1 / (np.linalg.norm(m0) * np.linalg.norm(m1) + 1e-9))
        if abs(l1 - l0) > 6.0 or cos < 0.5:
            cuts.append(b)
    cuts.append(z)
    blocks = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]
    merged: list[list[int]] = []
    for x0, x1 in blocks:
        if merged and (x1 - x0 < 4 or merged[-1][1] - merged[-1][0] < 4):
            merged[-1][1] = x1
        else:
            merged.append([x0, x1])
    return [(x0, x1) for x0, x1 in merged]


def label_sections(level: np.ndarray, shape: np.ndarray, rhythm: np.ndarray,
                   low: Optional[np.ndarray] = None) -> list[BaseSection]:
    bars = level.shape[0]
    if bars < 8:
        return [BaseSection("chorus", 0, bars, float(level.mean()) if bars else 0.0)]
    low = level.copy() if low is None else low
    top = float(np.percentile(level, 90))
    # Texture of each bar: spectral shape + rhythm, compared by cosine.
    sh = shape - shape.mean(axis=0)
    sh /= (np.linalg.norm(sh, axis=1, keepdims=True) + 1e-9)
    rh = rhythm / (np.linalg.norm(rhythm, axis=1, keepdims=True) + 1e-9)
    sim = 0.7 * (sh @ sh.T) + 0.3 * (rh @ rh.T)
    loud = level > top - 6.0
    # The Chorus (Main Automation) is the loud texture that comes back most often, far apart in time.
    rep = np.zeros(bars)
    for i in range(bars):
        far = np.abs(np.arange(bars) - i) >= 6
        rep[i] = float(np.sum((sim[i] > 0.8) & far & loud))
    cand = np.flatnonzero(loud)
    proto = int(cand[np.argmax(rep[cand])]) if cand.size else int(np.argmax(level))
    ref = sim[proto]
    is_chorus = (ref > 0.75) & (level > top - 4.5)
    lab = is_chorus.copy()
    for b in range(0, bars - 1, 2):          # sections move in 2-bar steps
        v = bool(lab[b] or lab[b + 1]) if (ref[b] + ref[b + 1]) / 2 > 0.72 else bool(lab[b] and lab[b + 1])
        lab[b] = lab[b + 1] = v
    secs: list[BaseSection] = []
    for is_c, a, z in _runs([bool(v) for v in lab]):
        if secs and ((not is_c and z - a <= 1 and secs[-1].kind == "chorus") or
                     secs[-1].kind == ("chorus" if is_c else "?")):
            secs[-1].bars += z - a            # 1-bar fills inside a chorus stay chorus
            continue
        secs.append(BaseSection("chorus" if is_c else "?", a, z - a))
    # Ends: the intro before the first chorus, the ending after the last one (or its fade-out).
    if secs[0].kind == "?":
        secs[0].kind = "intro"
    if secs[-1].kind == "?":
        secs[-1].kind = "ending"
    else:
        last = secs[-1]
        tail = 0
        for b in range(last.start_bar + last.bars - 1, last.start_bar, -1):
            if level[b] < top - 9.0:
                tail += 1
            else:
                break
        if tail:
            last.bars -= tail
            secs.append(BaseSection("ending", last.start_bar + last.bars, tail))
    # The Madness is the soft breakdown: the quietest middle part (kept whole).
    middle = [s for s in secs if s.kind == "?"]
    mad = min(middle, key=lambda s: float(level[s.start_bar:s.start_bar + s.bars].mean())) if middle else None
    if mad is not None:
        mad.kind = "madness"
    out: list[BaseSection] = []
    for s in secs:
        if s.kind != "?":
            out.append(s)
            continue
        for x0, x1 in _block_split(s.start_bar, s.start_bar + s.bars, low, sh):
            out.append(BaseSection("?", x0, x1 - x0))
    secs = out
    mad_i = next((i for i, s in enumerate(secs) if s.kind == "madness"), len(secs))
    # Wiki: the DunDunDenDen begins after the first Chorus; the Epicness follows the Chorus after the
    # DunDunDenDen and the Chorus after the Madness; Awesomeness 1 is the last pattern before the Madness.
    before = [i for i, s in enumerate(secs[:mad_i]) if s.kind == "?"]
    if before:
        secs[before[0]].kind = "dundundenden"
        if len(before) > 1:
            secs[before[-1]].kind = "awesomeness1"
    for s in secs:
        if s.kind == "?":
            s.kind = "epicness"
    # Awesomeness 2 opens the final Chorus of the extended bases.
    choruses = [s for s in secs if s.kind == "chorus"]
    if len(choruses) >= 3 and choruses[-1].bars >= 12:
        fc = choruses[-1]
        secs.insert(secs.index(fc), BaseSection("awesomeness2", fc.start_bar, 4))
        fc.start_bar += 4
        fc.bars -= 4
    for s in secs:
        s.level_db = round(float(level[s.start_bar:s.start_bar + s.bars].mean()), 2)
    return secs


def roll_bars(x: np.ndarray, sr: int, offset: float, bar_s: float, bars: int, lo: float = 200.0,
              hi: float = 4000.0) -> set[int]:
    """Bars whose second half is a roll of 16ths — an attack on (nearly) every step.  The Epicness ends
    on one ("…111_1111111111111111"), and a base's own Epicness carries it."""
    n = 256
    k_total = x.shape[0] // n
    if k_total < 8:
        return set()
    fr = np.fft.rfftfreq(n, 1.0 / sr)
    m = (fr >= lo) & (fr < hi)
    frames = x[: k_total * n].reshape(k_total, n) * np.hanning(n)
    env = 10.0 * np.log10((np.abs(np.fft.rfft(frames, axis=1)) ** 2)[:, m].sum(axis=1) + 1e-9)
    step = bar_s / 16
    out = set()
    for b in range(bars):
        hits = 0
        for st in range(8, 16):
            k = int((offset + b * bar_s + st * step) * sr / n)
            if k - 4 < 0 or k + 2 > k_total:
                continue
            if env[k:k + 2].max() - env[k - 4:k - 1].mean() >= 3.0:
                hits += 1
        if hits >= 6:
            out.add(b)
    return out


def epicness_by_roll(secs: list[BaseSection], rolls: set[int]) -> list[BaseSection]:
    """The Epicness ends on its roll.  When the 4 bars after a block labelled Epicness end on a roll and
    that block does not, the Epicness is the rolling block, and the one before it is the second half
    of the Chorus it follows (the extended base: Chorus bars 13-20, Epicness 21-24)."""
    out = list(secs)
    i = 0
    while i < len(out):
        s = out[i]
        if (s.kind == "epicness" and 0 < i < len(out) - 1 and out[i - 1].kind == "chorus"
                and (s.start_bar + s.bars - 1) not in rolls):
            nxt = out[i + 1]
            if nxt.kind in ("awesomeness1", "awesomeness2", "epicness") and nxt.bars == 4 \
                    and (nxt.start_bar + nxt.bars - 1) in rolls:
                out[i - 1].bars += s.bars
                nxt.kind = "epicness"
                del out[i]
                continue
        i += 1
    return out


def intro_hits(spec: _Spec, on: Onsets, offset: float, bar_s: float, intro_bars: int,
               key_pc: int, kick_pc: Optional[int] = None) -> list[tuple[int, int]]:
    """Strong hits in the intro (step from bar 1, semitone from the key)."""
    step_s = bar_s / 16
    n_steps = intro_bars * 16
    vals = on.at(offset + np.arange(n_steps) * step_s)
    if not vals.size or vals.max() <= 0:
        return []
    thr = 0.45 * vals.max()
    hits = []
    for s in range(n_steps):
        if vals[s] >= thr and (not hits or s - hits[-1][0] >= 3):
            t0 = offset + s * step_s
            hits.append((s, _root_at(spec, t0 + 0.02, t0 + 3 * step_s, key_pc, kick_pc)))
    return hits[:6]


def _root_at(spec: _Spec, t0: float, t1: float, key_pc: int, kick_pc: Optional[int] = None) -> int:
    """The bass note of a hit: its lowest strong partial (40–400 Hz), skipping a tuned kick's ring."""
    mag, freqs = spec.fine(t0, t1)
    m = (freqs >= 40.0) & (freqs <= 400.0)
    f, v = freqs[m], mag[m]
    peaks = [i for i in range(1, len(v) - 1) if v[i] > v[i - 1] and v[i] >= v[i + 1]]
    if not peaks:
        return 0
    top = max(float(v[i]) for i in peaks)
    strong = sorted((i for i in peaks if v[i] >= 0.25 * top), key=lambda i: f[i])
    for i in strong:
        pc = int(round(69 + 12 * math.log2(f[i] / 440.0))) % 12
        if kick_pc is not None and pc == kick_pc and f[i] < 70.0 and len(strong) > 1:
            continue
        return ((pc - key_pc + 6) % 12) - 6
    return 0


def kick_pitch_class(spec: _Spec, offset: float, bar_s: float, loud_bars: list[int]) -> Optional[int]:
    """Pitch class a tuned kick rings at: the bass-range note shared by every loud bar."""
    votes = np.zeros(12)
    for b in loud_bars[:: max(1, len(loud_bars) // 24)][:24]:
        med, freqs = spec.fine(offset + b * bar_s, offset + (b + 1) * bar_s)
        c = _chroma(med, freqs, 40.0, 70.0)
        votes[int(np.argmax(c))] += 1
    if votes.sum() < 4 or votes.max() < 0.7 * votes.sum():
        return None
    return int(np.argmax(votes))


def final_root(spec: _Spec, t: float, key_pc: int, kick_pc: Optional[int] = None) -> int:
    return _root_at(spec, t + 0.01, t + 0.3, key_pc, kick_pc)   # the hit itself, not its tail


# ── entry point ──────────────────────────────────────────────────────────────


def analyze_base(x: np.ndarray, sr: int, progress: Progress = None, bpm_hint: Optional[float] = None) -> BaseMap:
    def say(p: float, m: str) -> None:
        if progress:
            progress(p, m)

    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if sr != SR:
        x = dsp.resample_sr(x, sr, SR)
    say(0.05, "reading the base")
    spec = _Spec(x, SR)
    on = Onsets(x, SR)
    duration = x.shape[0] / SR
    say(0.3, "finding the tempo")
    bpm0 = float(bpm_hint) if bpm_hint else estimate_tempo(on)
    bpm, phase = refine_grid(on, bpm0, duration, span=0.6 if not bpm_hint else 0.1)
    if abs(bpm - round(bpm)) <= 0.03:
        bpm = float(round(bpm))
        _, phase = refine_grid(on, bpm, duration, span=0.0)
    offset = first_downbeat(on, bpm, phase)
    bar_s = 240.0 / bpm
    bars = max(1, int(round((duration - offset) / bar_s - 0.25)))
    say(0.5, "reading chords")
    roots = half_bar_roots(spec, offset, bar_s, bars)
    level, low, shape, rhythm = _bar_features(spec, on, offset, bar_s, bars)
    loud = list(level > float(np.percentile(level, 90)) - 8.0)
    # Bar 1 might sit a half bar off the chord cycle: pick the alignment whose chords change on it.
    key_pc, rel = detect_progression(roots, loud)
    minor = key_chord_is_minor(spec, offset, bar_s, roots, key_pc, loud)
    say(0.75, "mapping sections")
    secs = label_sections(level, shape, rhythm, low)
    secs = epicness_by_roll(secs, roll_bars(x, SR, offset, bar_s, bars))
    for sec in secs:
        sec.level_db = round(float(level[sec.start_bar:sec.start_bar + sec.bars].mean()), 2)
    chorus_bars = [b for c in secs if c.kind == "chorus" for b in range(c.start_bar, c.start_bar + c.bars)]
    kick_pc = kick_pitch_class(spec, offset, bar_s, chorus_bars or [b for b in range(bars) if loud[b]])
    intro = next((s for s in secs if s.kind == "intro"), None)
    hits = intro_hits(spec, on, offset, bar_s, intro.bars, key_pc, kick_pc) if intro else []
    ending = next((s for s in secs if s.kind == "ending"), None)
    end_root = final_root(spec, offset + ending.start_bar * bar_s, key_pc, kick_pc) if ending else 0
    rel_roots = [None if r is None else ((r - key_pc + 6) % 12) - 6 for r in roots]
    say(1.0, "base mapped")
    return BaseMap(duration=round(duration, 3), bpm=bpm, offset=round(offset, 4), bars=bars, key_pc=key_pc,
                   progression=" ".join(str(v) for v in rel), roots=rel_roots,
                   bar_db=[round(float(v), 2) for v in level], sections=secs, intro_hits=hits,
                   ending_root=end_root, minor=minor)


def analyze_base_file(path: str, progress: Progress = None, bpm_hint: Optional[float] = None) -> BaseMap:
    from .. import ffmpeg as ff
    x = ff.decode_audio(path, sr=SR, mono=True)
    m = analyze_base(x, SR, progress, bpm_hint)
    m.path = path
    return m


def describe(m: BaseMap) -> str:
    lines = [f"{m.bpm:g} BPM, bar 1 at {m.offset:.3f}s, {m.bars} bars, key {m.key}{' minor' if m.minor else ''}, "
             f"progression {m.progression}"]
    for s in m.sections:
        a, z = s.start_bar + 1, s.start_bar + s.bars
        lines.append(f"  bars {a:3d}-{z:3d}  {s.kind:13s} {s.level_db:6.1f} dB")
    if m.intro_hits:
        lines.append("  intro hits: " + ", ".join(f"step {st} ({r:+d})" for st, r in m.intro_hits))
    lines.append(f"  ending on {m.ending_root:+d}")
    return "\n".join(lines)
