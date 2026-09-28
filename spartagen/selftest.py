"""Self-test of an installed SpartaGen: a synthetic test video goes through the one-click remix — what
the app's ⚡ button does — and is saved like the app's "Save video…" and "Save audio…" do, over the engine's
API as the app uses it (a secret token, local paths), with the ffmpeg the engine found (the bundled one in
the desktop apps).  Used by CI on every built app; `spartagen selftest` or `spartagen-engine --selftest`
runs it.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import threading
import time
import urllib.request
import wave
from typing import Callable, Optional

import numpy as np

from . import __version__
from . import ffmpeg as ff

SR = 44100


def _tone(f0: float, dur: float, formant: float = 700.0, vibrato: float = 15.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    ph = 2 * np.pi * np.cumsum(f0 * 2 ** (vibrato * np.sin(2 * np.pi * 5 * t) / 1200)) / SR
    x = sum((math.exp(-((k * f0 - formant) / 450) ** 2) + 0.3 / k) * np.sin(k * ph)
            for k in range(1, 30) if k * f0 < SR / 2.2)
    env = np.minimum(1, np.minimum(t / 0.01, (dur - t) / 0.02))
    return 0.3 * x / np.max(np.abs(x)) * env


def _burst(dur: float, decay: float, seed: int, low: bool = False) -> np.ndarray:
    x = np.random.RandomState(seed).randn(int(dur * SR))
    if low:
        x = np.convolve(x, np.ones(64) / 64, mode="same") * 4
    return 0.5 * x * np.exp(-np.arange(x.size) / SR / decay)


def make_test_source(path: str) -> str:
    """An 11-second test video: held sung-like notes, syllables, thumps, bangs and hiss (the kinds of
    material the engine cuts from a real source) on ffmpeg's test card."""
    gap = np.zeros(int(0.25 * SR))
    parts = []
    for f in (196.0, 233.1, 174.6, 220.0, 261.6, 293.7):
        parts += [_tone(f, 0.45), gap]
    for i in range(6):
        parts += [_tone(150 + 12 * i, 0.18, 500 + 90 * i), np.zeros(int(0.06 * SR))]
    for i in range(4):
        parts += [_burst(0.25, 0.06, i, low=True), gap, _burst(0.2, 0.07, 10 + i), gap]
    hiss = np.diff(np.random.RandomState(5).randn(int(0.3 * SR) + 1)) * 0.1
    parts += [hiss, gap] * 3
    y = np.clip(np.concatenate(parts), -1, 1)
    wav = path + ".wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    ff.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            f"testsrc2=size=640x360:rate=25:duration={y.size / SR:.3f}", "-i", wav,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path])
    os.remove(wav)
    return path


def run(out_json: Optional[str] = None, quality: str = "preview",
        log: Callable[[str], None] = print) -> dict:
    """Source in, remix out, through the app's server.  Returns (and writes to ``out_json``) a report;
    ``report["ok"]`` says whether it all worked."""
    from .gui.server import make_server
    t0 = time.time()
    root = tempfile.mkdtemp(prefix="spartagen-selftest-")
    report: dict = {"ok": False, "version": __version__, "quality": quality}
    httpd = None
    try:
        report["ffmpeg"] = ff.ffmpeg_path()
        report["ffmpeg_version"] = ff.version()
        log(f"SpartaGen {__version__} self-test · {report['ffmpeg_version']}")
        src = make_test_source(os.path.join(root, "test-source.mp4"))
        token = "selftest-" + os.urandom(8).hex()
        httpd, url = make_server("127.0.0.1", 0, os.path.join(root, "home"), token=token, web_ui=False)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = url.rstrip("/")

        def call(path: str, body=None) -> dict:
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET",
                                         headers={"X-Sparta-Token": token})
            if body is not None:
                req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())

        call("/api/source/path", {"path": src})
        job = call("/api/auto", {"quality": quality})
        last = ""
        while job["status"] == "running":
            time.sleep(0.5)
            job = call(f"/api/job/{job['id']}")
            if job["message"] != last:
                last = job["message"]
                log(f"  {job['progress'] * 100:5.1f}%  {last}")
        if job["status"] != "done":
            raise RuntimeError(job.get("error") or "the one-click remix failed")
        res = job["result"]
        info = ff.probe(res["file"])
        # "Save video…" and "Save audio… → MP3": copies where the user chose, the MP3 encoded on the way
        saved = os.path.join(root, "chosen folder", "My remix.mp4")
        mp3 = os.path.join(root, "chosen folder", "My remix.mp3")
        call("/api/export/file", {"file": res["file"], "dest": saved})
        call("/api/export/file", {"file": res["audio"], "dest": mp3, "audio_format": "mp3"})
        saved_ok = os.path.getsize(saved) == os.path.getsize(res["file"]) and ff.probe(mp3).duration > 20
        report.update(ok=info.duration > 20 and res["events"] > 100 and saved_ok, file=res["file"],
                      events=res["events"], duration=round(info.duration, 2), lufs=res["lufs"],
                      has_video=info.has_video, saved=saved_ok)
        samples = call("/api/samples")["samples"]
        report["samples"] = sorted(s["id"] for s in samples)
        log(f"remix: {report['duration']} s, {res['events']} notes, {res['lufs']} LUFS, "
            f"{len(samples)} samples cut, saved as MP4 and MP3: {saved_ok} — {'OK' if report['ok'] else 'NOT OK'}")
    except Exception as exc:                      # the report says what broke
        report["error"] = f"{exc.__class__.__name__}: {exc}"
        log("self-test failed: " + report["error"])
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        report["seconds"] = round(time.time() - t0, 1)
        if out_json:
            with open(out_json, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=1)
        shutil.rmtree(root, ignore_errors=True)
    return report


if __name__ == "__main__":
    import sys
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else None)["ok"] else 1)
