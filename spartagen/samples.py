"""Turn analysis candidates into a playable Sparta sample bank.

Every sample is cut from the source audio (so its video clip is known) and
processed the way remixers prepare them by hand:

* pitch1..4 — held vowels hard-tuned to D (the key of the classic bases)
* chorus_a/b — the main phrase cut into two parts (Chorus slots 1 and 2), played as is
* chorus_c  — a third word of the voice, played as is (the Epicness's slot 3); chorus_c_a/_b
               its two halves (the DunDunDenDen's 3A and 3B)
* bass       — a held note of its own (another moment than the pitches) played down to D3 like a
               sampler; the bass pitch
* kick       — a thump from the source, pitched down for body, with a pitch
               sweep for punch and the original transient on top
* snare/clap — a noisy "bang" from the source, EQ'd for body + snap
* hat_closed / hat_open — sibilants or cymbal hiss, high-passed; hat2 a second hi-hat
* perc       — one more hit (another bang of the source) for the extra percussion layer
* crash      — a loud noisy stretch with a long reverb tail
* quote1..3  — speech phrases (intro, fills, ending)
* phrase + syl1..N — the main phrase (the Chorus clip) and its syllables (DunDunDenDen chops)
* word_a / word_b  — call & response words for the Madness
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

import numpy as np

from .audio import dsp, fx
from .audio.analysis import Analysis, Candidate, similar_word, split_syllables
from .audio.harmonic import harmonic_filter
from .audio.pitch import midi_to_hz, hz_to_midi, pitch_class, note_name, yin_track
from .audio.psola import TunedSample, tune_to_note, find_marks

#: Main, second, third and fourth pitch — several pitches play the chord lines together.
PITCH_ROLES = ("pitch1", "pitch2", "pitch3", "pitch4")
#: Pitch candidates tried (isolated, tuned, measured) before the auto picks are made.
PITCH_TRIES = 40
#: An auto-picked pitch keeps at least this much of its note inside one camera shot (an 8th at 140 BPM
#: is 0.21 s; a little stretching covers the rest).
AUTO_PITCH_MIN_S = 0.18


@dataclass
class Sample:
    id: str
    role: str                  # pitch | chorus | bass | kick | snare | hat_closed | hat_open | crash | quote | phrase | syllable | word
    label: str
    src_start: float           # source time range (drives the video clip)
    src_end: float
    audio: np.ndarray
    sr: int
    root_midi: float = float("nan")      # note the processed audio sits on
    tuned: Optional[TunedSample] = None  # formant-preserving transposition source
    video_rate: float = 1.0              # source seconds per sample second
    meta: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.audio.shape[0] / self.sr

    @property
    def pitched(self) -> bool:
        return np.isfinite(self.root_midi)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "role": self.role, "label": self.label,
            "src_start": round(self.src_start, 4), "src_end": round(self.src_end, 4),
            "duration": round(self.duration, 4),
            "root_midi": None if not self.pitched else round(float(self.root_midi), 3),
            "root_note": None if not self.pitched else note_name(self.root_midi),
            "video_rate": round(self.video_rate, 4),
            "meta": {k: v for k, v in self.meta.items() if isinstance(v, (int, float, str, bool, type(None)))
                     or isinstance(v, list) and all(isinstance(z, (int, float)) for z in v)},
        }


@dataclass
class SampleConfig:
    key: str = "D"                   # pitch class every pitch sample is tuned to
    pitch_octave: Optional[int] = None  # force D3/D4/D5; None = nearest to the voice
    flatten: float = 1.0             # 1 = dead-straight note, 0 = keep intonation
    bass_octave: int = 3             # bass root = D3 — a pitch you hear above a base's own sub-bass
    max_quotes: int = 3
    clean_pitch: bool = True         # isolate the voice's harmonics before tuning (sources with music under)
    selections: dict = field(default_factory=dict)  # role -> candidate index or {"start":…, "end":…}

    @staticmethod
    def from_dict(d: dict) -> "SampleConfig":
        c = SampleConfig()
        for k, v in (d or {}).items():
            if hasattr(c, k):
                setattr(c, k, v)
        return c


# ── helpers ──────────────────────────────────────────────────────────────────


def _cut(x: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    a = max(0, int(round(start * sr)))
    b = min(x.shape[0], int(round(end * sr)))
    return np.array(x[a:b], dtype=np.float32) if b > a else np.zeros(int(0.05 * sr), dtype=np.float32)


def _trim_silence(x: np.ndarray, sr: int, thresh_db: float = -45.0, pad_ms: float = 4.0) -> tuple[np.ndarray, int]:
    """Trim leading/trailing silence relative to the clip peak; returns (clip, samples cut at start)."""
    if x.size == 0:
        return x, 0
    env = dsp.envelope(x, sr, 1.0, 20.0, mode="peak", block=16)
    pk = float(env.max())
    if pk <= 1e-7:
        return x, 0
    above = np.flatnonzero(env > pk * dsp.db_to_gain(thresh_db))
    if above.size == 0:
        return x, 0
    pad = int(pad_ms * 1e-3 * sr)
    a = max(0, int(above[0]) - pad)
    b = min(x.shape[0], int(above[-1]) + pad)
    return x[a:b], a


def _pick(cands: list[Candidate], sel, avoid: list[tuple[float, float]] = (), min_gap: float = 0.0) -> Optional[Candidate]:
    """Selected candidate: an explicit index, a manual range, or the best one clear of `avoid`."""
    if isinstance(sel, dict) and "start" in sel and "end" in sel:
        kind = cands[0].kind if cands else "manual"
        return Candidate(kind, float(sel["start"]), float(sel["end"]), 1.0, {"manual": True})
    if isinstance(sel, int) and 0 <= sel < len(cands):
        return cands[sel]
    for c in cands:
        if all(c.end + min_gap <= a or c.start >= b + min_gap for a, b in avoid):
            return c
    return cands[0] if cands else None


def _clear_of(c: Candidate, used: list[tuple[float, float]], gap: float) -> bool:
    return all(c.end + gap <= a or c.start >= b + gap for a, b in used)


def trim_to_shot(c: Candidate, cuts: list[float], min_len: float = 0.12, margin: float = 0.04) -> Optional[Candidate]:
    """The longest part of a note between camera cuts.  A pitch's box shows one shot, so a note the
    video cuts away from is shortened with it — audio and picture from the same moment.  ``margin``
    (a frame) keeps clear of the cut.  None when no part is long enough to be a pitch."""
    inside = sorted(t for t in cuts if c.start + margin < t < c.end - margin)
    if not inside:
        return c
    edges = [c.start] + inside + [c.end]
    parts = [(a + (margin if k else 0.0), b - (margin if k < len(inside) else 0.0))
             for k, (a, b) in enumerate(zip(edges[:-1], edges[1:]))]
    a, b = max(parts, key=lambda ab: ab[1] - ab[0])
    if b - a < min_len:
        return None
    return Candidate(c.kind, a, b, c.score, dict(c.info, shot_trimmed=[round(c.start, 4), round(c.end, 4)]))


def _target_midi(f0: float, key_pc: int, octave: Optional[int]) -> int:
    if octave is not None:
        return 12 * (octave + 1) + key_pc
    m = hz_to_midi(f0) if np.isfinite(f0) and f0 > 0 else 62.0
    best = None
    for cand in range(12 * 3 + key_pc, 12 * 7 + key_pc, 12):  # D2..D5 for key D
        if best is None or abs(cand - m) < abs(best - m):
            best = cand
    return best


# ── designers ────────────────────────────────────────────────────────────────


def grow_note(x: np.ndarray, sr: int, c: Candidate, before: float = 0.35, after: float = 0.8,
              max_len: float = 0.9) -> Candidate:
    """The whole held note a pitch candidate sits in.  Candidates come from the full mix, where the
    band hides the voice now and then and cuts a note short; on the isolated voice the note often goes
    on — and a longer note needs less stretching to fill an 8th or a held chord, so it sounds natural."""
    f0 = c.info.get("f0")
    if not f0 or not np.isfinite(f0):
        return c
    a = max(0.0, c.start - before)
    seg = dsp.highpass(_cut(x, sr, a, c.end + after), sr, 60.0, order=2)
    if seg.shape[0] < int(0.1 * sr):
        return c
    iso, _ = harmonic_filter(seg, sr, f0_hint=f0)
    tr = yin_track(iso, sr, fmin=70.0, fmax=1000.0, frame=1024, hop=128, threshold=0.3)
    ok = tr.voiced & np.isfinite(tr.f0)
    if ok.sum() < 4:
        return c
    with np.errstate(invalid="ignore", divide="ignore"):
        cents = np.abs(1200.0 * np.log2(tr.f0 / f0))
    on = ok & (cents < 60.0) & (tr.rms > float(np.max(tr.rms)) * 10 ** (-15.0 / 20.0))
    centre = int(np.argmin(np.abs(tr.times - ((c.start + c.end) / 2 - a))))
    if not on[centre]:
        near = np.flatnonzero(on)
        if near.size == 0:
            return c
        centre = int(near[np.argmin(np.abs(near - centre))])
    i0 = i1 = centre
    while i0 > 0 and (on[i0 - 1] or (i0 > 1 and on[i0 - 2])):        # one-frame dropouts don't end it
        i0 -= 1
    while i1 < on.size - 1 and (on[i1 + 1] or (i1 < on.size - 2 and on[i1 + 2])):
        i1 += 1
    t0 = a + float(tr.times[i0]) - 0.012
    t1 = a + float(tr.times[i1]) + 0.012
    t0, t1 = min(t0, c.start), max(t1, c.end)
    if t1 - t0 > max_len:                                                # the loudest part of a long note
        t1 = t0 + max_len
    if t1 - t0 <= c.duration + 0.02:
        return c
    return Candidate(c.kind, max(0.0, t0), t1, c.score, dict(c.info, grown_from=[round(c.start, 4), round(c.end, 4)]))


def steady_core(seg: np.ndarray, sr: int, min_len: float = 0.1, pad: float = 0.004) -> Optional[tuple[int, int]]:
    """(start, end) samples of the held note inside a cut: the longest run that is voiced, loud and on
    one pitch (within 50 cents).  The consonant before it and the glide or breath after it make a
    pitch sound like a sung word; the core alone sounds like a pitch."""
    tr = yin_track(seg, sr, fmin=70.0, fmax=1000.0, frame=1024, hop=128, threshold=0.25)
    ok = tr.voiced & np.isfinite(tr.f0)
    if ok.sum() < 4:
        return None
    med = float(np.median(tr.f0[ok]))
    with np.errstate(invalid="ignore", divide="ignore"):
        cents = np.abs(1200.0 * np.log2(tr.f0 / med))
    loud = tr.rms > float(np.max(tr.rms)) * 10 ** (-12.0 / 20.0)
    steady = ok & (cents < 50.0) & loud
    best, run_start, best_span = 0, None, None
    for i, v in enumerate(list(steady) + [False]):
        if v and run_start is None:
            run_start = i
        elif not v and run_start is not None:
            if i - run_start > best:
                best, best_span = i - run_start, (run_start, i - 1)
            run_start = None
    if best_span is None:
        return None
    half = 64 / sr                                   # half a hop around the frame centres
    a = max(0, int((tr.times[best_span[0]] - half - pad) * sr))
    b = min(seg.shape[0], int((tr.times[best_span[1]] + half + pad) * sr))
    if (b - a) / sr < min_len:
        return None
    return a, b


def make_pitch(x: np.ndarray, sr: int, cand: Candidate, sid: str, cfg: SampleConfig) -> Sample:
    seg = _cut(x, sr, cand.start, cand.end)
    seg = dsp.highpass(seg, sr, 60.0, order=2)
    cleaned = False
    if cfg.clean_pitch:
        # Keep only the held note's harmonics: the band under a sung note would otherwise be tuned
        # along with it and blur the pitch.
        seg, voiced_share = harmonic_filter(seg, sr, f0_hint=cand.info.get("f0"))
        seg = dsp.apply_fades(seg, sr, 2.0, 6.0)
        cleaned = voiced_share > 0.2
    # A pitch is the held note, not the word: cut to its steady core (the clip with it).
    core = steady_core(seg, sr)
    trimmed_core = None
    if core is not None and (core[0] > 0.012 * sr or seg.shape[0] - core[1] > 0.012 * sr):
        trimmed_core = [round(core[0] / sr, 4), round((seg.shape[0] - core[1]) / sr, 4)]
        seg = dsp.apply_fades(np.array(seg[core[0]:core[1]], dtype=np.float32), sr, 2.0, 6.0)
        cand = Candidate(cand.kind, cand.start + core[0] / sr, cand.start + core[1] / sr, cand.score, cand.info)
    marks = find_marks(seg, sr)
    vper = marks.period[marks.voiced]
    f0 = float(sr / np.median(vper)) if vper.size else float(cand.info.get("f0", float("nan")))
    target = _target_midi(f0, pitch_class(cfg.key), cfg.pitch_octave)
    ts = tune_to_note(seg, sr, midi_to_hz(target), flatten=float(cfg.flatten), marks=marks)
    y = dsp.normalize_rms(ts.audio, -16.0, -1.0)
    scale = (dsp.rms(y) / max(dsp.rms(ts.audio), 1e-9))
    ts = TunedSample(y, sr, ts.f0, ts.marks, ts.source_f0)
    meta = {"source_f0": round(f0, 2) if np.isfinite(f0) else None,
            "source_note": note_name(hz_to_midi(f0)) if np.isfinite(f0) else None,
            "shift_semitones": round(target - hz_to_midi(f0), 2) if np.isfinite(f0) else None,
            "score": round(float(cand.score), 4), "gain": round(float(scale), 4), "isolated": cleaned}
    if cand.info.get("shot_trimmed"):
        meta["shot_trimmed"] = cand.info["shot_trimmed"]      # the note as detected, before the camera cut
    if trimmed_core:
        meta["core_trimmed"] = trimmed_core                     # seconds cut before / after the held note
    return Sample(sid, "pitch", f"{sid} ({note_name(target)})", cand.start, cand.end, y, sr,
                  float(target), ts, 1.0, meta)


def split_point(x: np.ndarray, sr: int, lo: float = 0.35, hi: float = 0.65) -> tuple[int, str]:
    """Where to cut a clip in two: the deepest energy valley between syllables in the middle part,
    else the biggest change of sound there, else the middle — always on a zero crossing."""
    n = x.shape[0]
    hop = max(1, int(0.005 * sr))
    frame = 4 * hop
    if n < 4 * frame:
        cut, how = n // 2, "middle"
    else:
        fr = dsp.block_features(x, frame, hop)
        db = 20.0 * np.log10(np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1)) + 1e-9)
        db = np.convolve(db, np.ones(5) / 5.0, mode="same")
        a, b = int(lo * db.shape[0]), max(int(lo * db.shape[0]) + 1, int(hi * db.shape[0]))
        m = a + int(np.argmin(db[a:b]))
        depth = min(db[:m].max(initial=db[m]), db[m:].max(initial=db[m])) - db[m]
        if depth >= 3.0:
            cut, how = m * hop + frame // 2, "valley"
        else:
            spec = np.abs(np.fft.rfft(fr * np.hanning(frame), axis=1))
            spec /= spec.sum(axis=1, keepdims=True) + 1e-9
            change = np.abs(np.diff(spec, axis=0)).sum(axis=1)
            change = np.convolve(change, np.ones(5) / 5.0, mode="same")
            if change.shape[0] > b and change[a:b].max() > 1.5 * np.median(change):
                cut, how = (a + int(np.argmax(change[a:b]))) * hop + frame, "change"
            else:
                cut, how = n // 2, "middle"
    # Snap to the nearest rising zero crossing within 5 ms.
    w = int(0.005 * sr)
    seg = x[max(1, cut - w):min(n - 1, cut + w)]
    zc = np.flatnonzero((seg[:-1] <= 0) & (seg[1:] > 0))
    if zc.size:
        cut = max(1, cut - w) + int(zc[np.argmin(np.abs(zc - (cut - max(1, cut - w))))]) + 1
    return int(np.clip(cut, 1, n - 1)), how


def make_chorus_pair(x: np.ndarray, sr: int, cand: Candidate, cfg: SampleConfig) -> list[Sample]:
    """The main phrase cut into two parts — the Chorus plays part 1 on "1" and part 2 on "2".

    The Chorus is the main phrase, not a pitch sample: the parts play as they are.  A copy tuned
    to the key note is kept alongside (``tuned``) for remixes that want a pitched chorus."""
    seg = _cut(x, sr, cand.start, cand.end)
    seg = dsp.highpass(seg, sr, 60.0, order=2)
    cut, how = split_point(seg, sr)
    marks = find_marks(seg, sr)
    vper = marks.period[marks.voiced]
    f0 = float(sr / np.median(vper)) if vper.size else float(cand.info.get("f0", float("nan")))
    target = _target_midi(f0, pitch_class(cfg.key), cfg.pitch_octave)
    out = []
    for sid, (a, b), label in (("chorus_a", (0, cut), "chorus part 1"), ("chorus_b", (cut, seg.shape[0]), "chorus part 2")):
        smp = _as_is_part(seg, sr, a, b, cand, target, cfg, sid, f"{label} (main phrase)")
        smp.meta.update({"split": how, "source_f0": round(f0, 2) if np.isfinite(f0) else None})
        out.append(smp)
    return out


def _as_is_part(seg: np.ndarray, sr: int, a: int, b: int, cand: Candidate, target: float, cfg: SampleConfig,
                sid: str, label: str) -> Sample:
    """A chorus sample: the source's own audio (plays as is), plus a copy tuned to ``target``."""
    part = dsp.apply_fades(np.array(seg[a:b], dtype=np.float32), sr, 1.0, 3.0)
    y = dsp.normalize_rms(part, -16.0, -1.0)
    pm = find_marks(part, sr)
    voiced = float(np.mean(pm.voiced)) if pm.voiced.size else 0.0
    ts = None
    root = float("nan")
    if voiced >= 0.3:
        ts = tune_to_note(part, sr, midi_to_hz(target), flatten=float(cfg.flatten), marks=pm)
        ts = TunedSample(dsp.normalize_rms(ts.audio, -16.0, -1.0), sr, ts.f0, ts.marks, ts.source_f0)
        root = float(target)
    return Sample(sid, "chorus", label, cand.start + a / sr, cand.start + b / sr, y, sr, root, ts, 1.0,
                  {"voiced": round(voiced, 3), "score": round(float(cand.score), 4), "plays": "as is"})


