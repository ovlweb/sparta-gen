"""TD-PSOLA pitch manipulation: hard-tune to a note, transpose, sustain.

This is what turns a random vowel from the source into a playable Sparta
"pitch": the sample is re-synthesised with every pitch period at exactly the
target note (Melodyne-style "pitch drift 100%"), keeping formants because the
grains themselves are never resampled.  The synthesis marks of the tuned
sample are kept, so later transpositions reuse perfectly regular marks
instead of re-detecting pitch.

Design follows Xleth's engine/src/dsp/TDPSOLA.cpp (marks every period,
2·T0 Hann grains, overlap-add with weight normalisation) with two changes:
marks snap to waveform peaks of a low-passed copy (steadier on speech than
zero crossings), and overlap normalisation only ever attenuates, so
downward shifts keep the natural gap between glottal pulses instead of
amplifying it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from . import dsp
from .pitch import yin_track, median_filter


@dataclass
class Marks:
    pos: np.ndarray       # float sample positions of pitch marks (ascending)
    period: np.ndarray    # local period at each mark, samples
    voiced: np.ndarray    # bool per mark


@dataclass
class TunedSample:
    """A sample re-synthesised at a constant pitch, with its synthesis marks."""

    audio: np.ndarray
    sr: int
    f0: float             # the note it was tuned to (Hz)
    marks: Marks
    source_f0: float      # median pitch before tuning (Hz)

    @property
    def duration(self) -> float:
        return self.audio.shape[0] / self.sr


def _voicing_per_sample(n: int, times: np.ndarray, f0: np.ndarray, voiced: np.ndarray, sr: int,
                        hop: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-sample period contour and voiced mask from a frame-level track."""
    per = np.full(times.shape[0], np.nan)
    per[voiced] = sr / f0[voiced]
    per = median_filter(per, 5)
    idx = np.arange(n) / sr
    vmask_frames = voiced.astype(float)
    vm = np.interp(idx, times, vmask_frames, left=vmask_frames[0] if len(vmask_frames) else 0,
                   right=vmask_frames[-1] if len(vmask_frames) else 0) > 0.5
    good = np.isfinite(per)
    if good.sum() >= 1:
        pc = np.interp(idx, times[good], per[good])
    else:
        pc = np.full(n, sr / 150.0)
    return pc, vm


