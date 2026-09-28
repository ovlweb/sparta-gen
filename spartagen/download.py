"""Fetch a source video from a URL (YouTube and anything else yt-dlp supports)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Callable, Optional

from . import ffmpeg as ff

Progress = Optional[Callable[[float, str], None]]


class DownloadError(RuntimeError):
    pass


def is_url(text: str) -> bool:
    t = text.strip().lower()
    return t.startswith("http://") or t.startswith("https://") or t.startswith("www.")


def available() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return shutil.which("yt-dlp") is not None


def download(url: str, out_dir: str, progress: Progress = None, max_height: int = 720) -> str:
    """Download ``url`` as an mp4 into ``out_dir`` and return the file path."""
    os.makedirs(out_dir, exist_ok=True)
    fmt = (f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/"
           f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b")
    template = os.path.join(out_dir, "%(title).80s [%(id)s].%(ext)s")
    try:
        ffmpeg_dir = None if ff.is_function() else os.path.dirname(ff.ffmpeg_path())
    except ff.FFmpegError:
        ffmpeg_dir = None
    if ff.is_function():      # iOS: yt-dlp cannot run ffmpeg to merge a video and an audio stream — one file
        fmt = f"b[height<={max_height}][ext=mp4]/b[height<={max_height}]/b"
    try:
        import yt_dlp  # type: ignore
    except Exception:
        yt_dlp = None

    if yt_dlp is not None:
        def hook(d: dict) -> None:
            if not progress:
                return
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                progress(min(0.99, done / total) if total else 0.0, "downloading")
            elif d.get("status") == "finished":
                progress(0.99, "merging")

        opts = {
            "format": fmt, "outtmpl": template, "merge_output_format": "mp4", "noplaylist": True,
            "quiet": True, "no_warnings": True, "progress_hooks": [hook], "restrictfilenames": True,
        }
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = ydl.prepare_filename(info)
        except Exception as exc:  # yt-dlp raises many types
            raise DownloadError(f"download failed: {exc}") from exc
        base, _ = os.path.splitext(path)
        for cand in (base + ".mp4", path, base + ".mkv", base + ".webm"):
            if os.path.isfile(cand):
                if progress:
                    progress(1.0, "downloaded")
                return cand
        raise DownloadError("download finished but the file was not found")

    exe = shutil.which("yt-dlp")
    if not exe:
        raise DownloadError("yt-dlp is not installed. Run `pip install yt-dlp` (or download the video manually).")
    cmd = [exe, "-f", fmt, "--merge-output-format", "mp4", "--no-playlist", "--restrict-filenames",
           "-o", template, "--print", "after_move:filepath", url]
    if ffmpeg_dir:
        cmd[1:1] = ["--ffmpeg-location", ffmpeg_dir]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise DownloadError(proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or "yt-dlp failed")
    lines = [ln for ln in proc.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    if not lines or not os.path.isfile(lines[-1]):
        raise DownloadError("yt-dlp did not report the downloaded file")
    return lines[-1]
