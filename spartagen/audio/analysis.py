"""Source analysis: find everything in a video that can become a Sparta sample.

Frame features (hop ≈ 11.6 ms) feed a set of detectors:

* pitch   — steady voiced windows (a held vowel / note) that tune cleanly to D
* kick    — sharp onsets with body in the lows (the "thump-y sound")
* snare   — sharp, noisy, broadband onsets (the "bang")
* hat     — sibilant / hissy runs ("s", "ts", cymbals) for closed + open hats
* crash   — longer loud noisy runs for crashes/impacts
* quote   — speech phrases between pauses (intro / ending / Madness material)
* word    — single words or syllables inside phrases (Madness call & response,
            DunDunDenDen chops)

Every candidate is just a time range in the source, so its video clip is
known too — that is what makes the "cutting video into samples" possible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

import numpy as np

from . import dsp
from .pitch import yin_track, median_filter, hz_to_midi, note_name, nearest_note_of_class

HOP = 512
FRAME = 2048

Progress = Optional[Callable[[float, str], None]]


# ── Frame features ───────────────────────────────────────────────────────────


@dataclass
class Features:
    sr: int
    hop: int
    frame: int
    times: np.ndarray
    rms_db: np.ndarray
    centroid: np.ndarray
    flatness: np.ndarray
    low: np.ndarray
    lowmid: np.ndarray
    mid: np.ndarray
    high: np.ndarray
    air: np.ndarray
    flux: np.ndarray
    f0: np.ndarray
    voiced: np.ndarray
    clarity: np.ndarray
    mfcc: np.ndarray
    noise_floor_db: float
    loud_ref_db: float

    @property
    def n(self) -> int:
        return self.times.shape[0]

    @property
    def noisiness(self) -> np.ndarray:
        """1 - YIN clarity: ~0 for a held vowel/note, ~0.5+ for hiss, snares, cymbals."""
        return 1.0 - self.clarity

    def t2f(self, t: float) -> int:
        return int(np.clip(round((t * self.sr - self.frame / 2) / self.hop), 0, max(self.n - 1, 0)))

    def f2t(self, i: int | np.ndarray) -> float | np.ndarray:
        return (np.asarray(i) * self.hop + self.frame / 2) / self.sr


def _mel_filterbank(sr: int, n_fft: int, n_mels: int = 40, fmin: float = 40.0, fmax: float = 8000.0) -> np.ndarray:
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    mels = np.linspace(hz2mel(fmin), hz2mel(min(fmax, sr / 2)), n_mels + 2)
    hz = mel2hz(mels)
    bins = np.fft.rfftfreq(n_fft, 1.0 / sr)
    fb = np.zeros((n_mels, bins.shape[0]), dtype=np.float32)
    for m in range(n_mels):
        lo, c, hi = hz[m], hz[m + 1], hz[m + 2]
        up = (bins - lo) / max(c - lo, 1e-9)
        down = (hi - bins) / max(hi - c, 1e-9)
        fb[m] = np.maximum(0.0, np.minimum(up, down))
    return fb


def _dct_matrix(n_in: int, n_out: int) -> np.ndarray:
    k = np.arange(n_out)[:, None]
    n = np.arange(n_in)[None, :]
    m = np.cos(np.pi / n_in * (n + 0.5) * k) * math.sqrt(2.0 / n_in)
    m[0] /= math.sqrt(2.0)
    return m.astype(np.float32)


def compute_features(x: np.ndarray, sr: int, progress: Progress = None) -> Features:
    x = np.asarray(x, dtype=np.float32)
    if x.shape[0] < FRAME:
        x = np.pad(x, (0, FRAME - x.shape[0]))
    frames = dsp.block_features(x, FRAME, HOP)
    nF = frames.shape[0]
    win = np.hanning(FRAME).astype(np.float32)
    freqs = np.fft.rfftfreq(FRAME, 1.0 / sr)
    b_low = freqs < 150
    b_lowmid = (freqs >= 150) & (freqs < 800)
    b_mid = (freqs >= 800) & (freqs < 3500)
    b_high = freqs >= 3500          # sibilance band (works on 16 kHz-sampled sources too)
    b_air = freqs >= 8000           # cymbal "air" on full-band sources
    b_flat = (freqs >= 300) & (freqs < 10000)
    fb = _mel_filterbank(sr, FRAME)
    dct = _dct_matrix(fb.shape[0], 14)

    out = {k: np.zeros(nF, dtype=np.float32) for k in
           ("centroid", "flatness", "low", "lowmid", "mid", "high", "air", "flux", "rms_db")}
    mfcc = np.zeros((nF, 13), dtype=np.float32)
    prev_logmag = None
    chunk = 1024
    for s in range(0, nF, chunk):
        blk = frames[s:s + chunk].astype(np.float32)
        # RMS over a 20 ms window at the frame centre, so the level is not smeared by the long FFT frame.
        c0 = FRAME // 2 - int(0.01 * sr)
        seg = blk[:, c0:c0 + int(0.02 * sr)]
        out["rms_db"][s:s + chunk] = 20.0 * np.log10(np.sqrt(np.mean(seg * seg, axis=1)) + 1e-9)
        spec = np.abs(np.fft.rfft(blk * win, axis=1))
        pw = spec * spec + 1e-12
        tot = pw.sum(axis=1)
        out["centroid"][s:s + chunk] = (pw * freqs[None, :]).sum(axis=1) / tot
        band = pw[:, b_flat]
        # Band-limited flatness: full-band flatness is dominated by the (always
        # present) lows and reads ~0 for everything, noise included.
        out["flatness"][s:s + chunk] = np.exp(np.mean(np.log(band), axis=1)) / np.mean(band, axis=1)
        out["low"][s:s + chunk] = pw[:, b_low].sum(axis=1) / tot
        out["lowmid"][s:s + chunk] = pw[:, b_lowmid].sum(axis=1) / tot
        out["mid"][s:s + chunk] = pw[:, b_mid].sum(axis=1) / tot
        out["high"][s:s + chunk] = pw[:, b_high].sum(axis=1) / tot
        out["air"][s:s + chunk] = pw[:, b_air].sum(axis=1) / tot
        logmag = np.log1p(100.0 * spec)
        if prev_logmag is None:
            prev = np.vstack([logmag[:1], logmag[:-1]])
        else:
            prev = np.vstack([prev_logmag[None, :], logmag[:-1]])
        out["flux"][s:s + chunk] = np.maximum(logmag - prev, 0.0).mean(axis=1)
        prev_logmag = logmag[-1]
        mel = np.log(fb @ pw.T + 1e-10)  # (n_mels, chunk)
        mfcc[s:s + chunk] = (dct @ mel).T[:, 1:14]
        if progress:
            progress(0.45 * min(1.0, (s + chunk) / nF), "spectral features")

    tr = yin_track(x, sr, fmin=65.0, fmax=1000.0, frame=FRAME, hop=HOP, threshold=0.18, min_rms_db=-55.0)
    if progress:
        progress(0.7, "pitch tracking")
    n = min(nF, tr.f0.shape[0])
    rms_db = out["rms_db"][:n]
    active = rms_db[rms_db > -85]
    noise = float(np.percentile(active, 10)) if active.size else -80.0
    loud = float(np.percentile(active, 97)) if active.size else -20.0
    flux = out["flux"][:n]
    fl_ref = float(np.percentile(flux, 99)) if flux.size else 1.0
    times = (np.arange(n) * HOP + FRAME / 2) / sr
    return Features(
        sr=sr, hop=HOP, frame=FRAME, times=times,
        rms_db=rms_db, centroid=out["centroid"][:n], flatness=out["flatness"][:n],
        low=out["low"][:n], lowmid=out["lowmid"][:n], mid=out["mid"][:n], high=out["high"][:n], air=out["air"][:n],
        flux=flux / max(fl_ref, 1e-9), f0=median_filter(tr.f0[:n], 5), voiced=tr.voiced[:n],
        clarity=np.clip(tr.clarity[:n], 0.0, 1.0), mfcc=mfcc[:n], noise_floor_db=noise, loud_ref_db=loud,
    )


# ── Candidates ───────────────────────────────────────────────────────────────


@dataclass
class Candidate:
    kind: str
    start: float
    end: float
    score: float
    info: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = round(self.duration, 4)
        d["start"] = round(self.start, 4)
        d["end"] = round(self.end, 4)
        d["score"] = round(float(self.score), 4)
        d["info"] = {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else
                         (int(v) if isinstance(v, (np.integer,)) else v)) for k, v in self.info.items()}
        return d


def _runs(mask: np.ndarray, max_gap: int = 0) -> list[tuple[int, int]]:
    """Half-open runs of True, bridging gaps of up to max_gap False frames."""
    m = np.asarray(mask, dtype=bool).copy()
    if max_gap > 0 and m.any():
        idx = np.flatnonzero(m)
        gaps = np.diff(idx)
        for a, g in zip(idx[:-1], gaps):
            if 1 < g <= max_gap + 1:
                m[a:a + g] = True
    runs = []
    i, n = 0, m.shape[0]
    while i < n:
        if m[i]:
            j = i
            while j < n and m[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _tri(v: float, lo: float, best_lo: float, best_hi: float, hi: float) -> float:
    """Trapezoid preference: 0 outside [lo, hi], 1 inside [best_lo, best_hi]."""
    if v <= lo or v >= hi:
        return 0.0
    if v < best_lo:
        return (v - lo) / max(best_lo - lo, 1e-9)
    if v > best_hi:
        return (hi - v) / max(hi - best_hi, 1e-9)
    return 1.0


def _loud_score(db: float, feat: Features, span: float = 30.0) -> float:
    return float(np.clip((db - (feat.loud_ref_db - span)) / span, 0.0, 1.0))


def find_pitch_candidates(feat: Features, limit: int = 40) -> list[Candidate]:
    good = feat.voiced & (feat.clarity > 0.55) & (feat.rms_db > feat.loud_ref_db - 32) & np.isfinite(feat.f0)
    cents = np.full(feat.n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        cents[good] = 1200.0 * np.log2(feat.f0[good] / 100.0)
    # Rolling local stability: std of cents over 5 frames (~58 ms).
    k = 5
    padded = np.pad(cents, (k // 2, k // 2), constant_values=np.nan)
    win = np.lib.stride_tricks.sliding_window_view(padded, k)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            local_std = np.nanstd(win, axis=1)
    steady = good & (local_std < 35.0)
    cands: list[Candidate] = []
    for a, b in _runs(steady, max_gap=1):
        segs = [(a, b)]
        # Split runs whose pitch wanders (e.g. two different syllable notes).
        out_segs = []
        while segs:
            s0, s1 = segs.pop()
            c = cents[s0:s1]
            c = c[np.isfinite(c)]
            if s1 - s0 < 6 or c.size < 4:
                continue
            if np.nanmax(c) - np.nanmin(c) > 160 and s1 - s0 >= 12:
                jumps = np.abs(np.diff(np.nan_to_num(cents[s0:s1], nan=np.nanmedian(c))))
                cut = s0 + 1 + int(np.argmax(jumps))
                segs += [(s0, cut), (cut, s1)]
            else:
                out_segs.append((s0, s1))
        for s0, s1 in out_segs:
            # Keep at most ~0.6 s: the loudest part of a long vowel.
            max_frames = int(0.6 * feat.sr / feat.hop)
            if s1 - s0 > max_frames:
                db = feat.rms_db[s0:s1]
                csum = np.concatenate([[0.0], np.cumsum(db)])
                best = int(np.argmax(csum[max_frames:] - csum[:-max_frames]))
                s0, s1 = s0 + best, s0 + best + max_frames
            f = feat.f0[s0:s1]
            f = f[np.isfinite(f)]
            if f.size < 4:
                continue
            f0m = float(np.median(f))
            dev = float(np.std(1200.0 * np.log2(f / f0m)))
            dur = (s1 - s0) * feat.hop / feat.sr
            db = float(np.mean(feat.rms_db[s0:s1]))
            clar = float(np.mean(feat.clarity[s0:s1]))
            flat = float(np.mean(feat.flatness[s0:s1]))
            cen = float(np.mean(feat.centroid[s0:s1]))
            s_dur = _tri(dur, 0.06, 0.16, 0.5, 1.2)
            s_stab = math.exp(-dev / 22.0)
            s_clar = float(np.clip((clar - 0.5) / 0.45, 0.0, 1.0))
            s_loud = _loud_score(db, feat)
            s_vowel = float(np.clip(1.0 - 3.0 * flat, 0.1, 1.0)) * (1.0 if 200 < cen < 4000 else 0.6)
            s_range = 1.0 if 75 <= f0m <= 750 else 0.5
            score = (s_dur ** 0.8) * s_stab * (0.2 + 0.8 * s_clar) * (0.25 + 0.75 * s_loud) * s_vowel * s_range
            if score <= 0.01:
                continue
            midi = float(hz_to_midi(f0m))
            d_midi = nearest_note_of_class(f0m, 2)
            start = float(feat.f2t(s0)) - 0.5 * feat.hop / feat.sr - 0.012  # small pre-roll for the attack
            end = float(feat.f2t(s1 - 1)) + 0.5 * feat.hop / feat.sr
            cands.append(Candidate("pitch", max(0.0, start), end, score, {
                "f0": f0m, "midi": midi, "note": note_name(midi), "cents": (midi - round(midi)) * 100.0,
                "stability_cents": dev, "clarity": clar, "loudness_db": db, "centroid": cen,
                "d_midi": d_midi, "d_note": note_name(d_midi), "shift_to_d": d_midi - midi,
            }))
    cands.sort(key=lambda c: -c.score)
    return _dedupe(cands, 0.05)[:limit]


def detect_onsets(feat: Features, delta: float = 0.06, wait_s: float = 0.05) -> np.ndarray:
    o = feat.flux
    n = o.shape[0]
    if n < 3:
        return np.zeros(0, dtype=int)
    pre = max(1, int(0.1 * feat.sr / feat.hop))
    csum = np.concatenate([[0.0], np.cumsum(o)])
    idx = np.arange(n)
    lo = np.maximum(0, idx - pre)
    mean_before = (csum[idx + 1] - csum[lo]) / (idx + 1 - lo)
    local_max = np.ones(n, dtype=bool)
    for sh in (1, 2, 3):
        local_max[sh:] &= o[sh:] >= o[:-sh]
        local_max[:-sh] &= o[:-sh] >= o[sh:]
    # The flux peaks a frame before the attack's energy arrives, so gate on the
    # level just after the onset rather than at the peak frame itself.
    ahead = feat.rms_db.copy()
    for sh in (1, 2, 3):
        ahead[:-sh] = np.maximum(ahead[:-sh], feat.rms_db[sh:])
    loud = ahead > max(feat.noise_floor_db + 10.0, feat.loud_ref_db - 45.0)
    cand = np.flatnonzero(local_max & (o > mean_before + delta) & (o > 0.08) & loud)
    wait = max(1, int(wait_s * feat.sr / feat.hop))
    keep = []
    last = -10 ** 9
    for c in cand:
        if c - last >= wait:
            keep.append(c)
            last = c
        elif o[c] > o[keep[-1]]:
            keep[-1] = c
            last = c
    return np.asarray(keep, dtype=int)


def refine_onset(x: np.ndarray, sr: int, t: float, search_ms: float = 30.0) -> float:
    """Snap an onset to where the waveform actually starts rising (sample accurate)."""
    a = max(0, int((t - search_ms * 1e-3) * sr))
    b = min(x.shape[0], int((t + search_ms * 1e-3) * sr))
    if b - a < 16:
        return t
    env = dsp.one_pole_smooth(np.abs(x[a:b]), 0.9)
    pk = float(env.max())
    if pk <= 1e-6:
        return t
    above = np.flatnonzero(env > 0.15 * pk)
    return (a + int(above[0])) / sr if above.size else t


def find_percussion_candidates(feat: Features, x: np.ndarray, limit: int = 30) -> dict[str, list[Candidate]]:
    onsets = detect_onsets(feat)
    noisiness = np.clip(feat.noisiness, 0.0, 1.0)
    kicks, snares, hits = [], [], []
    for i in onsets:
        p_end = min(feat.n, i + 6)
        p = i + int(np.argmax(feat.rms_db[i:p_end]))
        pk = float(feat.rms_db[p])
        base = float(np.min(feat.rms_db[max(0, i - 3):i + 1]))
        rise = pk - base
        j = p
        while j < feat.n and feat.rms_db[j] > pk - 18.0 and (j - p) * feat.hop / feat.sr < 0.6:
            j += 1
        decay = (j - p) * feat.hop / feat.sr
        w = slice(i, min(feat.n, i + 5))
        e = np.power(10.0, feat.rms_db[w] / 10.0)
        e = e / max(e.sum(), 1e-12)
        low = float(np.sum(feat.low[w] * e))
        lowmid = float(np.sum(feat.lowmid[w] * e))
        high = float(np.sum(feat.high[w] * e))
        flat = float(np.sum(feat.flatness[w] * e))
        noise = float(np.sum(noisiness[w] * e))
        cen = float(np.sum(feat.centroid[w] * e))
        voiced = float(np.mean(feat.voiced[i:min(feat.n, i + 8)]))
        sharp = float(np.clip(rise / 20.0, 0.0, 1.0)) * float(np.clip(feat.flux[i], 0.0, 1.5))
        loud = _loud_score(pk, feat, 35.0)
        t0 = refine_onset(x, feat.sr, float(feat.f2t(i)) - 0.5 * feat.frame / feat.sr + 0.5 * feat.hop / feat.sr)
        info = {"rise_db": rise, "decay_s": decay, "low": low, "lowmid": lowmid, "high": high,
                "flatness": flat, "noisiness": noise, "centroid": cen, "voiced": voiced, "peak_db": pk}
        # Kick: a thump — body in the lows, short, not a sung vowel.
        k_score = sharp * loud * (low + 0.35 * lowmid + 0.03) * _tri(decay, 0.02, 0.05, 0.3, 0.8) * (1.0 - 0.4 * voiced)
        # Snare/clap: a bang — noisy, broadband, mid/high centroid.
        # Band flatness separates drum noise (~0.2+) from speech consonants
        # (~0.01) far better than aperiodicity, which is high for both.
        s_noise = max(float(np.clip(flat / 0.2, 0.0, 1.0)), 0.45 * float(np.clip((noise - 0.2) / 0.4, 0.0, 1.0)))
        s_score = sharp * loud * (0.05 + 0.95 * s_noise) * _tri(cen, 250, 900, 6000, 12000) \
            * _tri(decay, 0.02, 0.05, 0.3, 0.8) * (1.0 - 0.5 * voiced) * (1.0 - 0.5 * low)
        h_score = sharp * loud
        kicks.append(Candidate("kick", t0, t0 + min(max(decay, 0.08), 0.35) + 0.03, k_score, dict(info)))
        snares.append(Candidate("snare", t0, t0 + min(max(decay, 0.08), 0.3) + 0.03, s_score, dict(info)))
        hits.append(Candidate("hit", t0, t0 + min(max(decay, 0.1), 0.5), h_score, dict(info)))
    out = {}
    for name, lst in (("kick", kicks), ("snare", snares), ("hit", hits)):
        lst.sort(key=lambda c: -c.score)
        out[name] = _dedupe([c for c in lst if c.score > 0.0], 0.08)[:limit]
    return out


def find_hat_candidates(feat: Features, limit: int = 20) -> list[Candidate]:
    """Sibilants ("s", "ts", "sh") and cymbal hiss → closed/open hi-hats."""
    noisiness = np.clip(feat.noisiness, 0.0, 1.0)
    hissy = ((feat.high > 0.25) | (feat.air > 0.05)) & ((feat.flatness > 0.02) | (noisiness > 0.45))
    sib = hissy & (feat.rms_db > max(feat.noise_floor_db + 8.0, feat.loud_ref_db - 50.0))
    cands = []
    for a, b in _runs(sib, max_gap=1):
        dur = (b - a) * feat.hop / feat.sr
        if dur < 0.03:
            continue
        high = float(np.mean(feat.high[a:b]))
        air = float(np.mean(feat.air[a:b]))
        flat = float(np.mean(feat.flatness[a:b]))
        noise = float(np.mean(noisiness[a:b]))
        db = float(np.max(feat.rms_db[a:b]))
        cen = float(np.mean(feat.centroid[a:b]))
        hiss = min(1.0, high + 3.0 * air) * (0.3 + 0.7 * max(min(flat / 0.15, 1.0), min(noise / 0.7, 1.0)))
        score = hiss * _tri(dur, 0.02, 0.06, 0.35, 1.5) * (0.3 + 0.7 * _loud_score(db, feat, 40.0)) * \
            (1.0 if cen > 2500 else 0.6)
        start = float(feat.f2t(a)) - 0.5 * feat.hop / feat.sr
        cands.append(Candidate("hat", max(0.0, start), start + dur, score,
                               {"high": high, "air": air, "flatness": flat, "noisiness": noise, "peak_db": db,
                                "centroid": cen, "duration": dur}))
    cands.sort(key=lambda c: -c.score)
    return _dedupe(cands, 0.05)[:limit]


def find_crash_candidates(feat: Features, limit: int = 10) -> list[Candidate]:
    """Longer, loud, noisy stretches (cymbals, explosions, "shhh") → crash."""
    noisiness = np.clip(feat.noisiness, 0.0, 1.0)
    noisy = ((feat.flatness > 0.08) | (noisiness > 0.55)) & (feat.centroid > 1500) & \
        (feat.rms_db > feat.loud_ref_db - 30)
    cands = []
    for a, b in _runs(noisy, max_gap=2):
        dur = (b - a) * feat.hop / feat.sr
        if dur < 0.1:
            continue
        db = float(np.mean(feat.rms_db[a:b]))
        flat = float(np.mean(feat.flatness[a:b]))
        noise = float(np.mean(noisiness[a:b]))
        score = _tri(dur, 0.08, 0.3, 1.5, 4.0) * _loud_score(db, feat, 30.0) * \
            max(min(flat / 0.2, 1.0), min(noise / 0.7, 1.0))
        start = float(feat.f2t(a)) - 0.5 * feat.hop / feat.sr
        cands.append(Candidate("crash", max(0.0, start), start + min(dur, 2.0), score,
                               {"flatness": flat, "noisiness": noise, "loudness_db": db, "duration": dur}))
    cands.sort(key=lambda c: -c.score)
    return _dedupe(cands, 0.2)[:limit]


def _split_long(a: int, b: int, rms: np.ndarray, max_len: int) -> list[tuple[int, int]]:
    if b - a <= max_len:
        return [(a, b)]
    lo, hi = a + max_len // 3, b - max_len // 3
    if hi <= lo:
        mid = (a + b) // 2
    else:
        mid = lo + int(np.argmin(rms[lo:hi]))
    return _split_long(a, mid, rms, max_len) + _split_long(mid, b, rms, max_len)


def find_quote_candidates(feat: Features, limit: int = 25) -> list[Candidate]:
    thr = max(feat.noise_floor_db + 10.0, feat.loud_ref_db - 38.0)
    active = feat.rms_db > thr
    gap = int(0.22 * feat.sr / feat.hop)
    max_len = int(4.0 * feat.sr / feat.hop)
    smooth_db = np.convolve(feat.rms_db, np.ones(5) / 5.0, mode="same")
    cands = []
    for a0, b0 in _runs(active, max_gap=gap):
        for a, b in _split_long(a0, b0, smooth_db, max_len):
            dur = (b - a) * feat.hop / feat.sr
            if dur < 0.45:
                continue
            voiced = float(np.mean(feat.voiced[a:b]))
            db = float(np.mean(feat.rms_db[a:b]))
            pk = float(np.max(feat.rms_db[a:b]))
            f = feat.f0[a:b]
            f = f[np.isfinite(f)]
            expr = float(np.std(12.0 * np.log2(f / np.median(f)))) if f.size > 4 else 0.0
            silence_inside = float(np.mean(feat.rms_db[a:b] < thr))
            score = _tri(dur, 0.4, 0.9, 2.6, 5.0) * _tri(voiced, 0.12, 0.35, 1.01, 1.02) * \
                (0.2 + 0.8 * _loud_score(db, feat, 30.0)) * (0.7 + 0.3 * min(expr / 3.0, 1.0)) * \
                (1.0 - 0.6 * silence_inside)
            if score <= 0.01:
                continue
            start = float(feat.f2t(a)) - 0.5 * feat.hop / feat.sr - 0.03
            end = float(feat.f2t(b - 1)) + 0.5 * feat.hop / feat.sr + 0.06
            cands.append(Candidate("quote", max(0.0, start), end, score,
                                   {"voiced": voiced, "loudness_db": db, "peak_db": pk, "expressiveness": expr,
                                    "frames": (a, b)}))
    cands.sort(key=lambda c: -c.score)
    return _dedupe(cands, 0.3)[:limit]


def split_syllables(feat: Features, a: int, b: int, min_len_s: float = 0.09) -> list[tuple[int, int]]:
    """Split frames [a, b) at energy valleys (≥ 5 dB below both neighbouring peaks)."""
    db = np.convolve(feat.rms_db, np.ones(3) / 3.0, mode="same")[a:b]
    n = db.shape[0]
    if n < 4:
        return [(a, b)]
    minima = [i for i in range(1, n - 1) if db[i] <= db[i - 1] and db[i] <= db[i + 1]]
    cuts = []
    for m in minima:
        left, right = db[:m].max(initial=db[m]), db[m + 1:].max(initial=db[m])
        # Local peaks within ±150 ms are what count as "neighbours".
        w = max(2, int(0.15 * feat.sr / feat.hop))
        left = db[max(0, m - w):m].max(initial=db[m])
        right = db[m + 1:m + 1 + w].max(initial=db[m])
        if min(left, right) - db[m] >= 5.0:
            cuts.append(m)
    # Onsets inside the phrase also start syllables.
    bounds = sorted(set([0] + cuts + [n]))
    min_len = max(1, int(min_len_s * feat.sr / feat.hop))
    merged = [bounds[0]]
    for c in bounds[1:]:
        if c - merged[-1] < min_len and c != n:
            continue
        merged.append(c)
    if merged[-1] != n:
        merged[-1] = n
    segs = [(a + s, a + e) for s, e in zip(merged[:-1], merged[1:]) if e - s >= 1]
    return segs or [(a, b)]


def find_word_candidates(feat: Features, quotes: list[Candidate], limit: int = 40) -> list[Candidate]:
    thr = max(feat.noise_floor_db + 10.0, feat.loud_ref_db - 38.0)
    words = []
    for qi, q in enumerate(quotes):
        a, b = q.info.get("frames", (feat.t2f(q.start), feat.t2f(q.end)))
        for s0, s1 in split_syllables(feat, a, b, 0.12):
            # Trim quiet edges.
            while s0 < s1 and feat.rms_db[s0] < thr:
                s0 += 1
            while s1 > s0 and feat.rms_db[s1 - 1] < thr:
                s1 -= 1
            dur = (s1 - s0) * feat.hop / feat.sr
            if dur < 0.1 or dur > 1.0:
                continue
            db = float(np.mean(feat.rms_db[s0:s1]))
            voiced = float(np.mean(feat.voiced[s0:s1]))
            score = _tri(dur, 0.08, 0.18, 0.5, 1.0) * (0.3 + 0.7 * _loud_score(db, feat, 30.0)) * (0.4 + 0.6 * voiced)
            start = float(feat.f2t(s0)) - 0.5 * feat.hop / feat.sr - 0.015
            end = float(feat.f2t(s1 - 1)) + 0.5 * feat.hop / feat.sr + 0.03
            mf = feat.mfcc[s0:s1].mean(axis=0)
            words.append(Candidate("word", max(0.0, start), end, score,
                                   {"quote_index": qi, "loudness_db": db, "voiced": voiced,
                                    "mfcc": [float(v) for v in mf]}))
    words.sort(key=lambda c: -c.score)
    return _dedupe(words, 0.05)[:limit]


def similar_word(words: list[Candidate], ref: Candidate) -> Optional[Candidate]:
    """Best match for ``ref`` from a *different* quote: similar length and timbre."""
    r = np.asarray(ref.info.get("mfcc", []), dtype=np.float64)
    best, best_s = None, -1e9
    for w in words:
        if w is ref or w.info.get("quote_index") == ref.info.get("quote_index"):
            continue
        v = np.asarray(w.info.get("mfcc", []), dtype=np.float64)
        if v.size != r.size or v.size == 0:
            continue
        cos = float(np.dot(r, v) / (np.linalg.norm(r) * np.linalg.norm(v) + 1e-9))
        dur_sim = math.exp(-abs(math.log(max(w.duration, 1e-3) / max(ref.duration, 1e-3))) * 2.0)
        s = (0.5 + 0.5 * cos) * dur_sim * (0.3 + w.score)
        if s > best_s:
            best, best_s = w, s
    return best


def _dedupe(cands: list[Candidate], min_gap: float) -> list[Candidate]:
    """Drop candidates overlapping an already-kept (better) one."""
    kept: list[Candidate] = []
    for c in cands:
        if all(c.end + min_gap <= k.start or c.start >= k.end + min_gap for k in kept):
            kept.append(c)
    return kept


# ── Full analysis ────────────────────────────────────────────────────────────


@dataclass
class Analysis:
    duration: float
    sr: int
    noise_floor_db: float
    loud_ref_db: float
    candidates: dict[str, list[Candidate]]

    def best(self, kind: str, index: int = 0) -> Optional[Candidate]:
        lst = self.candidates.get(kind) or []
        return lst[index] if index < len(lst) else None

    def to_dict(self) -> dict:
        return {
            "duration": round(self.duration, 4),
            "sr": self.sr,
            "noise_floor_db": round(self.noise_floor_db, 2),
            "loud_ref_db": round(self.loud_ref_db, 2),
            "candidates": {k: [c.to_dict() for c in v] for k, v in self.candidates.items()},
        }

    @staticmethod
    def from_dict(d: dict) -> "Analysis":
        cands = {}
        for k, lst in d.get("candidates", {}).items():
            cands[k] = [Candidate(c["kind"], c["start"], c["end"], c["score"], dict(c.get("info", {}))) for c in lst]
        return Analysis(d["duration"], d["sr"], d["noise_floor_db"], d["loud_ref_db"], cands)


def analyze(x: np.ndarray, sr: int, progress: Progress = None) -> Analysis:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if dsp.peak(x) < 1e-4:
        raise ValueError("the source audio is silent — nothing to sample")
    x = dsp.highpass(x, sr, 30.0, order=2)  # remove DC / rumble before measuring
    feat = compute_features(x, sr, progress)
    if progress:
        progress(0.75, "finding pitch samples")
    pitches = find_pitch_candidates(feat)
    if progress:
        progress(0.82, "finding percussion")
    perc = find_percussion_candidates(feat, x)
    hats = find_hat_candidates(feat)
    crashes = find_crash_candidates(feat)
    if progress:
        progress(0.9, "finding quotes and words")
    quotes = find_quote_candidates(feat)
    words = find_word_candidates(feat, quotes)
    cands = {
        "pitch": pitches,
        "kick": perc["kick"],
        "snare": perc["snare"],
        "hit": perc["hit"],
        "hat": hats,
        "crash": crashes,
        "quote": quotes,
        "word": words,
    }
    if progress:
        progress(1.0, "analysis done")
    return Analysis(x.shape[0] / sr, sr, feat.noise_floor_db, feat.loud_ref_db, cands)
