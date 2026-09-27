"""Thin, dependency-free wrapper around the ffmpeg command line.

All media I/O goes through here: probing, decoding audio to numpy, reading
video frames for the compositor, piping rendered frames back into an encoder
and cutting sample clips.  ffprobe is optional — builds such as the one
shipped by ``imageio-ffmpeg`` only contain ``ffmpeg``, so probing falls back
to parsing ``ffmpeg -i`` output.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Callable, Optional

import numpy as np

# Hide the console window that subprocess pops up on Windows GUI launches.
_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class FFmpegError(RuntimeError):
    """ffmpeg is missing or a command failed."""


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Locate ffmpeg: $SPARTAGEN_FFMPEG, a copy bundled next to the app, PATH, imageio-ffmpeg."""
    env = os.environ.get("SPARTAGEN_FFMPEG")
    if env and os.path.isfile(env):
        return env
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    for base in _bundle_dirs():
        cand = os.path.join(base, exe)
        if os.path.isfile(cand):
            return cand
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # optional pip package that ships a static ffmpeg per platform
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise FFmpegError(
        "ffmpeg was not found. Install it (https://ffmpeg.org/download.html, "
        "`apt install ffmpeg`, `brew install ffmpeg`, `pkg install ffmpeg` on Termux) "
        "or `pip install imageio-ffmpeg`, or set SPARTAGEN_FFMPEG=/path/to/ffmpeg."
    )


@lru_cache(maxsize=1)
def ffprobe_path() -> Optional[str]:
    env = os.environ.get("SPARTAGEN_FFPROBE")
    if env and os.path.isfile(env):
        return env
    exe = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    try:
        sibling = os.path.join(os.path.dirname(ffmpeg_path()), exe)
        if os.path.isfile(sibling):
            return sibling
    except FFmpegError:
        pass
    return shutil.which("ffprobe")


def _bundle_dirs() -> list[str]:
    """Directories a frozen (PyInstaller) build may carry ffmpeg in."""
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs += [meipass, os.path.join(meipass, "bin")]
    if getattr(sys, "frozen", False):
        here = os.path.dirname(sys.executable)
        dirs += [here, os.path.join(here, "bin")]
    return dirs


def available() -> bool:
    try:
        ffmpeg_path()
        return True
    except FFmpegError:
        return False


def version() -> str:
    out = run([ffmpeg_path(), "-hide_banner", "-version"], capture=True)
    return out.splitlines()[0] if out else "unknown"


def run(cmd: list[str], capture: bool = False, input_bytes: Optional[bytes] = None) -> str:
    """Run a command; raise FFmpegError with the tail of stderr on failure."""
    proc = subprocess.run(
        cmd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_CREATIONFLAGS,
    )
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-12:]
        raise FFmpegError(f"command failed ({proc.returncode}): {' '.join(cmd[:6])} ...\n" + "\n".join(tail))
    return proc.stdout.decode("utf-8", "replace") if capture else ""


# ── Probing ──────────────────────────────────────────────────────────────────


@dataclass
class MediaInfo:
    path: str
    duration: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    width: int = 0
    height: int = 0
    fps: float = 0.0
    audio_rate: int = 0
    audio_channels: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def probe(path: str) -> MediaInfo:
    if not os.path.isfile(path):
        raise FFmpegError(f"file not found: {path}")
    fp = ffprobe_path()
    if fp:
        try:
            return _probe_ffprobe(fp, path)
        except (FFmpegError, ValueError, KeyError):
            pass
    return _probe_ffmpeg(path)


def _parse_rate(text: str) -> float:
    if not text or text in ("0/0", "N/A"):
        return 0.0
    if "/" in text:
        num, den = text.split("/", 1)
        return float(num) / float(den) if float(den) else 0.0
    return float(text)