def make_third_halves(x: np.ndarray, sr: int, third: Sample, cfg: SampleConfig) -> list[Sample]:
    """The third word cut in two — the DunDunDenDen's "3A" and "3B" (its Original Pattern steps
    through the main phrase: 1___2___3A___3B___)."""
    cand = Candidate("word", third.src_start, third.src_end, float(third.meta.get("score", 1.0)))
    seg = dsp.highpass(_cut(x, sr, cand.start, cand.end), sr, 60.0, order=2)
    cut, how = split_point(seg, sr)
    target = third.root_midi if np.isfinite(third.root_midi) else 62.0
    out = []
    for sid, (a, b), label in (("chorus_c_a", (0, cut), "third word, part A (DunDunDenDen 3A)"),
                               ("chorus_c_b", (cut, seg.shape[0]), "third word, part B (DunDunDenDen 3B)")):
        smp = _as_is_part(seg, sr, a, b, cand, target, cfg, sid, label)
        smp.meta["split"] = how
        out.append(smp)
    return out


def make_chorus_third(x: np.ndarray, sr: int, cand: Candidate, cfg: SampleConfig) -> Sample:
    """The Epicness's third sample ("3"): another word of the voice, whole, played as is.  "For the
    tricky epicness pattern, you will need 3 quote/word samples (the two of them you used is in
    your chorus)" — GageDaRemixer's guide on the Sparta Remix Wiki."""
    seg = dsp.highpass(_cut(x, sr, cand.start, cand.end), sr, 60.0, order=2)
    marks = find_marks(seg, sr)
    vper = marks.period[marks.voiced]
    f0 = float(sr / np.median(vper)) if vper.size else float(cand.info.get("f0", float("nan")))
    target = _target_midi(f0, pitch_class(cfg.key), cfg.pitch_octave)
    smp = _as_is_part(seg, sr, 0, seg.shape[0], cand, target, cfg, "chorus_c", "third word (Epicness 3)")
    smp.meta["source_f0"] = round(f0, 2) if np.isfinite(f0) else None
    return smp


