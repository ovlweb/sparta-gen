"""Core DSP building blocks shared by analysis, sample design and the FX chain.

numpy is the only hard dependency.  When scipy is importable the IIR filters
run through ``scipy.signal.sosfilt`` (C speed); otherwise each filter is
converted to a truncated FIR and applied with FFT convolution, which keeps
the engine usable on minimal installs (e.g. Android/Termux without scipy).
"""

from __future__ import annotations

import math
import struct
import wave
from typing import Iterable, Optional, Sequence

import numpy as np

try:  # optional accelerator
    from scipy import signal as _sps  # type: ignore
except Exception:  # pragma: no cover - exercised on minimal installs
    _sps = None

HAVE_SCIPY = _sps is not None
EPS = 1e-12


# ── Level helpers ────────────────────────────────────────────────────────────


def db_to_gain(db: float | np.ndarray) -> float | np.ndarray:
    return np.power(10.0, np.asarray(db) / 20.0) if isinstance(db, np.ndarray) else 10.0 ** (db / 20.0)


def gain_to_db(g: float | np.ndarray) -> float | np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(g), EPS))


def rms(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def peak(x: np.ndarray) -> float:
    return float(np.max(np.abs(x))) if x.size else 0.0


def normalize_peak(x: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    p = peak(x)
    if p < 1e-9:
        return x.astype(np.float32, copy=True)
    return (x * (db_to_gain(peak_db) / p)).astype(np.float32)


def normalize_rms(x: np.ndarray, rms_db: float = -18.0, max_peak_db: float = -0.5) -> np.ndarray:
    r = rms(x)
    if r < 1e-9:
        return x.astype(np.float32, copy=True)
    y = x * (db_to_gain(rms_db) / r)
    p = peak(y)
    lim = db_to_gain(max_peak_db)
    if p > lim:
        y = y * (lim / p)
    return y.astype(np.float32)


def to_mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1).astype(np.float32) if x.ndim == 2 else x


def to_stereo(x: np.ndarray) -> np.ndarray:
    return np.stack([x, x], axis=1).astype(np.float32) if x.ndim == 1 else x


# ── WAV I/O (no external dependency) ─────────────────────────────────────────


def write_wav(path: str, x: np.ndarray, sr: int, bits: int = 16) -> str:
    """Write mono (n,) or stereo (n, 2) float audio as PCM16 or float32 WAV."""
    x = np.asarray(x, dtype=np.float32)
    channels = 1 if x.ndim == 1 else x.shape[1]
    if bits == 32:
        data = x.astype("<f4").tobytes()
        fmt_tag, block_align, bps = 3, 4 * channels, 32
    else:
        pcm = np.clip(x, -1.0, 1.0)
        data = (pcm * 32767.0).round().astype("<i2").tobytes()
        fmt_tag, block_align, bps = 1, 2 * channels, 16
    with open(path, "wb") as fh:
        fh.write(b"RIFF")
        fh.write(struct.pack("<I", 36 + len(data)))
        fh.write(b"WAVEfmt ")
        fh.write(struct.pack("<IHHIIHH", 16, fmt_tag, channels, sr, sr * block_align, block_align, bps))
        fh.write(b"data")
        fh.write(struct.pack("<I", len(data)))
        fh.write(data)
    return path


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """Read PCM16/PCM24/PCM32/float32 WAV; returns float32 (n,) or (n, ch) and rate."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"not a WAV file: {path}")
    pos, fmt, data = 12, None, None
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)
    if fmt is None or data is None:
        raise ValueError(f"malformed WAV: {path}")
    tag, ch, sr, _, _, bps = fmt
    if tag == 0xFFFE:  # WAVE_FORMAT_EXTENSIBLE: sub-format lives later; infer from bits
        tag = 3 if bps == 32 and len(data) % 4 == 0 and _looks_float(data) else 1
    if tag == 3:
        x = np.frombuffer(data, dtype="<f4").astype(np.float32)
    elif bps == 16:
        x = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    elif bps == 24:
        b = np.frombuffer(data[: len(data) // 3 * 3], dtype=np.uint8).reshape(-1, 3)
        i = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        i = np.where(i >= 1 << 23, i - (1 << 24), i)
        x = i.astype(np.float32) / float(1 << 23)
    elif bps == 32:
        x = np.frombuffer(data, dtype="<i4").astype(np.float32) / float(1 << 31)
    elif bps == 8:
        x = (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported WAV bit depth {bps}")
    if ch > 1:
        x = x[: len(x) // ch * ch].reshape(-1, ch)
    return x, sr


def _looks_float(data: bytes) -> bool:
    arr = np.frombuffer(data[: 4096 - 4096 % 4], dtype="<f4")
    return bool(np.all(np.isfinite(arr)) and np.max(np.abs(arr), initial=0) <= 16.0)


# ── Fades / declick (Hann, as Xleth's DeclickEnvelope) ───────────────────────


def hann_ramp(n: int) -> np.ndarray:
    """Rising half-Hann of n samples, 0 → 1 (exclusive of the final 1)."""
    if n <= 0:
        return np.ones(0, dtype=np.float32)
    t = np.arange(n, dtype=np.float64) / n
    return (0.5 - 0.5 * np.cos(np.pi * t)).astype(np.float32)


def apply_fades(x: np.ndarray, sr: int, fade_in_ms: float = 1.5, fade_out_ms: float = 1.5) -> np.ndarray:
    y = np.array(x, dtype=np.float32, copy=True)
    n = y.shape[0]
    fi = min(n // 2, int(round(fade_in_ms * 1e-3 * sr)))
    fo = min(n // 2, int(round(fade_out_ms * 1e-3 * sr)))
    if fi > 0:
        r = hann_ramp(fi)
        y[:fi] = (y[:fi].T * r).T
    if fo > 0:
        r = hann_ramp(fo)[::-1]
        y[n - fo:] = (y[n - fo:].T * r).T
    return y


def declick(x: np.ndarray, sr: int, ms: float = 1.5) -> np.ndarray:
    return apply_fades(x, sr, ms, ms)


def exp_decay_env(n: int, sr: int, decay_ms: float, floor: float = 0.0) -> np.ndarray:
    """exp(-t/τ) from 1 towards ``floor``; τ chosen so the curve hits -60 dB at decay_ms."""
    if n <= 0:
        return np.ones(0, dtype=np.float32)
    t = np.arange(n, dtype=np.float64) / sr
    tau = max(decay_ms * 1e-3, 1e-4) / math.log(1000.0)
    return (floor + (1.0 - floor) * np.exp(-t / tau)).astype(np.float32)


def adsr(n: int, sr: int, attack_ms: float = 1.0, decay_ms: float = 80.0, sustain: float = 0.7,
         release_ms: float = 20.0) -> np.ndarray:
    """Amplitude envelope for a note of n samples (release fits inside the note)."""
    env = np.full(n, sustain, dtype=np.float32)
    a = min(n, int(attack_ms * 1e-3 * sr))
    d = min(max(n - a, 0), int(decay_ms * 1e-3 * sr))
    r = min(n, int(release_ms * 1e-3 * sr))
    if a > 0:
        env[:a] = np.linspace(0.0, 1.0, a, endpoint=False, dtype=np.float32)
    if d > 0:
        env[a:a + d] = np.linspace(1.0, sustain, d, endpoint=False, dtype=np.float32)
    elif a < n:
        env[a] = 1.0
    if r > 0:
        env[n - r:] *= np.linspace(1.0, 0.0, r, dtype=np.float32)
    return env


def fit_length(x: np.ndarray, n: int) -> np.ndarray:
    """Truncate or zero-pad along axis 0 to exactly n samples."""
    if x.shape[0] >= n:
        return x[:n]
    pad = [(0, n - x.shape[0])] + [(0, 0)] * (x.ndim - 1)
    return np.pad(x, pad)


# ── Resampling ───────────────────────────────────────────────────────────────


def resample_to_length(x: np.ndarray, new_len: int) -> np.ndarray:
    """Band-limited resampling via FFT with zero padding against wrap-around."""
    x = np.asarray(x, dtype=np.float32)
    n = x.shape[0]
    if new_len <= 0 or n == 0:
        return np.zeros((max(new_len, 0),) + x.shape[1:], dtype=np.float32)
    if new_len == n:
        return x.copy()
    pad = max(64, n // 8)
    pad_new = int(round(pad * new_len / n))
    xp = np.pad(x, [(pad, pad)] + [(0, 0)] * (x.ndim - 1))
    total_in = xp.shape[0]
    total_out = new_len + 2 * pad_new
    spec = np.fft.rfft(xp, axis=0)
    m_out = total_out // 2 + 1
    if spec.shape[0] >= m_out:
        spec = spec[:m_out]
        if total_out % 2 == 0:  # Nyquist bin of the shorter signal
            spec[-1] *= 0.5
    else:
        spec = np.concatenate([spec, np.zeros((m_out - spec.shape[0],) + spec.shape[1:], dtype=spec.dtype)], axis=0)
    y = np.fft.irfft(spec, n=total_out, axis=0) * (total_out / total_in)
    return y[pad_new:pad_new + new_len].astype(np.float32)


def resample_ratio(x: np.ndarray, ratio: float) -> np.ndarray:
    """Stretch the time axis by ``ratio`` (2.0 → twice as long, an octave lower)."""
    return resample_to_length(x, max(1, int(round(x.shape[0] * ratio))))


def resample_sr(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return np.asarray(x, dtype=np.float32)
    return resample_to_length(x, int(round(x.shape[0] * sr_out / sr_in)))


def varispeed(x: np.ndarray, semitones: float) -> np.ndarray:
    """Classic sampler/tape pitch shift: pitch and speed change together."""
    if abs(semitones) < 1e-6:
        return np.asarray(x, dtype=np.float32).copy()
    return resample_ratio(x, 2.0 ** (-semitones / 12.0))


def sinc_interp(x: np.ndarray, positions: np.ndarray, rate: Optional[np.ndarray] = None,
                taps: int = 12) -> np.ndarray:
    """Evaluate mono signal x at fractional sample positions with a windowed sinc.

    ``rate`` (samples of input consumed per output sample) lowers the cutoff
    where the read head runs faster than 1, so time-varying varispeed effects
    (tape stop, pitch bends) stay alias-free.
    """
    x = np.asarray(x, dtype=np.float32)
    positions = np.asarray(positions, dtype=np.float64)
    out = np.zeros(positions.shape[0], dtype=np.float32)
    if x.size == 0 or positions.size == 0:
        return out
    half = taps // 2
    xp = np.pad(x, (half + 1, half + 1))
    ks = np.arange(-half + 1, half + 1)
    chunk = 32768
    for s in range(0, positions.shape[0], chunk):
        p = positions[s:s + chunk]
        base = np.floor(p).astype(np.int64)
        frac = p - base
        idx = base[:, None] + ks[None, :] + half + 1
        valid = (idx >= 0) & (idx < xp.shape[0])
        idx = np.clip(idx, 0, xp.shape[0] - 1)
        d = ks[None, :] - frac[:, None]
        if rate is not None:
            cut = np.minimum(1.0, 1.0 / np.maximum(np.asarray(rate[s:s + chunk], dtype=np.float64), 1e-6))[:, None]
        else:
            cut = 1.0
        w = 0.5 + 0.5 * np.cos(np.pi * d / (half + 1))
        kern = cut * np.sinc(cut * d) * w
        out[s:s + chunk] = np.sum(np.where(valid, xp[idx], 0.0) * kern, axis=1)
    return out


# ── Biquads (RBJ Audio EQ Cookbook) ──────────────────────────────────────────


def biquad(kind: str, f0: float, sr: int, q: float = 0.7071, gain_db: float = 0.0) -> np.ndarray:
    """Return one second-order section [b0, b1, b2, 1, a1, a2]."""
    f0 = float(np.clip(f0, 1.0, sr * 0.49))
    w0 = 2.0 * math.pi * f0 / sr
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2.0 * max(q, 1e-4))
    A = 10.0 ** (gain_db / 40.0)
    if kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bandpass":
        b = [alpha, 0.0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "notch":
        b = [1.0, -2 * cw, 1.0]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "allpass":
        b = [1 - alpha, -2 * cw, 1 + alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ("lowshelf", "highshelf"):
        sq = 2.0 * math.sqrt(A) * alpha
        if kind == "lowshelf":
            b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
            a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
            a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    else:
        raise ValueError(f"unknown biquad kind {kind!r}")
    a0 = a[0]
    return np.array([b[0] / a0, b[1] / a0, b[2] / a0, 1.0, a[1] / a0, a[2] / a0], dtype=np.float64)


def butter_sos(kind: str, f0: float, sr: int, order: int = 4) -> np.ndarray:
    """Butterworth low/high-pass as cascaded biquads (even orders)."""
    order = max(2, order + order % 2)
    qs = [1.0 / (2.0 * math.cos(math.pi * (2 * k + 1) / (2 * order))) for k in range(order // 2)]
    return np.stack([biquad(kind, f0, sr, q) for q in qs])


def linkwitz_riley(f0: float, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """LR4 crossover: (low sos, high sos); low + high sums to an allpass."""
    lp = biquad("lowpass", f0, sr, 0.7071)
    hp = biquad("highpass", f0, sr, 0.7071)
    return np.stack([lp, lp]), np.stack([hp, hp])


def _sos_impulse_response(sos: np.ndarray, n: int) -> np.ndarray:
    h = np.zeros(n, dtype=np.float64)
    h[0] = 1.0
    for b0, b1, b2, _a0, a1, a2 in sos:
        y = np.zeros(n, dtype=np.float64)
        x1 = x2 = y1 = y2 = 0.0
        for i in range(n):
            xi = h[i]
            yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1, y2, y1 = x1, xi, y1, yi
            y[i] = yi
        h = y
    return h


def _ir_length(sos: np.ndarray, sr: int) -> int:
    # Longest pole time constant decides how long the response rings.
    longest = 64
    for sec in sos:
        a1, a2 = sec[4], sec[5]
        roots = np.roots([1.0, a1, a2])
        r = float(np.max(np.abs(roots))) if roots.size else 0.0
        if 0.0 < r < 1.0:
            longest = max(longest, int(math.log(1e-5) / math.log(r)) + 1)
    return int(min(max(longest, 64), sr * 2))


def sosfilt(sos: np.ndarray, x: np.ndarray, sr: int = 44100) -> np.ndarray:
    """Apply cascaded biquads along axis 0."""
    sos = np.atleast_2d(np.asarray(sos, dtype=np.float64))
    x = np.asarray(x, dtype=np.float32)
    if x.shape[0] == 0:
        return x.copy()
    if _sps is not None:
        return _sps.sosfilt(sos, x, axis=0).astype(np.float32)
    h = _sos_impulse_response(sos, _ir_length(sos, sr))
    return fft_convolve(x, h.astype(np.float32))[: x.shape[0]]


def filt(x: np.ndarray, sr: int, kind: str, f0: float, q: float = 0.7071, gain_db: float = 0.0) -> np.ndarray:
    return sosfilt(biquad(kind, f0, sr, q, gain_db)[None, :], x, sr)


def highpass(x: np.ndarray, sr: int, f0: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter_sos("highpass", f0, sr, order), x, sr)


def lowpass(x: np.ndarray, sr: int, f0: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter_sos("lowpass", f0, sr, order), x, sr)


def bandpass(x: np.ndarray, sr: int, lo: float, hi: float, order: int = 2) -> np.ndarray:
    return lowpass(highpass(x, sr, lo, order), sr, hi, order)


def one_pole_smooth(x: np.ndarray, coeff: float) -> np.ndarray:
    """y[n] = coeff*y[n-1] + (1-coeff)*x[n] along axis 0."""
    x = np.asarray(x, dtype=np.float64)
    if _sps is not None:
        return _sps.lfilter([1.0 - coeff], [1.0, -coeff], x, axis=0)
    n = min(x.shape[0], max(16, int(math.log(1e-6) / math.log(max(coeff, 1e-9))) + 1))
    h = (1.0 - coeff) * np.power(coeff, np.arange(n))
    return fft_convolve(x, h)[: x.shape[0]]


# ── Convolution ──────────────────────────────────────────────────────────────


def _next_pow2(n: int) -> int:
    return 1 << max(0, int(n - 1).bit_length())


def fft_convolve(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Linear convolution along axis 0 (x may be stereo, h mono or matching)."""
    x = np.asarray(x)
    h = np.asarray(h)
    if _sps is not None:
        if x.ndim == 2 and h.ndim == 1:
            return _sps.oaconvolve(x, h[:, None], axes=0).astype(np.float32)
        return _sps.oaconvolve(x, h, axes=0).astype(np.float32)
    n_out = x.shape[0] + h.shape[0] - 1
    # Overlap-add in blocks keeps memory bounded for long signals.
    block = max(_next_pow2(h.shape[0]) * 4, 1 << 15)
    nfft = _next_pow2(block + h.shape[0] - 1)
    H = np.fft.rfft(h, nfft, axis=0)
    if x.ndim == 2 and H.ndim == 1:
        H = H[:, None]
    y = np.zeros((n_out,) + x.shape[1:], dtype=np.float64)
    for s in range(0, x.shape[0], block):
        seg = x[s:s + block]
        Y = np.fft.irfft(np.fft.rfft(seg, nfft, axis=0) * H, nfft, axis=0)
        e = min(n_out, s + nfft)
        y[s:e] += Y[: e - s]
    return y.astype(np.float32)


# ── Envelope follower (block rate, then interpolated) ────────────────────────


def envelope(
    x: np.ndarray,
    sr: int,
    attack_ms: float,
    release_ms: float,
    mode: str = "rms",
    block: int = 32,
) -> np.ndarray:
    """Attack/release envelope of |x| (peak) or sqrt(mean x^2) (rms), per sample.

    The recursion runs at block rate (sr / block) so the Python loop stays
    short; the result is linearly interpolated back to sample rate.
    """
    mono = np.abs(x).max(axis=1) if (x.ndim == 2 and mode == "peak") else (
        np.sqrt(np.mean(np.square(x), axis=1)) if x.ndim == 2 else np.abs(x))
    n = mono.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    nb = (n + block - 1) // block
    padded = np.pad(mono, (0, nb * block - n))
    blocks = padded.reshape(nb, block)
    level = blocks.max(axis=1) if mode == "peak" else np.sqrt(np.mean(np.square(blocks, dtype=np.float64), axis=1))
    brate = sr / block
    ca = math.exp(-1.0 / max(attack_ms * 1e-3 * brate, 1e-6))
    cr = math.exp(-1.0 / max(release_ms * 1e-3 * brate, 1e-6))
    env = np.empty(nb, dtype=np.float64)
    e = 0.0
    lv = level.tolist()
    for i in range(nb):
        v = lv[i]
        c = ca if v > e else cr
        e = c * e + (1.0 - c) * v
        env[i] = e
    centers = np.arange(nb) * block + block / 2.0
    return np.interp(np.arange(n), centers, env).astype(np.float32)


def running_max(x: np.ndarray, w: int) -> np.ndarray:
    """max(x[i : i + w]) for every i, in O(n) (van Herk / Gil-Werman)."""
    x = np.asarray(x)
    n = x.shape[0]
    if w <= 1 or n == 0:
        return x.copy()
    nb = (n + w - 1) // w + 1
    pad = np.full(nb * w, -np.inf, dtype=np.float64)
    pad[:n] = x
    blocks = pad.reshape(nb, w)
    prefix = np.maximum.accumulate(blocks, axis=1).reshape(-1)
    suffix = np.maximum.accumulate(blocks[:, ::-1], axis=1)[:, ::-1].reshape(-1)
    idx = np.arange(n)
    return np.maximum(suffix[idx], prefix[np.minimum(idx + w - 1, nb * w - 1)]).astype(x.dtype, copy=False)


def active_range(x: np.ndarray, thresh: float = 1e-6) -> Optional[tuple[int, int]]:
    """First and last sample index where |x| exceeds thresh (None if silent)."""
    mag = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    nz = np.flatnonzero(mag > thresh)
    if nz.size == 0:
        return None
    return int(nz[0]), int(nz[-1]) + 1


def block_features(x: np.ndarray, frame: int, hop: int) -> np.ndarray:
    """Frame a mono signal into (n_frames, frame) views without copying."""
    x = np.asarray(x, dtype=np.float32)
    if x.shape[0] < frame:
        x = np.pad(x, (0, frame - x.shape[0]))
    n = 1 + (x.shape[0] - frame) // hop
    strides = (x.strides[0] * hop, x.strides[0])
    return np.lib.stride_tricks.as_strided(x, shape=(n, frame), strides=strides, writeable=False)


# ── Loudness (ITU-R BS.1770-4) ───────────────────────────────────────────────


def _k_weighting_sos(sr: int) -> np.ndarray:
    """K-weighting (pre-filter shelf + RLB high-pass), bilinear-derived for any rate."""
    # Stage 1: high shelf, +4 dB above ~1.5 kHz (BS.1770 analog prototype).
    f0, gain_db, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10.0 ** (gain_db / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / q + K * K
    s1 = [(Vh + Vb * K / q + K * K) / a0, 2.0 * (K * K - Vh) / a0, (Vh - Vb * K / q + K * K) / a0,
          1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / q + K * K) / a0]
    # Stage 2: RLB high-pass at ~38 Hz.
    f0, q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    a0 = 1.0 + K / q + K * K
    s2 = [1.0, -2.0, 1.0, 1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / q + K * K) / a0]
    return np.array([s1, s2], dtype=np.float64)