def _probe_ffprobe(fp: str, path: str) -> MediaInfo:
    out = run(
        [fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture=True,
    )
    data = json.loads(out)
    info = MediaInfo(path=path)
    info.duration = float(data.get("format", {}).get("duration") or 0.0)
    for st in data.get("streams", []):
        kind = st.get("codec_type")
        if kind == "video" and not info.has_video:
            # Cover art in audio files is a "video" stream with a single frame.
            if st.get("disposition", {}).get("attached_pic"):
                continue
            info.has_video = True
            info.width = int(st.get("width") or 0)
            info.height = int(st.get("height") or 0)
            info.fps = _parse_rate(st.get("avg_frame_rate") or "") or _parse_rate(st.get("r_frame_rate") or "")
            if not info.duration:
                info.duration = float(st.get("duration") or 0.0)
        elif kind == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_rate = int(st.get("sample_rate") or 0)
            info.audio_channels = int(st.get("channels") or 0)
            if not info.duration:
                info.duration = float(st.get("duration") or 0.0)
    return info


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")
_VID_RE = re.compile(r"Stream #.*?Video:.*?(\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"([\d.]+)\s*(?:fps|tbr)")
_AUD_RE = re.compile(r"Stream #.*?Audio:.*?(\d+)\s*Hz,\s*([^,]+)")


def _probe_ffmpeg(path: str) -> MediaInfo:
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_CREATIONFLAGS,
    )
    text = proc.stderr.decode("utf-8", "replace")
    info = MediaInfo(path=path)
    m = _DUR_RE.search(text)
    if m:
        info.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in text.splitlines():
        if "Video:" in line and "attached pic" not in line and not info.has_video:
            vm = _VID_RE.search(line)
            if vm:
                info.has_video = True
                info.width, info.height = int(vm.group(1)), int(vm.group(2))
                fm = _FPS_RE.search(line)
                info.fps = float(fm.group(1)) if fm else 25.0
        if "Audio:" in line and not info.has_audio:
            am = _AUD_RE.search(line)
            if am:
                info.has_audio = True
                info.audio_rate = int(am.group(1))
                layout = am.group(2).strip()
                info.audio_channels = 1 if layout.startswith("mono") else 2
    if not info.has_audio and not info.has_video:
        raise FFmpegError(f"no audio/video streams found in {path}")
    return info


# ── Audio ────────────────────────────────────────────────────────────────────


def decode_audio(
    path: str,
    sr: int = 44100,
    mono: bool = True,
    start: Optional[float] = None,
    duration: Optional[float] = None,
) -> np.ndarray:
    """Decode (a part of) any media file to float32 PCM: shape (n,) or (n, 2)."""
    channels = 1 if mono else 2
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start is not None and start > 0:
        cmd += ["-ss", f"{start:.6f}"]
    cmd += ["-i", path]
    if duration is not None:
        cmd += ["-t", f"{max(duration, 0.001):.6f}"]
    cmd += ["-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_CREATIONFLAGS)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise FFmpegError("audio decode failed:\n" + "\n".join(tail))
    data = np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)
    if channels == 2:
        data = data[: len(data) // 2 * 2].reshape(-1, 2)
    return data


# ── Video frames ─────────────────────────────────────────────────────────────


def _scale_filter(width: int, height: int, fit: str) -> str:
    if fit == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=bilinear,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    if fit == "stretch":
        return f"scale={width}:{height}:flags=bilinear"
    # cover: fill the cell, crop the overflow (what grid remixes do)
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=bilinear,"
        f"crop={width}:{height}"
    )


def read_frames(
    path: str,
    start: float,
    duration: float,
    fps: float,
    width: int,
    height: int,
    fit: str = "cover",
) -> np.ndarray:
    """Decode a time range as RGB frames at a fixed rate: (n, h, w, 3) uint8."""
    n_expected = max(1, int(round(duration * fps)))
    vf = f"fps={fps:.6f}," + _scale_filter(width, height, fit)
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{max(start, 0.0):.6f}", "-i", path,
        "-t", f"{max(duration, 1.0 / fps):.6f}",
        "-an", "-vf", vf, "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_CREATIONFLAGS)
    frame_bytes = width * height * 3
    buf = proc.stdout
    n = len(buf) // frame_bytes
    if n == 0:
        # Seeking past the last frame (or an audio-only source): try one still.
        if proc.returncode == 0 and start > 0.05:
            return read_frames(path, max(0.0, start - 0.25), 0.25 + 1.0 / fps, fps, width, height, fit)[-1:]
        return np.zeros((1, height, width, 3), dtype=np.uint8)
    frames = np.frombuffer(buf[: n * frame_bytes], dtype=np.uint8).reshape(n, height, width, 3)
    if n > n_expected:
        frames = frames[:n_expected]
    return frames


def still_frame(path: str, t: float, width: int, height: int, fit: str = "cover") -> np.ndarray:
    return read_frames(path, t, 1.0 / 25.0, 25.0, width, height, fit)[0]


def save_jpeg(path_in: str, t: float, out_path: str, width: int = 320, height: int = 180) -> str:
    run([
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", f"{max(t, 0):.4f}", "-i", path_in, "-frames:v", "1",
        "-vf", _scale_filter(width, height, "cover"), "-q:v", "4", out_path,
    ])
    return out_path


class VideoWriter:
    """Pipe raw RGB frames into an H.264 encoder, optionally muxing an audio file."""

    def __init__(
        self,
        out_path: str,
        width: int,
        height: int,
        fps: float,
        audio_path: Optional[str] = None,
        crf: int = 20,
        preset: str = "veryfast",
        audio_bitrate: str = "256k",
    ):
        self.width, self.height = width, height
        self._frame_bytes = width * height * 3
        cmd = [
            ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", f"{fps:.6f}",
            "-i", "pipe:0",
        ]
        if audio_path:
            cmd += ["-i", audio_path]
        cmd += [
            "-map", "0:v:0",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ]
        if audio_path:
            cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", audio_bitrate, "-shortest"]
        cmd.append(out_path)
        self._stderr_chunks: list[bytes] = []
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=_CREATIONFLAGS,
        )
        # Drain stderr on a thread so a chatty encoder can never dead-lock the pipe.
        self._stderr_thread = threading.Thread(target=self._drain, daemon=True)
        self._stderr_thread.start()

    def _drain(self) -> None:
        assert self._proc.stderr is not None
        for chunk in iter(lambda: self._proc.stderr.read(4096), b""):
            self._stderr_chunks.append(chunk)

    def write(self, frame: np.ndarray) -> None:
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        data = np.ascontiguousarray(frame).tobytes()
        if len(data) != self._frame_bytes:
            raise ValueError(f"frame has wrong size {frame.shape}, expected {self.height}x{self.width}x3")
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.write(data)
        except BrokenPipeError as exc:
            self.close()
            raise FFmpegError("encoder exited early") from exc

    def close(self) -> None:
        if self._proc.stdin and not self._proc.stdin.closed:
            try:
                self._proc.stdin.close()
            except BrokenPipeError:
                pass
        code = self._proc.wait()
        self._stderr_thread.join(timeout=5)
        if code != 0:
            err = b"".join(self._stderr_chunks).decode("utf-8", "replace").strip().splitlines()[-8:]
            raise FFmpegError("video encode failed:\n" + "\n".join(err))

    def __enter__(self) -> "VideoWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.close()
        else:
            try:
                self.close()
            except FFmpegError:
                pass


