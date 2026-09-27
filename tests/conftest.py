import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR = 44100


def harmonic_tone(f0: float, dur: float, sr: int = SR, vibrato_cents: float = 0.0, formant: float = 700.0) -> np.ndarray:
    """A voice-like test tone (harmonics under a formant bump) — only used to test the DSP."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    f_inst = f0 * 2 ** ((vibrato_cents * np.sin(2 * np.pi * 5.0 * t)) / 1200.0)
    ph = 2 * np.pi * np.cumsum(f_inst) / sr
    x = np.zeros(n)
    for k in range(1, 30):
        if k * f0 > sr / 2.2:
            break
        amp = math.exp(-((k * f0 - formant) / 450.0) ** 2) + 0.3 / k
        x += amp * np.sin(k * ph)
    x *= 0.3 / np.max(np.abs(x))
    env = np.minimum(1.0, np.minimum(t / 0.01, (dur - t) / 0.02))
    return (x * env).astype(np.float32)


def noise_burst(dur: float, sr: int = SR, decay_ms: float = 80.0, seed: int = 0, lowpass: float = 0.0) -> np.ndarray:
    rng = np.random.RandomState(seed)
    n = int(dur * sr)
    x = rng.randn(n)
    if lowpass:
        from spartagen.audio import dsp
        x = dsp.lowpass(x.astype(np.float32), sr, lowpass, order=4)
    t = np.arange(n) / sr
    return (0.5 * x * np.exp(-t / (decay_ms / 1000.0))).astype(np.float32)


@pytest.fixture(scope="session")
def synthetic_source(tmp_path_factory) -> str:
    """A short test video: sung-like notes, speech-like syllables, thumps, hiss (synthetic, for tests only)."""
    from spartagen import ffmpeg as ff
    from spartagen.audio import dsp
    if not ff.available():
        pytest.skip("ffmpeg not available")
    parts = []
    silence = np.zeros(int(0.25 * SR), dtype=np.float32)
    for f in (196.0, 233.1, 174.6, 220.0):                 # held "vowels"
        parts += [harmonic_tone(f, 0.45, vibrato_cents=15.0), silence]
    for i in range(6):                                     # "syllables"
        parts += [harmonic_tone(150.0 + 12 * i, 0.18, formant=500 + 90 * i), np.zeros(int(0.06 * SR), np.float32)]
    parts.append(silence)
    for i in range(4):                                     # thumps (kick material)
        parts += [noise_burst(0.25, decay_ms=60, seed=i, lowpass=150.0) * 3.0, silence]
    for i in range(4):                                     # snare-like bangs
        parts += [noise_burst(0.2, decay_ms=70, seed=10 + i), silence]
    hiss = dsp.highpass(np.random.RandomState(5).randn(int(0.3 * SR)).astype(np.float32) * 0.2, SR, 5000.0, 4)
    for _ in range(3):                                     # sibilants
        parts += [hiss, silence]
    audio = np.concatenate(parts)
    d = tmp_path_factory.mktemp("media")
    wav = str(d / "src.wav")
    dsp.write_wav(wav, audio, SR)
    mp4 = str(d / "src.mp4")
    ff.make_test_card(mp4, len(audio) / SR, wav, size="320x180", fps=25)
    return mp4