def loudness_lufs(x: np.ndarray, sr: int) -> float:
    """Integrated loudness in LUFS (gated). Returns -70 for silence."""
    x = to_stereo(np.asarray(x, dtype=np.float32))
    if x.shape[0] < int(0.4 * sr):
        x = np.pad(x, ((0, int(0.4 * sr) - x.shape[0]), (0, 0)))
    xk = sosfilt(_k_weighting_sos(sr), x, sr).astype(np.float64)
    power = np.sum(np.square(xk), axis=1)
    win, hop = int(0.4 * sr), int(0.1 * sr)
    csum = np.concatenate([[0.0], np.cumsum(power)])
    starts = np.arange(0, power.shape[0] - win + 1, hop)
    ms = (csum[starts + win] - csum[starts]) / win
    with np.errstate(divide="ignore"):
        lk = -0.691 + 10.0 * np.log10(np.maximum(ms, 1e-20))
    gated = ms[lk > -70.0]
    if gated.size == 0:
        return -70.0
    rel = -0.691 + 10.0 * math.log10(np.mean(gated)) - 10.0
    final = ms[(lk > -70.0) & (lk > rel)]
    if final.size == 0:
        return -70.0
    return float(-0.691 + 10.0 * math.log10(np.mean(final)))


def true_peak_db(x: np.ndarray) -> float:
    """Approximate true peak via 4x FFT oversampling around the loudest region."""
    x = to_stereo(np.asarray(x, dtype=np.float32))
    if x.shape[0] == 0:
        return -200.0
    idx = int(np.argmax(np.max(np.abs(x), axis=1)))
    lo, hi = max(0, idx - 2048), min(x.shape[0], idx + 2048)
    seg = x[lo:hi]
    up = resample_to_length(seg, seg.shape[0] * 4)
    return float(gain_to_db(max(peak(up), peak(seg))))