def cut_clip(
    src: str,
    start: float,
    duration: float,
    out_path: str,
    audio_wav: Optional[str] = None,
    width: int = 0,
    height: int = 0,
) -> str:
    """Cut a sample's video out of the source (re-encoded so cuts are frame exact).

    When ``audio_wav`` is given (the processed sample, e.g. tuned to D) it
    replaces the source audio, so the clip is ready to drop into an editor.
    """
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", f"{max(start, 0):.6f}", "-t", f"{max(duration, 0.02):.6f}", "-i", src,
    ]
    if audio_wav:
        cmd += ["-i", audio_wav, "-map", "0:v:0?", "-map", "1:a:0"]
    vf = []
    if width and height:
        vf.append(_scale_filter(width, height, "contain"))
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k",
    ]
    if audio_wav:
        cmd += ["-shortest"]
    cmd.append(out_path)
    run(cmd)
    return out_path


def encode_audio(wav_path: str, out_path: str) -> str:
    ext = os.path.splitext(out_path)[1].lower()
    codec = {".mp3": ["-c:a", "libmp3lame", "-q:a", "2"], ".m4a": ["-c:a", "aac", "-b:a", "256k"],
             ".ogg": ["-c:a", "libopus", "-b:a", "192k"], ".opus": ["-c:a", "libopus", "-b:a", "192k"],
             ".flac": ["-c:a", "flac"], ".wav": ["-c:a", "pcm_s16le"]}.get(ext, ["-c:a", "aac", "-b:a", "256k"])
    run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", wav_path, *codec, out_path])
    return out_path


def make_test_card(out_path: str, duration: float, audio_wav: Optional[str] = None,
                   size: str = "640x360", fps: int = 30) -> str:
    """Render a video from an audio file over ffmpeg's animated test pattern (used by tests/demo)."""
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={duration:.3f}"]
    if audio_wav:
        cmd += ["-i", audio_wav, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", out_path]
    run(cmd)
    return out_path


ProgressCallback = Callable[[float, str], None]
