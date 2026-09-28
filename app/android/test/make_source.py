"""A short synthetic test video for the emulator run: held sung-like notes, syllables, thumps, bangs and
hiss (the same kinds of material the engine cuts from a real source), on ffmpeg's test card."""

import math
import subprocess
import sys
import wave

import numpy as np

SR = 44100


def tone(f0: float, dur: float, formant: float = 700.0, vibrato: float = 15.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    ph = 2 * np.pi * np.cumsum(f0 * 2 ** (vibrato * np.sin(2 * np.pi * 5 * t) / 1200)) / SR
    x = sum((math.exp(-((k * f0 - formant) / 450) ** 2) + 0.3 / k) * np.sin(k * ph)
            for k in range(1, 30) if k * f0 < SR / 2.2)
    env = np.minimum(1, np.minimum(t / 0.01, (dur - t) / 0.02))
    return 0.3 * x / np.max(np.abs(x)) * env


def burst(dur: float, decay: float, seed: int, low: bool = False) -> np.ndarray:
    x = np.random.RandomState(seed).randn(int(dur * SR))
    if low:
        x = np.convolve(x, np.ones(64) / 64, mode="same") * 4
    return 0.5 * x * np.exp(-np.arange(x.size) / SR / decay)


def main(out: str) -> None:
    gap = np.zeros(int(0.25 * SR))
    parts = []
    for f in (196.0, 233.1, 174.6, 220.0, 261.6, 293.7):
        parts += [tone(f, 0.45), gap]
    for i in range(6):
        parts += [tone(150 + 12 * i, 0.18, 500 + 90 * i), np.zeros(int(0.06 * SR))]
    for i in range(4):
        parts += [burst(0.25, 0.06, i, low=True), gap, burst(0.2, 0.07, 10 + i), gap]
    hiss = np.diff(np.random.RandomState(5).randn(int(0.3 * SR) + 1)) * 0.1
    parts += [hiss, gap] * 3
    y = np.clip(np.concatenate(parts), -1, 1)
    wav = out + ".wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    dur = y.size / SR
    subprocess.check_call(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                           f"testsrc2=size=640x360:rate=25:duration={dur:.3f}", "-i", wav,
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "source.mp4")