def _steadiness(x: np.ndarray, sr: int, c: Candidate) -> float:
    """1 for a held note, towards 0 for glides (a bowed or slid instrument, a sliding voice)."""
    seg = _cut(x, sr, c.start, c.end)
    tr = yin_track(seg, sr, fmin=70.0, fmax=1000.0, frame=2048, hop=256)
    ok = tr.voiced & np.isfinite(tr.f0)
    f = tr.f0[ok]
    if f.size < 4:
        return 0.2
    cents = 1200.0 * np.log2(f / np.median(f))
    held = float(np.mean(np.abs(cents) < 60.0))          # robust to octave slips in a noisy tail
    return held * float(np.sqrt(ok.mean()))


def _main_candidates(C: dict, x: Optional[np.ndarray] = None, sr: int = 44100, top: int = 10) -> list[Candidate]:
    """Clips that can be the main (Chorus) sample: sung or spoken words with a clear voice on a held
    note — the ones that sound good cut in two and tuned."""
    pool = []
    for c in C.get("word", []) + C.get("pitch", []):
        d = c.duration
        if not 0.18 <= d <= 0.9:
            continue
        voiced = float(c.info.get("voiced", 1.0 if c.kind == "pitch" else 0.0))
        fit = math.exp(-((d - 0.42) / 0.25) ** 2)
        pool.append((c.score * (0.3 + 0.7 * voiced) * (0.4 + 0.6 * fit), c))
    pool.sort(key=lambda z: -z[0])
    if x is not None:
        head = [(sc * (0.25 + 0.75 * _steadiness(x, sr, c)), c) for sc, c in pool[:top]]
        pool = sorted(head, key=lambda z: -z[0]) + pool[top:]
    return [c for _, c in pool]


