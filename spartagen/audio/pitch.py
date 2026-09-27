"""Fundamental-frequency tracking (YIN) and note math.

The tracker follows de Cheveigné & Kawahara (2002) steps 1-5, the same
formulation Xleth's loop optimizer uses (tools/loop_optimizer/pitch.py), but
vectorised over whole blocks of frames so a ten-minute source analyses in a
few seconds with plain numpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .dsp import block_features

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_ALIASES = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}


def hz_to_midi(f: float | np.ndarray) -> float | np.ndarray:
    return 69.0 + 12.0 * np.log2(np.asarray(f, dtype=np.float64) / 440.0) if isinstance(f, np.ndarray) \
        else 69.0 + 12.0 * math.log2(max(f, 1e-9) / 440.0)


def midi_to_hz(m: float | np.ndarray) -> float | np.ndarray:
    return 440.0 * np.power(2.0, (np.asarray(m, dtype=np.float64) - 69.0) / 12.0) if isinstance(m, np.ndarray) \
        else 440.0 * 2.0 ** ((m - 69.0) / 12.0)


def note_name(midi: float) -> str:
    m = int(round(midi))
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def pitch_class(name: str) -> int:
    """'D' -> 2, 'Eb' -> 3, 'F#' -> 6."""
    n = name.strip().upper().replace("♯", "#").replace("♭", "B")
    n = FLAT_ALIASES.get(n, n)
    if n not in NOTE_NAMES:
        raise ValueError(f"unknown note name {name!r}")
    return NOTE_NAMES.index(n)


def nearest_note_of_class(f0: float, pc: int, lo_midi: int = 38, hi_midi: int = 74) -> int:
    """MIDI number of pitch class ``pc`` closest (in log distance) to f0, clamped."""
    m = hz_to_midi(f0)
    best = None
    for cand in range(lo_midi, hi_midi + 1):
        if cand % 12 != pc:
            continue
        if best is None or abs(cand - m) < abs(best - m):
            best = cand
    return best if best is not None else lo_midi


@dataclass
class PitchTrack:
    """Per-frame pitch analysis; times are frame centres in seconds."""

    times: np.ndarray
    f0: np.ndarray          # Hz, NaN where unvoiced
    voiced: np.ndarray      # bool
    clarity: np.ndarray     # 1 - CMND dip, ~[0, 1]
    rms: np.ndarray         # frame RMS
    sr: int
    hop: int

    def median_f0(self, mask: np.ndarray | None = None) -> float:
        sel = self.voiced if mask is None else (self.voiced & mask)
        vals = self.f0[sel]
        return float(np.median(vals)) if vals.size else float("nan")

    def slice(self, t0: float, t1: float) -> "PitchTrack":
        m = (self.times >= t0) & (self.times < t1)
        return PitchTrack(self.times[m], self.f0[m], self.voiced[m], self.clarity[m], self.rms[m], self.sr, self.hop)


def _yin_block(frames: np.ndarray, tau_min: int, tau_max: int, threshold: float):
    """YIN steps 1-5 for a (F, L) block of frames. Returns (period, clarity, voiced)."""
    F, L = frames.shape
    x = frames.astype(np.float64)
    w = L - tau_max
    power = np.concatenate([np.zeros((F, 1)), np.cumsum(x * x, axis=1)], axis=1)
    taus = np.arange(tau_max + 1)
    term_first = (power[:, w] - power[:, 0])[:, None]
    term_lagged = power[:, w + taus] - power[:, taus]
    size = 1 << int(math.ceil(math.log2(L + w)))
    spec = np.fft.rfft(x, size, axis=1)
    spec_w = np.fft.rfft(x[:, :w][:, ::-1], size, axis=1)
    conv = np.fft.irfft(spec * spec_w, size, axis=1)
    term_cross = conv[:, w - 1: w + tau_max]
    d = np.maximum(term_first + term_lagged - 2.0 * term_cross, 0.0)

    # Step 3: cumulative-mean-normalised difference.
    cmnd = np.ones_like(d)
    csum = np.cumsum(d[:, 1:], axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cmnd[:, 1:] = d[:, 1:] * taus[1:][None, :] / csum
    cmnd[~np.isfinite(cmnd)] = 1.0

    # Step 4: first dip under the threshold, then walk down to its local minimum.
    region = cmnd[:, tau_min:tau_max]
    below = region < threshold
    has = below.any(axis=1)
    first = np.argmax(below, axis=1)
    n = region.shape[1]
    idx = np.arange(n)[None, :]
    rising = np.zeros_like(below)
    rising[:, :-1] = region[:, 1:] >= region[:, :-1]
    rising[:, -1] = True
    cand = rising & (idx >= first[:, None])
    local_min = np.argmax(cand, axis=1)
    global_min = np.argmin(region, axis=1)
    tau = np.where(has, local_min, global_min) + tau_min

    rows = np.arange(F)
    best = cmnd[rows, tau]
    # Step 5: parabolic refinement for sub-sample period.
    tl = np.clip(tau - 1, 0, tau_max)
    tr = np.clip(tau + 1, 0, tau_max)
    a, b, c = cmnd[rows, tl], best, cmnd[rows, tr]
    den = 2.0 * (a - 2.0 * b + c)
    with np.errstate(divide="ignore", invalid="ignore"):
        shift = np.where(np.abs(den) > 1e-12, (a - c) / den, 0.0)
    shift = np.clip(shift, -1.0, 1.0)
    period = tau + shift
    clarity = 1.0 - best
    voiced = has & (best < threshold)
    return period, clarity, voiced


def yin_track(
    x: np.ndarray,
    sr: int,
    fmin: float = 60.0,
    fmax: float = 1100.0,
    frame: int = 2048,
    hop: int = 512,
    threshold: float = 0.15,
    min_rms_db: float = -50.0,
    chunk: int = 1024,
) -> PitchTrack:
    x = np.asarray(x, dtype=np.float32)
    tau_min = max(2, int(math.floor(sr / fmax)))
    tau_max = min(int(math.ceil(sr / fmin)) + 1, frame // 2)
    if x.shape[0] < frame:
        x = np.pad(x, (0, frame - x.shape[0]))
    frames = block_features(x, frame, hop)
    nF = frames.shape[0]
    periods = np.full(nF, np.nan)
    clar = np.zeros(nF)
    voiced = np.zeros(nF, dtype=bool)
    for s in range(0, nF, chunk):
        blk = frames[s:s + chunk]
        p, c, v = _yin_block(blk, tau_min, tau_max, threshold)
        periods[s:s + chunk] = p
        clar[s:s + chunk] = c
        voiced[s:s + chunk] = v
    # Level over a short window at the frame centre (the analysis frame is long).
    env_len = min(frame, max(64, int(0.02 * sr)))
    off = (frame - env_len) // 2
    seg = frames[:, off:off + env_len].astype(np.float64)
    rms = np.sqrt(np.mean(seg * seg, axis=1))
    loud = 20.0 * np.log10(np.maximum(rms, 1e-9)) > min_rms_db
    voiced &= loud
    f0 = np.where(voiced, sr / np.maximum(periods, 1e-6), np.nan)
    times = (np.arange(nF) * hop + frame / 2.0) / sr
    return PitchTrack(times, f0, voiced, clar, rms, sr, hop)


def median_filter(x: np.ndarray, k: int = 5) -> np.ndarray:
    """Running median ignoring NaNs (k odd)."""
    if x.size == 0 or k <= 1:
        return x.copy()
    half = k // 2
    xp = np.pad(x, (half, half), mode="edge")
    win = np.lib.stride_tricks.sliding_window_view(xp, k)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            out = np.nanmedian(win, axis=1)
    return out


def cents_deviation(f0: np.ndarray) -> float:
    """Spread (std) of voiced f0 around its median, in cents — 0 means perfectly steady."""
    v = f0[np.isfinite(f0)]
    if v.size < 2:
        return float("inf")
    c = 1200.0 * np.log2(v / np.median(v))
    return float(np.std(c))