def find_marks(x: np.ndarray, sr: int, fmin: float = 60.0, fmax: float = 1100.0,
               uv_hop_ms: float = 5.0) -> Marks:
    """Place analysis pitch marks: one per period in voiced parts, fixed hop elsewhere."""
    x = np.asarray(x, dtype=np.float32)
    n = x.shape[0]
    hop = 128
    tr = yin_track(x, sr, fmin=fmin, fmax=fmax, frame=2048, hop=hop, threshold=0.2, min_rms_db=-55)
    pc, vm = _voicing_per_sample(n, tr.times, tr.f0, tr.voiced, sr, hop)
    med_f0 = tr.median_f0()
    lp_cut = float(np.clip((med_f0 if np.isfinite(med_f0) else 200.0) * 1.8, 150.0, 1400.0))
    lp = dsp.lowpass(x, sr, lp_cut, order=4)

    pos: list[float] = []
    per: list[float] = []
    voi: list[bool] = []
    uv_hop = max(8, int(uv_hop_ms * 1e-3 * sr))

    # Walk contiguous voiced / unvoiced runs.
    edges = np.flatnonzero(np.diff(vm.astype(np.int8))) + 1
    bounds = np.concatenate([[0], edges, [n]])
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b <= a:
            continue
        if vm[a] and (b - a) > 2 * np.median(pc[a:b]):
            seg = lp[a:b]
            anchor = a + int(np.argmax(np.abs(seg)))
            pol = 1.0 if lp[anchor] >= 0 else -1.0
            run_pos = [anchor]
            p = anchor
            while True:  # forward
                T = pc[min(int(p), n - 1)]
                guess = p + T
                lo, hi = int(guess - 0.2 * T), int(guess + 0.2 * T) + 1
                if hi >= b or lo <= p:
                    break
                p = lo + int(np.argmax(pol * lp[lo:hi]))
                run_pos.append(p)
            p = anchor
            back = []
            while True:  # backward
                T = pc[min(int(p), n - 1)]
                guess = p - T
                lo, hi = int(guess - 0.2 * T), int(guess + 0.2 * T) + 1
                if lo < a or hi >= p:
                    break
                p = lo + int(np.argmax(pol * lp[lo:hi]))
                back.append(p)
            run = sorted(back + run_pos)
            for q in run:
                pos.append(float(q))
                per.append(float(pc[q]))
                voi.append(True)
        else:
            for q in range(a + uv_hop // 2, b, uv_hop):
                pos.append(float(q))
                per.append(float(uv_hop))
                voi.append(False)
    if not pos:
        pos, per, voi = [float(n // 2)], [float(uv_hop)], [False]
    order = np.argsort(pos)
    return Marks(np.asarray(pos)[order], np.asarray(per)[order], np.asarray(voi)[order])


def _ola(
    x: np.ndarray,
    marks: Marks,
    out_len: int,
    synth_period: Callable[[float, int], float],
    time_map: Callable[[float], float],
    start: Optional[float] = None,
) -> tuple[np.ndarray, Marks]:
    n = x.shape[0]
    maxT = int(np.max(marks.period)) + 2 if marks.period.size else 256
    out = np.zeros(out_len + 4 * maxT, dtype=np.float64)
    wsum = np.zeros_like(out)
    off = 2 * maxT
    xp = np.pad(x.astype(np.float64), (2 * maxT, 2 * maxT))
    t_out = float(marks.pos[0]) if start is None else float(start)
    t_out = min(t_out, max(0.0, out_len - 1.0))
    s_pos, s_per, s_voi = [], [], []
    mpos = marks.pos
    guard = 0
    while t_out < out_len and guard < 200000:
        guard += 1
        t_in = time_map(t_out)
        k = int(np.searchsorted(mpos, t_in))
        if k >= mpos.shape[0]:
            k = mpos.shape[0] - 1
        elif k > 0 and abs(mpos[k - 1] - t_in) <= abs(mpos[k] - t_in):
            k -= 1
        Ta = float(marks.period[k])
        L = max(2, int(round(Ta)))
        m = int(round(mpos[k]))
        grain = xp[m - L + 2 * maxT: m + L + 2 * maxT]
        if grain.shape[0] != 2 * L:
            grain = np.pad(grain, (0, 2 * L - grain.shape[0]))
        w = np.hanning(2 * L + 1)[:-1] if L > 1 else np.ones(2)
        c = int(round(t_out)) + off
        out[c - L:c + L] += grain * w
        wsum[c - L:c + L] += w
        Ts = synth_period(t_out, k) if marks.voiced[k] else Ta
        s_pos.append(t_out)
        s_per.append(Ts)
        s_voi.append(bool(marks.voiced[k]))
        t_out += max(Ts, 2.0)
    y = out / np.maximum(wsum, 1.0)
    y = y[off:off + out_len]
    return y.astype(np.float32), Marks(np.asarray(s_pos), np.asarray(s_per), np.asarray(s_voi, dtype=bool))


def _identity(t: float) -> float:
    return t


def tune_to_note(x: np.ndarray, sr: int, target_hz: float, flatten: float = 1.0,
                 marks: Optional[Marks] = None) -> TunedSample:
    """Re-synthesise ``x`` so its voiced parts sit on ``target_hz``.

    flatten=1.0 removes all drift/vibrato (a dead-straight note); 0.0 keeps the
    original intonation and only moves its median onto the target.
    """
    x = np.asarray(x, dtype=np.float32)
    if marks is None:
        marks = find_marks(x, sr)
    vper = marks.period[marks.voiced]
    src_f0 = float(sr / np.median(vper)) if vper.size else float("nan")
    if not np.isfinite(src_f0) or x.shape[0] < int(0.05 * sr):
        # Nothing periodic to hold on to: fall back to a plain resample shift.
        ratio = 1.0
        if np.isfinite(src_f0) and src_f0 > 0:
            ratio = target_hz / src_f0
        y = dsp.fit_length(dsp.varispeed(x, 12 * math.log2(ratio)) if ratio != 1.0 else x, x.shape[0])
        T = sr / target_hz
        pos = np.arange(T, y.shape[0], T)
        return TunedSample(y, sr, target_hz, Marks(pos, np.full(pos.shape, T), np.ones(pos.shape, bool)),
                           src_f0 if np.isfinite(src_f0) else target_hz)

    T_target = sr / target_hz
    shift_ratio = target_hz / src_f0

    def synth_period(_t: float, k: int) -> float:
        f_in = sr / marks.period[k]
        f_contour = f_in * shift_ratio
        f_out = (target_hz ** flatten) * (f_contour ** (1.0 - flatten))
        return sr / f_out if flatten < 1.0 else T_target

    y, smarks = _ola(x, marks, x.shape[0], synth_period, _identity)
    y = dsp.declick(y, sr, 1.5)
    return TunedSample(y, sr, target_hz, smarks, src_f0)


def _stretch_map(in_len: int, out_len: int, attack: int, window: Optional[tuple[int, int]] = None,
                 pingpong_over: float = 3.0) -> Callable[[float], float]:
    """Output-time → input-time map that keeps the attack and sustains the body."""
    if out_len <= in_len:
        return _identity
    attack = min(attack, in_len // 3)
    ratio = (out_len - attack) / max(in_len - attack, 1)
    if ratio <= pingpong_over or window is None:
        def lin(t: float) -> float:
            if t <= attack:
                return t
            return attack + (t - attack) / ratio
        return lin
    ws, we = window
    ws = max(ws, attack)
    we = max(we, ws + 2)
    span = we - ws

    def pingpong(t: float) -> float:
        if t <= ws:
            return t
        u = (t - ws) % (2 * span)
        return ws + (u if u < span else 2 * span - u)
    return pingpong


def steady_window(marks: Marks, n: int) -> tuple[int, int]:
    """Longest voiced run of marks — the part worth sustaining."""
    best = (0, n)
    best_len = -1
    i = 0
    v = marks.voiced
    while i < v.shape[0]:
        if v[i]:
            j = i
            while j + 1 < v.shape[0] and v[j + 1]:
                j += 1
            ln = marks.pos[j] - marks.pos[i]
            if ln > best_len:
                best_len = ln
                best = (int(marks.pos[i]), int(marks.pos[j]))
            i = j + 1
        else:
            i += 1
    if best_len <= 0:
        return (n // 4, max(n // 4 + 2, 3 * n // 4))
    # Trim 15 % off both ends of the run: those periods are still settling.
    a, b = best
    trim = int(0.15 * (b - a))
    return a + trim, b - trim


def shift(ts: TunedSample, semitones: float, out_len: Optional[int] = None,
          attack_ms: float = 25.0) -> np.ndarray:
    """Transpose a tuned sample by ``semitones`` (formants kept), optionally to a new length."""
    n = ts.audio.shape[0]
    out_len = n if out_len is None else int(out_len)
    if abs(semitones) < 1e-6 and out_len <= n:
        return ts.audio[:out_len].copy()
    factor = 2.0 ** (semitones / 12.0)
    tmap = _stretch_map(n, out_len, int(attack_ms * 1e-3 * ts.sr), steady_window(ts.marks, n))

    def synth_period(_t: float, k: int) -> float:
        return ts.marks.period[k] / factor

    y, _ = _ola(ts.audio, ts.marks, out_len, synth_period, tmap)
    return dsp.declick(y, ts.sr, 1.5)


def stretch_raw(x: np.ndarray, sr: int, out_len: int, semitones: float = 0.0,
                marks: Optional[Marks] = None) -> np.ndarray:
    """PSOLA time-stretch/shift for material that was not tuned first."""
    x = np.asarray(x, dtype=np.float32)
    if marks is None:
        marks = find_marks(x, sr)
    factor = 2.0 ** (semitones / 12.0)
    tmap = _stretch_map(x.shape[0], out_len, int(0.02 * sr), steady_window(marks, x.shape[0]))
    y, _ = _ola(x, marks, out_len, lambda _t, k: marks.period[k] / factor, tmap)
    return dsp.declick(y, sr, 1.5)