def sample_timbre(s: Sample) -> np.ndarray:
    """The sound of a sample regardless of its note: mean MFCCs over its loud frames (vowel, voice,
    instrument).  Tuned pitches all sit on D, so this is what tells them apart by ear."""
    from .audio.analysis import compute_features
    y = np.asarray(s.audio, dtype=np.float32)
    f = compute_features(y, s.sr)
    if f.mfcc.shape[0] == 0:
        return np.zeros(13, dtype=np.float32)
    loud = f.rms_db > float(np.max(f.rms_db)) - 20.0
    return f.mfcc[loud].mean(axis=0) if loud.any() else f.mfcc.mean(axis=0)


def timbre_distance(a: np.ndarray, b: np.ndarray, scale: np.ndarray) -> float:
    return float(np.linalg.norm((a - b) / scale))


def _timbre_scale(ts: list[np.ndarray]) -> Optional[tuple[np.ndarray, float]]:
    """(per-coefficient spread, median pairwise distance) over a set of timbres."""
    if len(ts) < 3:
        return None
    m = np.stack(ts)
    scale = m.std(axis=0) + 1e-6
    d = [timbre_distance(m[i], m[j], scale) for i in range(len(ts)) for j in range(i + 1, len(ts))]
    return scale, float(np.median(d)) or 1.0


def pitch_quality(s: Sample, up_drop: Optional[float] = None) -> float:
    """How clearly a tuned sample reads as a note: voiced share × harmonic purity × the share of it
    that sits on the note (a singer bending into the note from a neighbour keeps some of the bend
    through the tuning) × how well it survives an octave up (0..1).  ``up_drop``: a measured
    :func:`octave_up_drop_db`."""
    y = s.audio
    if y.shape[0] < 1024 or not s.pitched:
        return 0.05
    tr = yin_track(y, s.sr, fmin=60.0, fmax=1200.0, frame=2048, hop=256)
    voiced = float(tr.voiced.mean()) if tr.voiced.size else 0.0
    f = float(midi_to_hz(s.root_midi))
    ok = tr.voiced & np.isfinite(tr.f0)
    on_note = 1.0
    if ok.sum() >= 3:
        cents = 1200.0 * np.log2(tr.f0[ok] / f)
        on_note = float(np.mean(np.abs((cents + 600.0) % 1200.0 - 600.0) < 35.0))   # octave slips aside
    S = np.abs(np.fft.rfft(y * np.hanning(y.shape[0]))) ** 2
    fr = np.fft.rfftfreq(y.shape[0], 1.0 / s.sr)
    band = (fr > 80.0) & (fr < 8000.0)
    k = np.round(fr / f)
    harm = (k >= 1) & (np.abs(fr - k * f) < np.maximum(15.0, 0.03 * k * f))
    purity_db = 10.0 * math.log10(float(S[harm & band].sum()) / max(float(S[~harm & band].sum()), 1e-12))
    up = octave_up_factor(s) if up_drop is None else _up_factor(up_drop)
    return (max(0.05, voiced) * float(np.clip((purity_db - 3.0) / 15.0, 0.1, 1.0))
            * float(np.clip((on_note - 0.5) / 0.45, 0.1, 1.0)) * up)


def octave_up_drop_db(s: Sample) -> float:
    """How much quieter the pitch gets an octave up (the Chorus lines reach +12 … +20).  A voice with
    hardly any overtones — a hum, a low breathy note — has nothing left there once its formants are
    kept, and its high notes all but vanish."""
    if s.tuned is None or s.tuned.audio.shape[0] < 1024:
        return 0.0
    from .audio.psola import shift
    y = shift(s.tuned, 12.0, out_len=int(0.22 * s.sr))
    return float(20.0 * np.log10(max(dsp.rms(s.tuned.audio), 1e-9) / max(dsp.rms(y), 1e-9)))


def octave_up_factor(s: Sample) -> float:
    return _up_factor(octave_up_drop_db(s))


def _up_factor(drop_db: float) -> float:
    return float(np.clip(1.0 - (drop_db - 6.0) / 10.0, 0.2, 1.0))


def make_bass(p: Sample, cfg: SampleConfig, own: bool = False) -> Sample:
    """The bass pitch: a tuned note played lower the way a sampler does (slower, deeper), in octave 3
    by default — real Sparta basslines sit there (root and octave bounces around D3), where the voice
    still reads as a pitch instead of a rumble under the base's own bass.  ``own``: the note is the
    bass's own cut, not one of the pitches (its clip is then the bass's alone)."""
    sr = p.sr
    target = 12 * (cfg.bass_octave + 1) + pitch_class(cfg.key)
    shift = target - p.root_midi
    y = dsp.varispeed(p.audio, shift)
    low = cfg.bass_octave <= 2
    y = dsp.lowpass(y, sr, 700.0 if low else 3500.0, order=4)
    y = dsp.highpass(y, sr, 28.0 if low else 70.0, order=2)
    y = fx.saturate(y, 6.0 if low else 3.0, "tanh")
    y = dsp.lowpass(y, sr, 1800.0 if low else 5000.0, order=2)
    y = dsp.declick(dsp.normalize_rms(y, -15.0, -1.0), sr, 2.0)
    if own:
        f0 = p.meta.get("source_f0")
        meta = {k: p.meta[k] for k in ("source_note", "score", "isolated", "shot_trimmed", "core_trimmed")
                if p.meta.get(k) is not None}
        meta["shift_semitones"] = round(target - hz_to_midi(f0), 2) if f0 else None
    else:
        meta = {"from": p.id}
    return Sample("bass", "bass", f"bass ({note_name(target)})", p.src_start, p.src_end, y, sr,
                  float(target), None, 2.0 ** (shift / 12.0), meta)


def make_kick(x: np.ndarray, sr: int, cand: Candidate) -> Sample:
    seg = _cut(x, sr, cand.start, cand.start + 0.45)
    cen = float(cand.info.get("centroid", 300.0))
    low = float(cand.info.get("low", 0.0))
    # A thump from the source, "then EQ it" (wiki): at most an octave down, so it keeps its own knock
    # and its body sits where a kick is heard (~90-150 Hz), not a sub-bass blip under the base.
    shift = 0.0 if (low > 0.6 and cen < 200) else float(np.clip(-12.0 * math.log2(max(cen, 60.0) / 150.0), -12.0, 0.0))
    body = dsp.varispeed(seg, shift) if shift < -0.5 else seg.copy()
    body = body[: int(0.32 * sr)]
    body = fx.pitch_sweep(body, sr, 7.0, 0.0, 45.0)          # punch: glide down onto the body
    knock = dsp.highpass(dsp.lowpass(body, sr, 2500.0, order=2), sr, 200.0, order=2)
    body = dsp.highpass(dsp.lowpass(body, sr, 200.0, order=4), sr, 40.0, order=2) + 0.5 * knock
    click = dsp.highpass(seg[: int(0.015 * sr)], sr, 1500.0, order=2)
    n = body.shape[0]
    y = body * dsp.exp_decay_env(n, sr, 300.0)
    y = dsp.normalize_peak(y, -1.0)
    ck = dsp.normalize_peak(click, -10.0) * dsp.exp_decay_env(click.shape[0], sr, 12.0)
    y[: ck.shape[0]] += ck
    y = fx.saturate(y, 5.0, "tanh")
    y = dsp.apply_fades(y, sr, 0.3, 8.0)
    y = dsp.normalize_peak(y, -1.0)
    # Its clip runs as slow as its body does (a kick pitched down an octave: the clip at half speed).
    return Sample("kick", "kick", "kick", cand.start, cand.start + 0.3, y, sr,
                  video_rate=2.0 ** (shift / 12.0) if shift < -0.5 else 1.0,
                  meta={"shift_semitones": round(shift, 2), "score": round(float(cand.score), 4)})


