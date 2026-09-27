"""Xleth-style effects rack, offline and vectorised.

The set mirrors the processors Xleth ships for Sparta/YTPMV polishing
(engine/src/audio/*Effect.h): OTT, compressor, limiter, EQ/filter,
waveshaper/distortion, reverb, delay, chorus, flanger, phaser, transient
processor, plus the edit-style effects remixers lean on (gross-beat gates,
sidechain pumping, stutter, tape stop, filter sweeps, bitcrush).

Every function takes mono ``(n,)`` or stereo ``(n, 2)`` float32 audio and
returns the same layout.  Envelope followers run at block rate and are
interpolated back to the sample rate, which keeps pure-Python loops short.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Optional, Sequence

import numpy as np

from . import dsp


def _as2d(x: np.ndarray) -> tuple[np.ndarray, bool]:
    x = np.asarray(x, dtype=np.float32)
    return (x[:, None], True) if x.ndim == 1 else (x, False)


#: Samples per piece when an effect works through a long signal piece by piece (bounded memory:
#: a whole remix's stems at once would not fit a phone).
CHUNK = 1 << 18


def _back(y: np.ndarray, was_mono: bool) -> np.ndarray:
    return (y[:, 0] if was_mono else y).astype(np.float32, copy=False)


def mix(dry: np.ndarray, wet: np.ndarray, amount: float) -> np.ndarray:
    if amount >= 1.0:
        return wet.astype(np.float32, copy=False)
    if amount <= 0.0:
        return dry.astype(np.float32, copy=False)
    n = min(dry.shape[0], wet.shape[0])
    out = wet.copy() if wet.shape[0] >= dry.shape[0] else dry.copy()
    out[:n] = dry[:n] * (1.0 - amount) + wet[:n] * amount
    return out.astype(np.float32)


def gain(x: np.ndarray, db: float) -> np.ndarray:
    return (x * dsp.db_to_gain(db)).astype(np.float32)


# ── EQ / filters ─────────────────────────────────────────────────────────────


def eq(x: np.ndarray, sr: int, bands: Sequence[dict]) -> np.ndarray:
    """bands: [{"type": "peak"|"lowshelf"|"highshelf"|"lowpass"|"highpass"|"bandpass"|"notch",
    "freq": Hz, "q": 0.7, "gain": dB}, ...]"""
    if not bands:
        return np.asarray(x, dtype=np.float32)
    sos = np.stack([dsp.biquad(b["type"], b["freq"], sr, b.get("q", 0.7071), b.get("gain", 0.0)) for b in bands])
    return dsp.sosfilt(sos, x, sr)


def stft_filter(x: np.ndarray, sr: int, gain_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
                n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """Time-varying spectral filter: gain_fn(frame_times[s], freqs[Hz]) -> (frames, bins) linear gains.

    Used for filter sweeps and risers where coefficients change continuously.
    """
    x2, mono = _as2d(x)
    n = x2.shape[0]
    win = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    pad = n_fft
    xp = np.pad(x2, ((pad, pad + n_fft), (0, 0)))
    n_frames = 1 + (xp.shape[0] - n_fft) // hop
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    times = (np.arange(n_frames) * hop - pad + n_fft / 2) / sr
    gains = np.asarray(gain_fn(times, freqs), dtype=np.float32)
    out = np.zeros_like(xp)
    norm = np.zeros(xp.shape[0], dtype=np.float32)
    for ch in range(x2.shape[1]):
        frames = np.lib.stride_tricks.sliding_window_view(xp[:, ch], n_fft)[::hop][:n_frames]
        spec = np.fft.rfft(frames * win, axis=1) * gains
        rec = np.fft.irfft(spec, n_fft, axis=1) * win
        for i in range(n_frames):
            s = i * hop
            out[s:s + n_fft, ch] += rec[i]
            if ch == 0:
                norm[s:s + n_fft] += win * win
    out /= np.maximum(norm, 1e-6)[:, None]
    return _back(out[pad:pad + n], mono)


def filter_sweep(x: np.ndarray, sr: int, kind: str = "lowpass", f_start: float = 300.0, f_end: float = 18000.0,
                 resonance_db: float = 3.0, curve: float = 2.0) -> np.ndarray:
    """Exponential cutoff sweep over the clip (the classic build-up / breakdown filter)."""
    dur = max(np.asarray(x).shape[0] / sr, 1e-6)

    def gains(times: np.ndarray, freqs: np.ndarray) -> np.ndarray:
        u = np.clip(times / dur, 0.0, 1.0) ** curve
        fc = f_start * (f_end / f_start) ** u
        r = freqs[None, :] / np.maximum(fc[:, None], 1.0)
        if kind == "lowpass":
            g = 1.0 / np.sqrt(1.0 + r ** 8)
        else:
            g = 1.0 / np.sqrt(1.0 + (1.0 / np.maximum(r, 1e-6)) ** 8)
        bump = 1.0 + (dsp.db_to_gain(resonance_db) - 1.0) * np.exp(-((np.log2(np.maximum(r, 1e-6))) ** 2) / 0.08)
        return g * bump
    return stft_filter(x, sr, gains)


# ── Dynamics ─────────────────────────────────────────────────────────────────


def _gain_computer(level_db: np.ndarray, threshold: float, ratio: float, knee: float) -> np.ndarray:
    over = level_db - threshold
    gr = np.zeros_like(level_db)
    if knee > 0:
        in_knee = np.abs(over) <= knee / 2
        gr[in_knee] = (1.0 / ratio - 1.0) * (over[in_knee] + knee / 2) ** 2 / (2 * knee)
        above = over > knee / 2
    else:
        above = over > 0
    gr[above] = (1.0 / ratio - 1.0) * over[above]
    return gr


def compressor(x: np.ndarray, sr: int, threshold_db: float = -18.0, ratio: float = 4.0, attack_ms: float = 5.0,
               release_ms: float = 80.0, knee_db: float = 6.0, makeup_db: float = 0.0, mix_amount: float = 1.0,
               detector: str = "rms", sidechain: Optional[np.ndarray] = None) -> np.ndarray:
    x2, mono = _as2d(x)
    sc = x2 if sidechain is None else _as2d(sidechain)[0]
    env = dsp.envelope(sc, sr, attack_ms, release_ms, mode=detector, block=32)
    n = min(x2.shape[0], env.shape[0])
    y = x2.copy()
    for a in range(0, n, CHUNK):                 # the gain, piece by piece (same result, less memory)
        b = min(n, a + CHUNK)
        lvl = dsp.gain_to_db(np.maximum(env[a:b], 1e-9))
        y[a:b] *= dsp.db_to_gain(_gain_computer(lvl, threshold_db, ratio, knee_db) + makeup_db).astype(
            np.float32)[:, None]
    return _back(mix(x2, y, mix_amount), mono)


def limiter(x: np.ndarray, sr: int, ceiling_db: float = -1.0, release_ms: float = 60.0,
            lookahead_ms: float = 3.0) -> np.ndarray:
    """Look-ahead peak limiter: gain never lets |x| exceed the ceiling."""
    x2, mono = _as2d(x)
    n = x2.shape[0]
    if n == 0:
        return _back(x2, mono)
    ceil = dsp.db_to_gain(ceiling_db)
    la = max(1, int(lookahead_ms * 1e-3 * sr))
    pk = np.max(np.abs(x2), axis=1)
    # Max over the look-ahead window (the current and the next `la` samples).
    fut = dsp.running_max(pk, la + 1)
    target = np.minimum(1.0, ceil / np.maximum(fut, 1e-9))
    # Instant attack, smooth release — run at block rate on the minimum gain.
    blk = 32
    nb = (n + blk - 1) // blk
    tb = np.pad(target, (0, nb * blk - n), constant_values=1.0).reshape(nb, blk).min(axis=1)
    rel = math.exp(-1.0 / max(release_ms * 1e-3 * sr / blk, 1e-6))
    gb = np.empty(nb)
    g = 1.0
    for i, t in enumerate(tb.tolist()):
        g = t if t < g else rel * g + (1.0 - rel) * t
        gb[i] = g
    gs = np.repeat(gb, blk)[:n]
    # Smooth block steps with a short moving average, then re-apply the hard bound.
    k = max(1, blk)
    gs = np.convolve(np.pad(gs, (k, k), mode="edge"), np.ones(k) / k, mode="same")[k:-k]
    gs = np.minimum(gs, target)
    # The gain already starts falling `la` samples ahead of each peak (it is
    # computed from future peaks), so the signal itself needs no delay.
    y = x2 * gs[:, None]
    y = np.clip(y, -ceil, ceil)
    return _back(y, mono)


# Xleth OTT preset (engine/src/audio/XlethOTTEffect.h kBands):
#   attack ms, release ms, down thresh dB, down ratio, up thresh dB, up ratio, band gain dB
_OTT_BANDS = (
    (47.8, 282.0, -33.8, 66.7, -40.8, 4.17, 10.3),
    (22.4, 282.0, -30.3, 66.7, -41.8, 4.17, 5.7),
    (13.5, 132.0, -35.5, 1e6, -40.8, 4.17, 10.3),
)
_OTT_INPUT_DB = 5.2
_OTT_MASTER_DB = -2.0
_OTT_GATE_DB = -80.0


def ott(x: np.ndarray, sr: int, depth: float = 0.5, time: float = 0.5, xover_low: float = 88.0,
        xover_high: float = 2500.0, gain_low: float = 0.0, gain_mid: float = 0.0, gain_high: float = 0.0,
        output_db: float = 0.0) -> np.ndarray:
    """3-band upward + downward compressor — a port of Xleth's XlethOTTEffect.

    depth scales the compression amount (0..1), not a dry/wet mix, so the
    crossover's phase is identical at every setting.  time scales all
    attack/release times (0.5 = the preset's base values).
    """
    x2, mono = _as2d(x)
    lo_sos, hi_sos = dsp.linkwitz_riley(xover_low, sr)
    lo2_sos, hi2_sos = dsp.linkwitz_riley(xover_high, sr)
    ap = np.stack([dsp.biquad("allpass", xover_high, sr, 0.7071)] * 2)  # LR4 allpass phase match
    user = (gain_low, gain_mid, gain_high)
    tscale = max(time / 0.5, 0.002)
    blk = 16
    n = x2.shape[0]
    nb = (n + blk - 1) // blk
    centers = np.arange(nb) * blk + blk / 2.0
    in_gain = dsp.db_to_gain(_OTT_INPUT_DB)
    out = np.zeros_like(x2)

    def compress(b: int, band: np.ndarray) -> None:
        """One band's up/down compression, added to the output — band by band, piece by piece (memory)."""
        atk, rel, dth, dra, uth, ura, bgain = _OTT_BANDS[b]
        sqb = np.empty(nb)
        for a0 in range(0, n, CHUNK):                    # CHUNK is a whole number of blocks
            a1 = min(n, a0 + CHUNK)
            sc = band[a0:a1] * in_gain
            sq = 0.5 * np.sum(sc * sc, axis=1) if sc.shape[1] > 1 else sc[:, 0] ** 2
            k = a1 - a0
            kb = (k + blk - 1) // blk
            sqb[a0 // blk:a0 // blk + kb] = np.pad(sq, (0, kb * blk - k)).reshape(kb, blk).mean(axis=1)
        brate = sr / blk
        ac = math.exp(-1.0 / max(atk * tscale * 1e-3 * brate, 1e-6))
        rc = math.exp(-1.0 / max(rel * tscale * 1e-3 * brate, 1e-6))
        env = np.empty(nb)
        pk = e = 0.0
        for i, v in enumerate(sqb.tolist()):
            pk = max(v, rc * pk + (1.0 - rc) * v)
            e = ac * e + (1.0 - ac) * pk
            env[i] = e
        env_db = 20.0 * np.log10(np.maximum(np.sqrt(np.maximum(env, 1e-12)), 1e-6))
        g_db = np.zeros_like(env_db)
        up = (env_db < uth) & (env_db > _OTT_GATE_DB)
        g_db[up] += (uth - env_db[up]) * (1.0 - 1.0 / ura)
        dn = env_db > dth
        g_db[dn] -= (env_db[dn] - dth) * (1.0 - 1.0 / dra)
        total_db = (g_db + bgain + _OTT_INPUT_DB) * depth + user[b]
        for a0 in range(0, n, CHUNK):
            a1 = min(n, a0 + CHUNK)
            g = np.power(10.0, np.interp(np.arange(a0, a1), centers, total_db) / 20.0).astype(np.float32)
            out[a0:a1] += band[a0:a1] * g[:, None]

    compress(0, dsp.sosfilt(ap, dsp.sosfilt(lo_sos, x2, sr), sr))
    midhigh = dsp.sosfilt(hi_sos, x2, sr)
    compress(1, dsp.sosfilt(lo2_sos, midhigh, sr))
    compress(2, dsp.sosfilt(hi2_sos, midhigh, sr))
    del midhigh
    out *= dsp.db_to_gain(_OTT_MASTER_DB * depth + output_db)
    return _back(out, mono)


def transient(x: np.ndarray, sr: int, attack_db: float = 4.0, sustain_db: float = 0.0) -> np.ndarray:
    """Transient processor: boost/cut the attack and the sustain independently."""
    x2, mono = _as2d(x)
    fast = dsp.envelope(x2, sr, 0.5, 30.0, mode="peak", block=8)
    slow = dsp.envelope(x2, sr, 15.0, 120.0, mode="peak", block=8)
    y = x2.copy()
    for a in range(0, y.shape[0], CHUNK):
        b = min(y.shape[0], a + CHUNK)
        diff = np.clip((fast[a:b] - slow[a:b]) / np.maximum(fast[a:b], 1e-6), 0.0, 1.0)
        y[a:b] *= dsp.db_to_gain(attack_db * diff + sustain_db * (1.0 - diff)).astype(np.float32)[:, None]
    return _back(y, mono)


# ── Distortion ───────────────────────────────────────────────────────────────


def saturate(x: np.ndarray, drive_db: float = 6.0, mode: str = "tanh", mix_amount: float = 1.0,
             output_db: float = 0.0) -> np.ndarray:
    """Waveshaper: tanh (warm), soft (cubic), hard (clip), fold (wavefolder), asym (tube-ish)."""
    x = np.asarray(x, dtype=np.float32)
    d = dsp.db_to_gain(drive_db)
    u = x * np.float32(d)
    if mode == "tanh":
        y = np.tanh(u, out=u)                    # in place: a whole stem at a time
        if d > 1:
            y /= np.float32(max(math.tanh(d), 1e-6))
    elif mode == "soft":
        uc = np.clip(u, -1.5, 1.5)
        y = uc - (uc ** 3) / 6.75
    elif mode == "hard":
        y = np.clip(u, -1.0, 1.0)
    elif mode == "fold":
        y = np.sin(np.clip(u, -8, 8) * math.pi / 2.0)
    elif mode == "asym":
        y = np.where(u >= 0, np.tanh(u), np.tanh(0.7 * u) / 0.7 * 0.8)
    else:
        raise ValueError(f"unknown saturation mode {mode!r}")
    if output_db:
        y = y * dsp.db_to_gain(output_db)
    return mix(x, y.astype(np.float32, copy=False), mix_amount)


def bitcrush(x: np.ndarray, sr: int, bits: int = 8, downsample: int = 4, mix_amount: float = 1.0) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    q = 2.0 ** (bits - 1)
    y = np.round(x * q) / q
    if downsample > 1:
        idx = (np.arange(y.shape[0]) // downsample) * downsample
        y = y[idx]
    return mix(x, y.astype(np.float32), mix_amount)


# ── Space ────────────────────────────────────────────────────────────────────


def reverb_ir(sr: int, decay_s: float = 1.6, predelay_ms: float = 12.0, damping: float = 0.5,
              size: float = 0.7, seed: int = 7) -> np.ndarray:
    """Stereo impulse response for a plate/room-like algorithmic reverb.

    Early reflections are sparse taps, the tail is decorrelated noise with an
    exponential envelope whose high end decays faster (damping).
    """
    rng = np.random.RandomState(seed)
    n = int((decay_s * 1.2 + predelay_ms * 1e-3) * sr) + 1
    t = np.arange(n) / sr
    pre = int(predelay_ms * 1e-3 * sr)
    ir = np.zeros((n, 2), dtype=np.float32)
    # Early reflections (first ~80 ms scaled by size).
    for k in range(18):
        d = pre + int(rng.uniform(0.002, 0.08 * size + 0.01) * sr)
        if d < n:
            ir[d, rng.randint(2)] += rng.uniform(0.2, 0.7) * (1 if rng.rand() > 0.5 else -1)
    tail = rng.randn(n, 2).astype(np.float32)
    env = np.exp(-6.9 * t / max(decay_s, 1e-3)).astype(np.float32)
    env[:pre] = 0.0
    # Fade the tail in over the early-reflection window.
    fade = min(n - pre, int(0.03 * sr))
    if fade > 0:
        env[pre:pre + fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    tail *= env[:, None]
    # Damping: split the tail in two bands; highs decay (damping x) faster.
    hi = dsp.highpass(tail, sr, 3000.0, order=2)
    lo = tail - hi
    hi_env = np.exp(-6.9 * t * (1.0 + 3.0 * damping) / max(decay_s, 1e-3)).astype(np.float32)
    tail = lo + hi * (hi_env / np.maximum(env, 1e-6))[:, None] * (env > 0)[:, None]
    ir += 0.35 * tail
    ir /= max(float(np.sqrt(np.sum(ir ** 2) / 2)), 1e-6)
    return ir.astype(np.float32)


_IR_CACHE: dict[tuple, np.ndarray] = {}


def reverb(x: np.ndarray, sr: int, mix_amount: float = 0.2, decay_s: float = 1.6, predelay_ms: float = 12.0,
           damping: float = 0.5, size: float = 0.7, lowcut: float = 200.0, width: float = 1.0) -> np.ndarray:
    key = (sr, round(decay_s, 3), round(predelay_ms, 2), round(damping, 3), round(size, 3))
    ir = _IR_CACHE.get(key)
    if ir is None:
        ir = reverb_ir(sr, decay_s, predelay_ms, damping, size)
        _IR_CACHE[key] = ir
    x2, mono = _as2d(x)
    src = dsp.to_mono(x2) if x2.shape[1] > 1 else x2[:, 0]
    if lowcut > 0:
        src = dsp.highpass(src, sr, lowcut, order=2)
    wet = np.stack([dsp.fft_convolve(src, ir[:, 0]), dsp.fft_convolve(src, ir[:, 1])], axis=1)
    if width != 1.0:
        wet = stereo_width(wet, width)
    n = x2.shape[0] + ir.shape[0]
    dry = np.pad(dsp.to_stereo(x2[:, 0]) if mono else x2, ((0, n - x2.shape[0]), (0, 0)))
    wet = dsp.fit_length(wet, n)
    y = dry * (1.0 - 0.5 * mix_amount) + wet * mix_amount
    return y.astype(np.float32)  # stereo, with tail


def delay(x: np.ndarray, sr: int, time_s: float = 0.2143, feedback: float = 0.35, mix_amount: float = 0.2,
          pingpong: bool = True, lowpass_hz: float = 6000.0, repeats: int = 8) -> np.ndarray:
    """Tempo delay rendered as a finite chain of filtered echoes (returns stereo, with tail)."""
    x2, mono = _as2d(x)
    src = dsp.to_mono(x2) if x2.shape[1] > 1 else x2[:, 0]
    d = max(1, int(time_s * sr))
    n = x2.shape[0] + d * repeats
    wet = np.zeros((n, 2), dtype=np.float32)
    echo = src.copy()
    for k in range(1, repeats + 1):
        echo = dsp.lowpass(echo, sr, lowpass_hz, order=2) * feedback if k > 1 else echo * 1.0
        g = 1.0 if k == 1 else 1.0
        ch = (k % 2) if pingpong else None
        start = d * k
        seg = echo * g
        e = min(n, start + seg.shape[0])
        if ch is None:
            wet[start:e] += seg[: e - start, None]
        else:
            wet[start:e, ch] += seg[: e - start]
        if np.max(np.abs(echo)) < 1e-4:
            break
    dry = np.pad(dsp.to_stereo(x2[:, 0]) if mono else x2, ((0, n - x2.shape[0]), (0, 0)))
    return (dry + wet * mix_amount).astype(np.float32)


def _mod_delay(x: np.ndarray, sr: int, base_ms: float, depth_ms: float, rate_hz: float, phase: float = 0.0) -> np.ndarray:
    """Read x through an LFO-swept delay line (linear interpolation), piece by piece."""
    n = x.shape[0]
    xp = np.concatenate([np.zeros(1, dtype=np.float32), np.asarray(x, dtype=np.float32), np.zeros(1, dtype=np.float32)])
    out = np.empty(n, dtype=np.float32)
    for s0 in range(0, n, CHUNK):
        s1 = min(n, s0 + CHUNK)
        idx = np.arange(s0, s1, dtype=np.float32)
        t = idx / np.float32(sr)
        d = (base_ms + depth_ms * 0.5 * (1.0 + np.sin(np.float32(2 * math.pi * rate_hz) * t + np.float32(phase)))) \
            * np.float32(1e-3 * sr)
        pos = idx - d
        i0 = np.floor(pos).astype(np.int64)
        frac = (pos - i0).astype(np.float32)
        a = np.clip(i0 + 1, 0, n + 1)
        b = np.clip(i0 + 2, 0, n + 1)
        out[s0:s1] = xp[a] * (1.0 - frac) + xp[b] * frac
    return out


def chorus(x: np.ndarray, sr: int, rate_hz: float = 0.8, depth_ms: float = 4.0, base_ms: float = 12.0,
           mix_amount: float = 0.4, voices: int = 2) -> np.ndarray:
    x2, mono = _as2d(x)
    src = dsp.to_mono(x2) if x2.shape[1] > 1 else x2[:, 0]
    L = np.zeros_like(src)
    R = np.zeros_like(src)
    for v in range(voices):
        ph = 2 * math.pi * v / voices
        L += _mod_delay(src, sr, base_ms, depth_ms, rate_hz * (1 + 0.1 * v), ph)
        R += _mod_delay(src, sr, base_ms, depth_ms, rate_hz * (1 + 0.1 * v), ph + math.pi / 2)
    wet = np.stack([L, R], axis=1) / voices
    dry = dsp.to_stereo(x2[:, 0]) if mono else x2
    return mix(dry, wet, mix_amount)


def flanger(x: np.ndarray, sr: int, rate_hz: float = 0.25, depth_ms: float = 3.0, base_ms: float = 1.0,
            feedback: float = 0.5, mix_amount: float = 0.5) -> np.ndarray:
    x2, mono = _as2d(x)
    out = np.empty_like(x2)
    g1, g2 = 0.8, 0.8 * feedback
    for ch in range(x2.shape[1]):
        s = x2[:, ch]
        wet = _mod_delay(s, sr, base_ms, depth_ms, rate_hz, ch * math.pi / 2)
        # A second pass through the same swept delay approximates the feedback resonance.
        wet2 = _mod_delay(wet, sr, base_ms, depth_ms, rate_hz, ch * math.pi / 2)
        out[:, ch] = (s + g1 * wet + g2 * wet2) / (1.0 + 0.5 * (g1 + g2))
    return _back(mix(x2, out, mix_amount), mono)


def phaser(x: np.ndarray, sr: int, rate_hz: float = 0.35, stages: int = 6, f_lo: float = 250.0, f_hi: float = 3500.0,
           mix_amount: float = 0.5, block: int = 256) -> np.ndarray:
    """Swept allpass cascade, coefficients updated per block (state carried with scipy when present)."""
    x2, mono = _as2d(x)
    n = x2.shape[0]
    out = np.empty_like(x2)
    for ch in range(x2.shape[1]):
        s = x2[:, ch].astype(np.float64)
        y = np.empty_like(s)
        z = [np.zeros(2) for _ in range(stages)]
        for b0 in range(0, n, block):
            b1 = min(n, b0 + block)
            t = b0 / sr
            u = 0.5 * (1 + math.sin(2 * math.pi * rate_hz * t + ch * math.pi / 3))
            fc = f_lo * (f_hi / f_lo) ** u
            seg = s[b0:b1]
            for k in range(stages):
                bq = dsp.biquad("allpass", fc * (1 + 0.15 * k), sr, 0.6)
                if dsp._sps is not None:
                    seg, z[k] = dsp._sps.lfilter(bq[:3], bq[3:], seg, zi=z[k])
                else:
                    seg = dsp.sosfilt(bq[None, :], seg.astype(np.float32), sr).astype(np.float64)
            y[b0:b1] = seg
        out[:, ch] = (s + y) * 0.5
    return _back(mix(x2, out, mix_amount), mono)


def stereo_width(x: np.ndarray, width: float = 1.3) -> np.ndarray:
    x2 = dsp.to_stereo(np.asarray(x, dtype=np.float32))
    m = 0.5 * (x2[:, 0] + x2[:, 1])
    s = 0.5 * (x2[:, 0] - x2[:, 1]) * width
    return np.stack([m + s, m - s], axis=1).astype(np.float32)


def haas(x: np.ndarray, sr: int, ms: float = 12.0, side: int = 1) -> np.ndarray:
    """Pseudo-stereo from mono by delaying one side a few ms."""
    mono = dsp.to_mono(np.asarray(x, dtype=np.float32))
    d = int(ms * 1e-3 * sr)
    dl = np.concatenate([np.zeros(d, dtype=np.float32), mono])[: mono.shape[0]]
    return np.stack([mono, dl] if side > 0 else [dl, mono], axis=1)


# ── Edit-style effects ───────────────────────────────────────────────────────


def sidechain_env(n: int, sr: int, triggers: Iterable[float], depth_db: float = 8.0, attack_ms: float = 2.0,
                  release_ms: float = 140.0, curve: float = 2.0) -> np.ndarray:
    """Ducking envelope from trigger times (the kick-driven pump)."""
    g = np.ones(n, dtype=np.float32)
    floor = dsp.db_to_gain(-abs(depth_db))
    a = max(1, int(attack_ms * 1e-3 * sr))
    r = max(1, int(release_ms * 1e-3 * sr))
    shape = np.concatenate([
        np.linspace(1.0, floor, a, endpoint=False),
        floor + (1.0 - floor) * (np.linspace(0.0, 1.0, r) ** (1.0 / curve)),
    ]).astype(np.float32)
    for t in triggers:
        s = int(t * sr)
        if s >= n:
            continue
        e = min(n, s + shape.shape[0])
        g[s:e] = np.minimum(g[s:e], shape[: e - s])
    return g


def apply_env(x: np.ndarray, env: np.ndarray) -> np.ndarray:
    x2, mono = _as2d(x)
    n = min(x2.shape[0], env.shape[0])
    y = x2.copy()
    for a in range(0, n, CHUNK):
        b = min(n, a + CHUNK)
        y[a:b] *= np.asarray(env[a:b], dtype=np.float32)[:, None]
    return _back(y, mono)


def gate_pattern(x: np.ndarray, sr: int, step_s: float, pattern: str, offset_s: float = 0.0,
                 smooth_ms: float = 2.0, floor: float = 0.0) -> np.ndarray:
    """Gross-beat / trance-gate: '1' = open, '_' = closed, one char per step, looping."""
    x2, mono = _as2d(x)
    n = x2.shape[0]
    if not pattern:
        return _back(x2, mono)
    step = max(1, int(step_s * sr))
    idx = ((np.arange(n) - int(offset_s * sr)) // step) % len(pattern)
    table = np.array([1.0 if c not in "_ 0." else floor for c in pattern], dtype=np.float32)
    g = table[idx]
    k = max(1, int(smooth_ms * 1e-3 * sr))
    if k > 1:
        g = np.convolve(g, np.ones(k, dtype=np.float32) / k, mode="same")
    return _back(x2 * g[:, None], mono)


def tape_stop(x: np.ndarray, sr: int, duration_s: float = 0.6, curve: float = 1.5) -> np.ndarray:
    """Slow the tail of the clip down to a halt (pitch and speed fall together)."""
    x2, mono = _as2d(x)
    n = x2.shape[0]
    d = min(n, int(duration_s * sr))
    if d < 16:
        return _back(x2, mono)
    start = n - d
    u = np.linspace(0.0, 1.0, d)
    rate = np.clip((1.0 - u) ** curve, 0.0, 1.0)
    pos = start + np.cumsum(rate) - rate[0]
    out = x2.copy()
    for ch in range(x2.shape[1]):
        out[start:, ch] = dsp.sinc_interp(x2[:, ch], pos, rate=rate)
    fade = dsp.hann_ramp(min(d, int(0.02 * sr)))[::-1]
    out[n - fade.shape[0]:] *= fade[:, None]
    return _back(out, mono)


def reverse(x: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(x, dtype=np.float32)[::-1])


def stutter(x: np.ndarray, sr: int, slice_s: float, repeats: int, decay: float = 1.0) -> np.ndarray:
    """Repeat the first slice N times (the classic YTP/Sparta word stutter)."""
    x = np.asarray(x, dtype=np.float32)
    k = max(8, int(slice_s * sr))
    piece = dsp.declick(x[:k], sr, 1.0)
    parts = [piece * (decay ** i) for i in range(repeats)]
    return np.concatenate(parts + [x[k:]]).astype(np.float32)


def pitch_sweep(x: np.ndarray, sr: int, start_st: float, end_st: float, time_ms: float, curve: float = 2.0) -> np.ndarray:
    """Sampler pitch envelope: start transposed by start_st, glide to end_st (kick punch)."""
    x = np.asarray(x, dtype=np.float32)
    n_out = x.shape[0]
    T = max(1.0, time_ms * 1e-3 * sr)
    i = np.arange(n_out)
    u = np.clip(i / T, 0.0, 1.0)
    st = end_st + (start_st - end_st) * (1.0 - u) ** curve
    rate = np.power(2.0, st / 12.0)
    pos = np.cumsum(rate) - rate[0]
    keep = pos < x.shape[0] - 1
    y = np.zeros(n_out, dtype=np.float32)
    y[keep] = dsp.sinc_interp(x, pos[keep], rate=rate[keep])
    return y


# ── Presets / chains ─────────────────────────────────────────────────────────


def apply_chain(x: np.ndarray, sr: int, chain: Sequence[dict]) -> np.ndarray:
    """Run a list of {"fx": name, ...params} through the rack in order."""
    y = np.asarray(x, dtype=np.float32)
    for step in chain:
        params = dict(step)
        name = params.pop("fx")
        if params.pop("bypass", False):
            continue
        fn = RACK.get(name)
        if fn is None:
            raise ValueError(f"unknown effect {name!r}")
        n0 = y.shape[0]
        y = fn(y, sr, **params)
        if name in ("reverb", "delay") and y.shape[0] > n0 and not params.get("keep_tail", False):
            y = y[:n0]
    return y


def _wrap(fn):
    def inner(x, sr, **kw):
        kw.pop("keep_tail", None)
        return fn(x, sr, **kw)
    return inner


RACK: dict[str, Callable] = {
    "eq": _wrap(lambda x, sr, bands=(): eq(x, sr, bands)),
    "highpass": _wrap(lambda x, sr, freq=80.0, order=2: dsp.highpass(x, sr, freq, order)),
    "lowpass": _wrap(lambda x, sr, freq=12000.0, order=2: dsp.lowpass(x, sr, freq, order)),
    "compressor": _wrap(compressor),
    "limiter": _wrap(limiter),
    "ott": _wrap(ott),
    "transient": _wrap(transient),
    "saturate": _wrap(lambda x, sr, **kw: saturate(x, **kw)),
    "bitcrush": _wrap(bitcrush),
    "reverb": _wrap(reverb),
    "delay": _wrap(delay),
    "chorus": _wrap(chorus),
    "flanger": _wrap(flanger),
    "phaser": _wrap(phaser),
    "width": _wrap(lambda x, sr, width=1.3: stereo_width(x, width)),
    "gain": _wrap(lambda x, sr, db=0.0: gain(x, db)),
    "filter_sweep": _wrap(filter_sweep),
    "tape_stop": _wrap(tape_stop),
}