# ── Misc ─────────────────────────────────────────────────────────────────────


def mix_into(dest: np.ndarray, src: np.ndarray, start: int, gain: float = 1.0) -> None:
    """Add src into dest at sample offset start (clipped to dest bounds)."""
    if start >= dest.shape[0] or src.shape[0] == 0:
        return
    s0 = max(0, start)
    off = s0 - start
    e = min(dest.shape[0], start + src.shape[0])
    if e <= s0:
        return
    seg = src[off:off + (e - s0)]
    if dest.ndim == 2 and seg.ndim == 1:
        dest[s0:e] += (seg * gain)[:, None]
    else:
        dest[s0:e] += seg * gain


def pan_gains(pan: float) -> tuple[float, float]:
    """Constant-power pan law; pan in [-1, 1]."""
    ang = (np.clip(pan, -1.0, 1.0) + 1.0) * math.pi / 4.0
    return math.cos(ang), math.sin(ang)


def crossfade_concat(parts: Sequence[np.ndarray], sr: int, xfade_ms: float = 5.0) -> np.ndarray:
    parts = [p for p in parts if p.shape[0]]
    if not parts:
        return np.zeros(0, dtype=np.float32)
    out = parts[0].astype(np.float32)
    n = int(xfade_ms * 1e-3 * sr)
    for p in parts[1:]:
        k = min(n, out.shape[0], p.shape[0])
        if k > 0:
            r = hann_ramp(k)
            mixed = out[-k:] * r[::-1] + p[:k] * r
            out = np.concatenate([out[:-k], mixed, p[k:]])
        else:
            out = np.concatenate([out, p])
    return out.astype(np.float32)


def chunks(n: int, size: int) -> Iterable[tuple[int, int]]:
    for s in range(0, n, size):
        yield s, min(n, s + size)