def make_snare(x: np.ndarray, sr: int, cand: Candidate, clap: bool = False) -> Sample:
    seg = _cut(x, sr, cand.start, cand.start + 0.3)
    y = dsp.highpass(seg, sr, 160.0, order=2)
    y = fx.eq(y, sr, [{"type": "peak", "freq": 220.0, "q": 1.0, "gain": 3.0},
                      {"type": "highshelf", "freq": 5000.0, "q": 0.7, "gain": 4.0}])
    y = fx.transient(y, sr, 6.0, -2.0)
    y = y[: int(0.24 * sr)] * dsp.exp_decay_env(min(y.shape[0], int(0.24 * sr)), sr, 220.0)
    if clap:  # the classic clap trick: a few retriggers of the same burst
        n = y.shape[0] + int(0.03 * sr)
        c = np.zeros(n, dtype=np.float32)
        for k, (d, g) in enumerate(((0.0, 0.7), (0.011, 0.8), (0.023, 1.0))):
            dsp.mix_into(c, y, int(d * sr), g)
        y = c
    y = fx.saturate(y, 3.0, "soft")
    y = dsp.apply_fades(y, sr, 0.3, 10.0)
    y = dsp.normalize_peak(y, -1.0)
    sid = "clap" if clap else "snare"
    return Sample(sid, "snare", sid, cand.start, cand.start + 0.25, y, sr, meta={"score": round(float(cand.score), 4)})


def make_hat(x: np.ndarray, sr: int, cand: Candidate, open_hat: bool) -> Sample:
    length = 0.22 if open_hat else 0.05
    seg = _cut(x, sr, cand.start, max(cand.end, cand.start + length + 0.02))
    if not open_hat and seg.shape[0] > int(0.06 * sr):
        # Start the closed hat at the loudest part of the hiss.
        env = dsp.envelope(seg, sr, 1.0, 10.0, mode="peak", block=16)
        a = max(0, int(np.argmax(env)) - int(0.003 * sr))
        seg = seg[a:]
    cen = float(cand.info.get("centroid", 5000.0))
    hp = float(np.clip(0.6 * cen, 2500.0, 7000.0))
    y = dsp.highpass(seg, sr, hp, order=4)
    y = fx.eq(y, sr, [{"type": "highshelf", "freq": 8000.0, "q": 0.7, "gain": 3.0}])
    n = min(y.shape[0], int((length + 0.02) * sr))
    y = y[:n] * dsp.exp_decay_env(n, sr, length * 1000.0)
    y = dsp.apply_fades(y, sr, 0.2, 5.0)
    y = dsp.normalize_peak(y, -1.0)
    sid = "hat_open" if open_hat else "hat_closed"
    return Sample(sid, sid, "open hat" if open_hat else "closed hat", cand.start, cand.start + length, y, sr,
                  meta={"highpass": round(hp), "score": round(float(cand.score), 4)})


def make_crash(x: np.ndarray, sr: int, cand: Candidate) -> Sample:
    seg = _cut(x, sr, cand.start, cand.start + max(0.25, min(cand.duration, 0.9)))
    y = dsp.highpass(seg, sr, 1500.0, order=2)
    y = y * dsp.exp_decay_env(y.shape[0], sr, 900.0)
    wet = fx.reverb(y, sr, mix_amount=0.8, decay_s=1.8, predelay_ms=5.0, damping=0.3, lowcut=1500.0)
    y = dsp.to_mono(wet)
    y = y * dsp.exp_decay_env(y.shape[0], sr, 1900.0)
    y = dsp.apply_fades(y, sr, 0.5, 30.0)
    y = dsp.normalize_peak(y, -1.0)
    return Sample("crash", "crash", "crash", cand.start, cand.end, y, sr, meta={"score": round(float(cand.score), 4)})


def make_speech(x: np.ndarray, sr: int, cand: Candidate, sid: str, role: str, label: str,
                fade_ms: float = 5.0) -> Sample:
    seg = _cut(x, sr, cand.start, cand.end)
    seg = dsp.highpass(seg, sr, 70.0, order=2)
    seg, cut = _trim_silence(seg, sr, -42.0, 6.0)
    y = dsp.apply_fades(seg, sr, fade_ms, fade_ms * 2)
    y = dsp.normalize_rms(y, -17.0, -1.0)
    start = cand.start + cut / sr
    return Sample(sid, role, label, start, start + y.shape[0] / sr, y, sr, meta={"score": round(float(cand.score), 4)})


def tune_speech(s: Sample, cfg: SampleConfig) -> Sample:
    """Give a word/syllable a D-tuned version for pitched chops (keeps the raw one too)."""
    marks = find_marks(s.audio, s.sr)
    vper = marks.period[marks.voiced]
    if vper.size < 4:
        return s
    f0 = float(s.sr / np.median(vper))
    target = _target_midi(f0, pitch_class(cfg.key), cfg.pitch_octave)
    ts = tune_to_note(s.audio, s.sr, midi_to_hz(target), flatten=float(cfg.flatten), marks=marks)
    s.tuned = ts
    s.root_midi = float(target)
    s.meta["tuned_to"] = note_name(target)
    return s


# ── bank ─────────────────────────────────────────────────────────────────────


@dataclass
class SampleBank:
    sr: int
    samples: dict[str, Sample] = field(default_factory=dict)

    def get(self, sid: str) -> Optional[Sample]:
        return self.samples.get(sid)

    def first(self, *ids: str) -> Optional[Sample]:
        for i in ids:
            s = self.samples.get(i)
            if s is not None:
                return s
        return None

    def by_role(self, role: str) -> list[Sample]:
        return [s for s in self.samples.values() if s.role == role]

    def syllables(self) -> list[Sample]:
        out = [s for s in self.samples.values() if s.role == "syllable"]
        return sorted(out, key=lambda s: s.src_start)

    def to_dict(self) -> dict:
        return {k: v.to_dict() for k, v in self.samples.items()}

    def export(self, folder: str, source_path: Optional[str] = None, video: bool = True) -> list[str]:
        """Write every sample as WAV (+ its cut video clip) — a ready-to-use sample pack, in the folders
        remixers keep: Chorus, Pitches (tuned, the note in the name), Percussion, Quotes and words."""
        from . import ffmpeg as ff
        os.makedirs(folder, exist_ok=True)
        written = []
        for sid, s in self.samples.items():
            rel = pack_path(s)
            wav = os.path.join(folder, rel + ".wav")
            os.makedirs(os.path.dirname(wav), exist_ok=True)
            dsp.write_wav(wav, s.audio, s.sr)
            written.append(wav)
            if video and source_path:
                clip = os.path.join(folder, rel + ".mp4")
                dur = max(0.05, (s.src_end - s.src_start))
                try:
                    ff.cut_clip(source_path, s.src_start, dur, clip, audio_wav=wav)
                    written.append(clip)
                except ff.FFmpegError:
                    pass
        return written


