"""Pull a voice's harmonics out of a busy mix (music-video sources).

A held note cut from a song carries the band under it; tuned to D it would
bring the band's chords along and stop sounding like a pitch.  Remixers
isolate the note first (Melodyne's note separation).  This does the same with
a time-varying harmonic mask on the short-time spectrum: bins near k·f0 of the
tracked voice are kept, everything between the harmonics is pushed down.  The
result is the source's own audio, filtered — no synthesis.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .pitch import yin_track


def harmonic_filter(x: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 1000.0, n: int = 2048,
                    hop: int = 256, width_cents: float = 45.0, floor_db: float = -30.0,
                    max_freq: float = 9000.0, f0_hint: Optional[float] = None) -> tuple[np.ndarray, float]:
    """(filtered audio, share of voiced frames).  Unvoiced frames are attenuated like the gaps.

    ``f0_hint`` (the held note's pitch, known from detection) stands in wherever the tracker is
    unsure — a loud band can hide the voice's periodicity from YIN."""
    x = np.asarray(x, dtype=np.float32)
    if x.shape[0] < n // 2:
        return x.copy(), 0.0
    tr = yin_track(x, sr, fmin=fmin, fmax=fmax, frame=2048, hop=128, threshold=0.35, min_rms_db=-55)
    if f0_hint is not None and np.isfinite(f0_hint) and f0_hint > 0:
        loud = tr.rms > (np.max(tr.rms) * 10 ** (-30 / 20.0) if tr.rms.size else 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            off = np.abs(1200.0 * np.log2(tr.f0 / f0_hint))
        # Frames the tracker misses, or reads at another note or octave, take the held note's pitch.
        near = np.isfinite(off) & (off < 100.0)
        use_hint = loud & ~(tr.voiced & near)
        tr.f0 = np.where(use_hint, float(f0_hint), tr.f0)
        tr.voiced = tr.voiced & near | use_hint
    pad = n // 2
    xp = np.pad(x, (pad, pad + n))
    nfr = 1 + (xp.shape[0] - n) // hop
    win = np.hanning(n).astype(np.float32)
    idx = np.arange(n)[None, :] + hop * np.arange(nfr)[:, None]
    X = np.fft.rfft(xp[idx] * win, axis=1)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    centres = (np.arange(nfr) * hop) / sr                 # frame centre in the unpadded signal
    ok = tr.voiced & np.isfinite(tr.f0)
    floor = float(10 ** (floor_db / 20.0))
    mask = np.full(X.shape, floor, dtype=np.float32)
    voiced_frames = 0
    ratio = 2 ** (width_cents / 1200.0) - 1.0
    for i, t in enumerate(centres):
        j = int(np.argmin(np.abs(tr.times - t)))
        if not ok[j] or abs(tr.times[j] - t) > 0.03:
            continue
        f0 = float(tr.f0[j])
        k = np.arange(1, int(min(max_freq, sr / 2 - 100) // f0) + 1)
        if k.size == 0:
            continue
        voiced_frames += 1
        centres_k = k * f0
        sig = np.maximum(12.0, centres_k * ratio)
        # Nearest harmonic per bin → one Gaussian lobe each (cheap and exact enough).
        near = np.clip(np.round(freqs / f0).astype(int), 1, k[-1])
        d = freqs - near * f0
        lobe = np.exp(-0.5 * (d / sig[near - 1]) ** 2)
        lobe[freqs < 0.5 * f0] = 0.0
        mask[i] = np.maximum(lobe, floor)
    Y = X * mask
    y = np.fft.irfft(Y, n, axis=1).astype(np.float32) * win
    out = np.zeros(xp.shape[0], dtype=np.float32)
    norm = np.zeros(xp.shape[0], dtype=np.float32)
    for i in range(nfr):
        a = i * hop
        out[a:a + n] += y[i]
        norm[a:a + n] += win * win
    out = out / np.maximum(norm, 1e-3)
    return out[pad:pad + x.shape[0]], voiced_frames / max(1, nfr)