#: Sample pack folders and file names.
PACK_FOLDERS = {"chorus": "1 Chorus", "phrase": "1 Chorus", "syllable": "1 Chorus/Syllables (chops)",
                "pitch": "2 Pitches", "bass": "2 Pitches", "kick": "3 Percussion", "snare": "3 Percussion",
                "hat_closed": "3 Percussion", "hat_open": "3 Percussion", "crash": "3 Percussion",
                "quote": "4 Quotes and words", "word": "4 Quotes and words"}
PACK_NAMES = {"chorus_a": "Chorus 1 (first part)", "chorus_b": "Chorus 2 (second part)",
              "chorus_c": "Epicness 3 (third word)", "chorus_c_a": "DunDunDenDen 3A", "chorus_c_b": "DunDunDenDen 3B",
              "phrase": "Main phrase", "pitch1": "Pitch 1 (main)", "pitch2": "Pitch 2", "pitch3": "Pitch 3",
              "pitch4": "Pitch 4", "bass": "Bass pitch", "kick": "Kick", "snare": "Snare", "clap": "Clap",
              "hat_closed": "Hi-hat closed", "hat_open": "Hi-hat open", "hat2": "Hi-hat 2", "perc": "Extra hit",
              "crash": "Crash", "word_a": "Madness word 1", "word_b": "Madness word 2"}


def pack_path(s: Sample) -> str:
    """Where a sample goes in the sample pack (no extension), e.g. ``2 Pitches/Pitch 1 (main) - D4``."""
    folder = PACK_FOLDERS.get(s.role, "5 Other")
    if s.id.startswith("quote"):
        name = "Quote " + s.id[5:]
    elif s.id.startswith("syl"):
        name = "Syllable " + s.id[3:]
    else:
        name = PACK_NAMES.get(s.id, s.id)
    if s.role in ("pitch", "bass") and s.pitched:
        name += " - " + note_name(s.root_midi)
    return f"{folder}/{name}"


def _cached(cache: Optional[dict], key: tuple, make: Callable):
    """``make()``, remembered in ``cache`` (a dict the caller keeps per source) under ``key``."""
    if cache is None:
        return make()
    if key not in cache:
        cache[key] = make()
    return cache[key]


#: The bass is picked from this many of the best notes left: the lowest-sitting of them.
BASS_TRIES = 12


def _bass_note(x: np.ndarray, sr: int, cfg: SampleConfig, bsel, pitches: list[Candidate], ranked: list[Candidate],
               made: dict, worth: dict, taken: list[tuple[float, float]], cut_away: set,
               shot_cuts: Optional[Callable[[float, float], list[float]]], cache: Optional[dict]) -> Optional[Sample]:
    """The bass's own held note, tuned (the bass is played down from it): the user's pick — an index in the
    pitch candidates or a range they cut — or, of the good notes clear of the pitches' and the Chorus's
    moments, the lowest-sitting one (the least way down to the bass octave keeps the most body).  Another
    moment of the video than the pitches: the bass's box shows the clip it plays, not the main pitch's
    again.  None when no note is left."""
    explicit = isinstance(bsel, dict) or (isinstance(bsel, int) and not isinstance(bsel, bool))
    if explicit:
        c = _pick(pitches, bsel)
        pool = [c] if c is not None else []
    else:
        def low_first(c: Candidate) -> float:
            smp = made.get(id(c))
            root = float(smp.root_midi) if smp is not None and smp.pitched else 62.0
            return worth.get(id(c), c.score) * float(np.clip(1.0 + (62.0 - root) / 48.0, 0.75, 1.25))
        # Far from the pitches first (likely another shot), then nearer, then only not the same moment.
        left = [c for c in ranked if id(c) not in cut_away]
        pool = []
        for gap in (2.0, 0.3, 0.05):
            tier = [c for c in left if _clear_of(c, taken, gap) and all(c is not p for p in pool)]
            pool += sorted(tier[:BASS_TRIES], key=low_first, reverse=True) + tier[BASS_TRIES:]
    for c in pool:
        cand = c
        if shot_cuts is not None:
            trimmed = trim_to_shot(c, shot_cuts(c.start, c.end))
            if not explicit and (trimmed is None or trimmed.duration < AUTO_PITCH_MIN_S):
                continue
            cand = trimmed or c
        pre = made.get(id(cand)) if cfg.pitch_octave is None else None
        if pre is not None:
            return replace(pre, meta=dict(pre.meta))
        key = ("bass", round(cand.start, 4), round(cand.end, 4), cfg.key, float(cfg.flatten), bool(cfg.clean_pitch))
        return _cached(cache, key, lambda: make_pitch(x, sr, cand, "bass", replace(cfg, pitch_octave=None)))
    return None


def _assign_voice_roles(bank: SampleBank, roles: list[str]) -> None:
    """Deal the auto-picked second to fourth pitches out by how they take being shifted up.  The
    Chorus's chord lines lift the second pitch to +16 and the third to +19 semitones, while the fourth
    doubles the root an octave down: the one that loses least an octave up plays the highest line, the
    one that loses most the low root."""
    if len(roles) < 2:
        return
    smps = [bank.samples[r] for r in roles]
    drops = [float(s.meta["_up_drop"]) if s.meta.get("_up_drop") is not None else octave_up_drop_db(s)
             for s in smps]
    order = sorted(range(len(smps)), key=lambda k: drops[k])
    for role, k in zip([r for r in ("pitch3", "pitch2", "pitch4") if r in roles], order):
        smp = smps[k]
        smp.label = smp.label.replace(smp.id, role)
        smp.id = role
        bank.samples[role] = smp


def build_bank(x: np.ndarray, sr: int, an: Analysis, cfg: Optional[SampleConfig] = None,
               progress=None, shot_cuts: Optional[Callable[[float, float], list[float]]] = None,
               cache: Optional[dict] = None) -> SampleBank:
    """``shot_cuts(start, end)`` lists the source video's camera cuts in a range (no video: None).
    ``cache``: a dict kept per source across rebuilds (another pick, key or octave) so the pitch
    candidates are grown, isolated and tuned once."""
    cfg = cfg or SampleConfig()
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    sel = cfg.selections or {}
    bank = SampleBank(sr)
    C = an.candidates

    def step(p: float, msg: str) -> None:
        if progress:
            progress(p, msg)

    # ── the Chorus: the main phrase cut into two parts (first: the pitches then keep off its clips) ──
    mains = _main_candidates(C, x, sr)
    csel = sel.get("chorus")                  # a word candidate index, a {"start", "end"} range, or auto
    words_c = C.get("word", [])
    if isinstance(csel, dict) and "start" in csel and "end" in csel:
        main_c = Candidate("word", float(csel["start"]), float(csel["end"]), 1.0, {"manual": True})
    elif isinstance(csel, int) and 0 <= csel < len(words_c):
        main_c = words_c[csel]
    else:
        main_c = mains[0] if mains else None
    reserved: list[tuple[float, float]] = []      # clips the Chorus plays: no pitch is cut from them too
    if main_c is not None:
        step(0.02, "cutting the main phrase in two")
        for smp in make_chorus_pair(x, sr, main_c, cfg):
            bank.samples[smp.id] = smp
        reserved.append((main_c.start, main_c.end))
        # The Epicness's "3": another word of the same voice, from another moment of the source.
        tsel = sel.get("chorus_c")
        if isinstance(tsel, dict) and "start" in tsel and "end" in tsel:
            third = Candidate("word", float(tsel["start"]), float(tsel["end"]), 1.0, {"manual": True})
        elif isinstance(tsel, int) and 0 <= tsel < len(words_c):
            third = words_c[tsel]
        else:
            around = [(main_c.start, main_c.end)]
            third = next((c for c in mains if _clear_of(c, around, 0.3)), None)
        if third is not None:
            bank.samples["chorus_c"] = make_chorus_third(x, sr, third, cfg)
            for smp in make_third_halves(x, sr, bank.samples["chorus_c"], cfg):
                bank.samples[smp.id] = smp
            reserved.append((third.start, third.end))

    # ── pitches ──
    used: list[tuple[float, float]] = []
    pitches = C.get("pitch", [])
    tried = pitches[:PITCH_TRIES]
    if pitches:
        step(0.04, "finding whole held notes")
        tried = [_cached(cache, ("grow", c.start, c.end), lambda c=c: grow_note(x, sr, c)) for c in tried]
        pitches = tried + list(pitches[PITCH_TRIES:])               # same order and indices
    # Auto picks go by how the note comes out once isolated and tuned: a steady note buried in the
    # band is no pitch at all.  (Explicit picks index the analysis list as shown in the app.)
    made: dict[int, Sample] = {}
    ranked = pitches
    worth: dict[int, float] = {}
    timbres: dict[int, np.ndarray] = {}
    up_drop: dict[int, float] = {}
    if pitches:
        step(0.06, "trying pitch candidates")
        scored = []
        tune_key = (cfg.key, cfg.pitch_octave, float(cfg.flatten), bool(cfg.clean_pitch))
        for k, c in enumerate(tried):
            def attempt(c=c):
                smp = make_pitch(x, sr, c, "try", cfg)
                drop = octave_up_drop_db(smp)
                return smp, sample_timbre(smp), drop, pitch_quality(smp, drop)
            smp, tb, drop, q = _cached(cache, ("try", c.start, c.end) + tune_key, attempt)
            made[id(c)], timbres[id(c)], up_drop[id(c)] = smp, tb, drop
            # Longer held notes make better pitches (they carry 8ths and held notes without looping):
            # the note as it comes out — its steady core — not the clip around it.  And the less a
            # note has to move to reach the key, the more natural it stays.
            held = float(np.clip((smp.duration - 0.08) / 0.17, 0.35, 1.0))
            shift = abs(float(smp.meta.get("shift_semitones") or 0.0))
            natural = float(np.clip(1.0 - 0.04 * max(0.0, shift - 3.0), 0.75, 1.0))
            worth[id(c)] = c.score * q * held * natural
            scored.append((worth[id(c)], c))
            if k % 8 == 7:
                step(0.06 + 0.12 * k / len(tried), "trying pitch candidates")
        scored.sort(key=lambda z: -z[0])
        ranked = [c for _, c in scored] + pitches[PITCH_TRIES:]
    # Several pitches must sound different — another voice, vowel or instrument — not the same note
    # four times: after the main pitch, candidates far in timbre from the ones already chosen win.
    spread = _timbre_scale(list(timbres.values()))
    chosen_timbres: list[np.ndarray] = []

    def by_difference(pool: list[Candidate]) -> list[Candidate]:
        if not chosen_timbres or spread is None:
            return pool
        scale, ref = spread

        def key(c: Candidate) -> float:
            tb = timbres.get(id(c))
            if tb is None:
                return -0.5 * c.score
            d = min(float(np.linalg.norm((tb - o) / scale)) for o in chosen_timbres)
            return worth.get(id(c), c.score) * float(np.clip(d / ref, 0.5, 1.3))
        return sorted(pool, key=key, reverse=True)

    cut_away: set[int] = set()           # auto picks the video cuts away from too soon
    auto_roles: list[str] = []
    for i, sid in enumerate(PITCH_ROLES):
        explicit = sel.get(sid) is not None
        cand = first = short = None
        for _attempt in range(6):
            if explicit:
                pool = pitches
            else:
                left = [c for c in ranked if id(c) not in cut_away]
                pool = by_difference([c for c in left if _clear_of(c, reserved, 0.1)] or left)
            # Second/third pitch: prefer another moment of the source (another word,
            # speaker or note) so the call & response between slots is audible.
            cand = _pick(pool, sel.get(sid), used, 2.0) if i > 0 else None
            if cand is None or (i > 0 and not explicit and not _clear_of(cand, used, 2.0)):
                cand = _pick(pool, sel.get(sid), used, 0.3)
            if cand is None or shot_cuts is None:
                break
            first = first or cand
            # One shot per pitch box: cut the note where the video cuts, or pass on it.  An auto pick
            # has to keep enough of the note to hold an 8th.
            trimmed = trim_to_shot(cand, shot_cuts(cand.start, cand.end))
            if not explicit and (trimmed is None or trimmed.duration < AUTO_PITCH_MIN_S):
                short = short or trimmed
                cut_away.add(id(cand))
                cand = None
                continue
            cand = trimmed or cand
            break
        cand = cand or short or first
        if cand is None:
            # No voiced material at all: fall back to the loudest word/quote so the remix still has a "pitch".
            cand = _pick(C.get("word", []) or C.get("quote", []), None, used)
        if cand is None:
            continue
        if i > 0 and cand in [bank.samples[k].meta.get("_cand") for k in bank.samples]:
            continue
        step(0.2 + 0.03 * i, f"tuning {sid} to {cfg.key}")
        pre = made.get(id(cand))
        cfg_i = cfg
        if i > 0 and cfg.pitch_octave is None and "pitch1" in bank.samples:
            # The pitches play chord lines together: they share the main pitch's octave (a note cut
            # nearer the D above would otherwise sound an octave over the others).
            cfg_i = replace(cfg, pitch_octave=int(round(bank.samples["pitch1"].root_midi)) // 12 - 1)
            if pre is not None and int(round(pre.root_midi)) != int(round(bank.samples["pitch1"].root_midi)):
                pre = None
        s = replace(pre, meta=dict(pre.meta)) if pre is not None else make_pitch(x, sr, cand, sid, cfg_i)
        s.id, s.label = sid, s.label.replace("try", sid)
        s.meta["_cand"] = cand
        if pre is not None:
            s.meta["_up_drop"] = up_drop.get(id(cand))
        bank.samples[sid] = s
        used.append((cand.start, cand.end))
        chosen_timbres.append(timbres[id(cand)] if id(cand) in timbres else sample_timbre(s))
        if i > 0 and not explicit:
            auto_roles.append(sid)
    _assign_voice_roles(bank, auto_roles)
    pitched = [bank.samples[k] for k in PITCH_ROLES if k in bank.samples]
    if pitched:
        step(0.35, "building bass")
        bsel = sel.get("bass")
        src = bank.samples.get(bsel) if isinstance(bsel, str) else None        # "the bass of pitch 2" (older projects)
        own = False
        if src is None or not src.pitched:
            src = _bass_note(x, sr, cfg, bsel, pitches, ranked, made, worth, used + reserved, cut_away, shot_cuts,
                             cache)
            own = src is not None
        if src is None:
            # Nothing else voiced in the video: the lowest tuned pitch, which needs the smallest drop to reach
            # the bass octave (it keeps the most body and the fewest resampling artefacts).
            src = min(pitched, key=lambda smp: (smp.root_midi, smp.id))
        bank.samples["bass"] = make_bass(src, cfg, own=own)

    # ── percussion ──
    step(0.45, "designing percussion")
    kick_c = _pick(C.get("kick", []) or C.get("hit", []), sel.get("kick"))
    snare_c = _pick(C.get("snare", []) or C.get("hit", []), sel.get("snare"),
                    [(kick_c.start, kick_c.end)] if kick_c else [])
    if kick_c:
        bank.samples["kick"] = make_kick(x, sr, kick_c)
    if snare_c:
        bank.samples["snare"] = make_snare(x, sr, snare_c)
        bank.samples["clap"] = make_snare(x, sr, snare_c, clap=True)
    hats = C.get("hat", [])
    hc = _pick(hats, sel.get("hat_closed"))
    if hc is None:
        hc = snare_c
    if hc:
        bank.samples["hat_closed"] = make_hat(x, sr, hc, open_hat=False)
    longest = sorted(hats, key=lambda c: -(c.score * min(c.duration, 0.3)))
    ho = _pick(longest, sel.get("hat_open"), [(hc.start, hc.end)] if hc else []) or hc
    if ho:
        bank.samples["hat_open"] = make_hat(x, sr, ho, open_hat=True)
    cr = _pick(C.get("crash", []), sel.get("crash")) or ho or snare_c
    if cr:
        bank.samples["crash"] = make_crash(x, sr, cr)
    # Layers remixers add over the pattern (Citrus's remix on the extended base): a second hi-hat —
    # another hiss of the source — and one more hit, both from other moments than the kit above.
    taken = [(c.start, c.end) for c in (hc, ho) if c is not None]
    h2 = _pick(hats, sel.get("hat2"), taken, 0.5)
    if h2 is not None and sel.get("hat2") is None and not _clear_of(h2, taken, 0.5):
        h2 = None
    if h2 is not None:
        smp = make_hat(x, sr, h2, open_hat=False)
        smp.id, smp.label = "hat2", "second hi-hat"
        bank.samples["hat2"] = smp
    bangs = sorted(C.get("snare", []) + C.get("hit", []), key=lambda c: -c.score)
    used_bangs = [(c.start, c.end) for c in (kick_c, snare_c, hc, ho, h2) if c is not None]
    pc = _pick(bangs, sel.get("perc"), used_bangs, 0.5)
    if pc is not None and sel.get("perc") is None and not _clear_of(pc, used_bangs, 0.5):
        pc = None
    if pc is not None:
        smp = make_snare(x, sr, pc)
        smp.id, smp.label = "perc", "percussion hit"
        bank.samples["perc"] = smp

    # ── quotes, phrase, syllables, words ──
    step(0.65, "cutting quotes")
    quotes = C.get("quote", [])
    q_used: list[tuple[float, float]] = []
    for i in range(cfg.max_quotes):
        sid = f"quote{i + 1}"
        qc = _pick(quotes, sel.get(sid), q_used, 0.1)
        if qc is None or (i > 0 and (qc.start, qc.end) in q_used):
            break
        bank.samples[sid] = make_speech(x, sr, qc, sid, "quote", f"quote {i + 1}")
        q_used.append((qc.start, qc.end))
    # The main phrase: the Chorus clip (the chorus always holds the main phrase, and the DunDunDenDen
    # usually chops it too — Sparta Remix Wiki), else the best quote.
    if sel.get("phrase") is None and main_c is not None:
        phrase_c = main_c
    else:
        phrase_c = _pick(quotes, sel.get("phrase"))
    if phrase_c is not None:
        ph = make_speech(x, sr, phrase_c, "phrase", "phrase", "main phrase")
        bank.samples["phrase"] = ph
        step(0.75, "chopping syllables")
        for j, (a, b) in enumerate(_syllable_ranges(ph, sr)):
            c = Candidate("syllable", ph.src_start + a, ph.src_start + b, 1.0)
            syl = make_speech(x, sr, c, f"syl{j + 1}", "syllable", f"syllable {j + 1}", fade_ms=3.0)
            bank.samples[syl.id] = tune_speech(syl, cfg)
    words = C.get("word", [])
    voice: list[Candidate] = []
    if sel.get("word_a") is None and mains:
        # The Madness call & response: clear voices (the ranking used for the main clip), not the
        # chorus clip itself.
        voice = [c for c in mains if c.kind == "word" and main_c is not None and
                 (c.end <= main_c.start or c.start >= main_c.end)]
        wa = voice[0] if voice else _pick(words, None)
    else:
        wa = _pick(words, sel.get("word_a"))
    if wa is not None:
        step(0.85, "pairing Madness words")
        wb_sel = sel.get("word_b")
        if wb_sel is not None:
            wb = _pick(words, wb_sel)
        elif len(voice) > 1:
            wb = voice[1]
        else:
            wb = similar_word(words, wa) or _pick(words, None, [(wa.start, wa.end)])
        bank.samples["word_a"] = tune_speech(make_speech(x, sr, wa, "word_a", "word", "word 1 (call)", 3.0), cfg)
        if wb is not None:
            bank.samples["word_b"] = tune_speech(make_speech(x, sr, wb, "word_b", "word", "word 2 (response)", 3.0), cfg)
    for s in bank.samples.values():
        s.meta.pop("_cand", None)
        s.meta.pop("_up_drop", None)
    step(1.0, "sample bank ready")
    return bank


def _syllable_ranges(ph: Sample, sr: int, max_syl: int = 8) -> list[tuple[float, float]]:
    """Syllable boundaries (seconds, relative to the phrase) from energy valleys."""
    y = ph.audio
    hop = 256
    frame = 1024
    if y.shape[0] < frame * 2:
        return [(0.0, y.shape[0] / sr)]
    fr = dsp.block_features(y, frame, hop)
    db = 20 * np.log10(np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5.0, mode="same")
    n = db.shape[0]
    w = max(2, int(0.12 * sr / hop))
    cuts = []
    for m in range(1, n - 1):
        if db[m] <= db[m - 1] and db[m] <= db[m + 1]:
            left = db[max(0, m - w):m].max(initial=db[m])
            right = db[m + 1:m + 1 + w].max(initial=db[m])
            if min(left, right) - db[m] >= 4.0:
                cuts.append(m)
    min_len = int(0.1 * sr / hop)
    bounds = [0]
    for c in cuts:
        if c - bounds[-1] >= min_len:
            bounds.append(c)
    if n - bounds[-1] < min_len and len(bounds) > 1:
        bounds.pop()
    bounds.append(n)
    segs = [((a * hop) / sr, (b * hop + frame) / sr) for a, b in zip(bounds[:-1], bounds[1:])]
    if len(segs) == 1:
        # One long syllable: split into beats of ~0.25 s so the chop still works.
        total = y.shape[0] / sr
        k = int(np.clip(round(total / 0.25), 2, 4))
        segs = [(total * i / k, total * (i + 1) / k) for i in range(k)]
    # Keep the loudest ones if there are too many.
    if len(segs) > max_syl:
        energy = [float(np.mean(db[int(a * sr / hop):max(int(a * sr / hop) + 1, int(b * sr / hop))])) for a, b in segs]
        keep = sorted(np.argsort(energy)[-max_syl:])
        segs = [segs[i] for i in keep]
    return [(a, min(b, y.shape[0] / sr)) for a, b in segs]
