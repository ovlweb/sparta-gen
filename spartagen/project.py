"""Project state (JSON) and the analyse → sample → arrange → render pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

import numpy as np

from . import SAMPLE_RATE, __version__
from . import ffmpeg as ff
from .arrangement import Arrangement, build_arrangement, build_from_base, compile_events, VARIANTS
from .audio import dsp
from .audio.analysis import Analysis, analyze
from .render_audio import MixConfig, muted_stems, render_mix
from .render_video import VideoConfig, render_video
from .samples import SampleBank, SampleConfig, build_bank

Progress = Optional[Callable[[float, str], None]]

QUALITIES = ("audio", "preview", "720p", "1080p")


def default_workspace() -> str:
    env = os.environ.get("SPARTAGEN_HOME")
    if env:
        return env
    home = os.path.expanduser("~")
    return os.path.join(home, "SpartaGen")


@dataclass
class Project:
    name: str = "Untitled Sparta Remix"
    source_path: str = ""
    source_info: dict = field(default_factory=dict)
    workspace: str = ""
    analysis: Optional[dict] = None
    samples: dict = field(default_factory=lambda: asdict(SampleConfig()))
    variant: str = "unextended"
    arrangement: Optional[dict] = None       # full Arrangement.to_dict() once built/edited
    options: dict = field(default_factory=dict)  # bpm, key, progression, pitching, polish, minor …
    mix: dict = field(default_factory=dict)
    base: Optional[dict] = None              # BaseMap of the Sparta base (tempo, bars, sections …)
    video: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    version: str = __version__

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Project":
        p = Project()
        for k, v in d.items():
            if hasattr(p, k):
                setattr(p, k, v)
        return p

    def save(self, path: Optional[str] = None) -> str:
        path = path or os.path.join(self.workspace, "project.spartagen.json")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1)
        os.replace(tmp, path)
        return path

    @staticmethod
    def load(path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as fh:
            return Project.from_dict(json.load(fh))


def _file_key(path: str) -> str:
    st = os.stat(path)
    h = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()
    return h[:12]


class Session:
    """Holds a project plus its heavy in-memory state (audio, sample bank)."""

    def __init__(self, project: Optional[Project] = None, workspace: Optional[str] = None):
        self.project = project or Project()
        if not self.project.workspace:
            self.project.workspace = workspace or os.path.join(default_workspace(), time.strftime("remix-%Y%m%d-%H%M%S"))
        os.makedirs(self.project.workspace, exist_ok=True)
        self.lock = threading.RLock()
        self._audio: Optional[np.ndarray] = None
        self._analysis: Optional[Analysis] = None
        self._bank: Optional[SampleBank] = None
        self._bank_key: Optional[str] = None

    # ── paths ──
    def path(self, *parts: str) -> str:
        p = os.path.join(self.project.workspace, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    # ── source ──
    def set_source(self, path: str, copy_into_workspace: bool = False) -> dict:
        path = os.path.abspath(path)
        if copy_into_workspace:
            dst = self.path("source", os.path.basename(path))
            if os.path.abspath(dst) != path:
                shutil.copy2(path, dst)
            path = dst
        info = ff.probe(path)
        if not info.has_audio:
            raise ValueError("the source has no audio track — there is nothing to sample")
        with self.lock:
            self.project.source_path = path
            self.project.source_info = info.to_dict()
            self.project.analysis = None
            self.project.arrangement = None
            self.project.samples["selections"] = {}
            self._audio = None
            self._analysis = None
            self._bank = None
            if self.project.name.startswith("Untitled"):
                self.project.name = os.path.splitext(os.path.basename(path))[0][:60]
        return self.project.source_info

    def audio(self) -> np.ndarray:
        with self.lock:
            if self._audio is None:
                if not self.project.source_path:
                    raise ValueError("no source loaded")
                cache = self.path("cache", f"source-{_file_key(self.project.source_path)}.f32")
                if os.path.isfile(cache):
                    self._audio = np.fromfile(cache, dtype=np.float32)
                else:
                    self._audio = ff.decode_audio(self.project.source_path, sr=SAMPLE_RATE, mono=True)
                    self._audio.tofile(cache)
            return self._audio

    # ── analysis ──
    def analysis(self, progress: Progress = None, force: bool = False) -> Analysis:
        with self.lock:
            if self._analysis is not None and not force:
                return self._analysis
            if self.project.analysis and not force:
                self._analysis = Analysis.from_dict(self.project.analysis)
                return self._analysis
        x = self.audio()
        an = analyze(x, SAMPLE_RATE, progress)
        with self.lock:
            self._analysis = an
            self.project.analysis = an.to_dict()
            self._bank = None
        return an

    # ── samples ──
    def bank(self, progress: Progress = None) -> SampleBank:
        key = json.dumps(self.project.samples, sort_keys=True, default=str)
        with self.lock:
            if self._bank is not None and self._bank_key == key:
                return self._bank
        an = self.analysis(progress)
        bank = build_bank(self.audio(), SAMPLE_RATE, an, SampleConfig.from_dict(self.project.samples), progress)
        with self.lock:
            self._bank = bank
            self._bank_key = key
        return bank

    def sample_wav(self, sid: str) -> str:
        """Processed sample as a WAV file (for auditioning in the GUI)."""
        b = self.bank()
        s = b.get(sid)
        if s is None:
            raise KeyError(sid)
        key = hashlib.sha1((self._bank_key or "").encode()).hexdigest()[:8]
        out = self.path("samples", f"{sid}-{key}.wav")
        if not os.path.isfile(out):
            dsp.write_wav(out, s.audio, s.sr)
        return out

    def candidate_wav(self, kind: str, index: int) -> str:
        """Raw (unprocessed) audio of an analysis candidate."""
        an = self.analysis()
        c = an.candidates[kind][index]
        out = self.path("candidates", f"{kind}-{index}-{int(c.start * 1000)}.wav")
        if not os.path.isfile(out):
            x = self.audio()
            seg = x[int(c.start * SAMPLE_RATE):int(c.end * SAMPLE_RATE)]
            dsp.write_wav(out, dsp.apply_fades(seg, SAMPLE_RATE, 3, 6), SAMPLE_RATE)
        return out

    # ── base ──
    def set_base(self, path: str, progress: Progress = None, fit: bool = True) -> dict:
        """Load a Sparta base: map its tempo, bars, chords and sections, line bar 1 up with the remix
        and (``fit``) build the remix on the base's own structure."""
        from .audio.base import analyze_base_file
        path = os.path.abspath(path)
        bm = analyze_base_file(path, progress)
        with self.lock:
            self.project.base = bm.to_dict()
            self.project.mix.update({"base_path": path, "base_offset": bm.offset,
                                     "base_mode": self.project.mix.get("base_mode") or "remix"})
            if self.project.mix.get("base_mode") == "replace" and fit:
                self.project.mix["base_mode"] = "remix"
            if fit:
                self.project.variant = "base"
                self.project.arrangement = None
        return self.project.base

    def clear_base(self) -> None:
        with self.lock:
            self.project.base = None
            for k in ("base_path", "base_offset"):
                self.project.mix.pop(k, None)
            if self.project.variant == "base":
                self.project.variant = "unextended"
                self.project.arrangement = None

    # ── arrangement ──
    def arrangement(self) -> Arrangement:
        with self.lock:
            if self.project.arrangement:
                return Arrangement.from_dict(self.project.arrangement)
            o = self.project.options
            if self.project.variant == "base" and self.project.base:
                arr = build_from_base(self.project.base, pitching=o.get("pitching") or "normal",
                                      polish=o.get("polish") or "normal", minor=bool(o.get("minor")),
                                      title=o.get("title") or None, chorus_pattern=o.get("chorus_pattern"),
                                      progression=o.get("progression"),
                                      chorus_pitch=bool(o.get("chorus_pitch")))
                if not o.get("title"):
                    arr.title = f"{self.project.name} has a Sparta Remix" if self.project.source_path else arr.title
                return arr
            arr = build_arrangement(
                self.project.variant, bpm=o.get("bpm"), key=o.get("key", "D"), progression=o.get("progression"),
                pitching=o.get("pitching"), polish=o.get("polish"), minor=o.get("minor"),
                intro_pattern=o.get("intro_pattern"), chorus_pattern=o.get("chorus_pattern"),
                title=o.get("title") or None, chorus_pitch=bool(o.get("chorus_pitch")),
            )
            if o.get("title"):
                arr.title = o["title"]
            elif self.project.source_path:
                # Community naming: "<Source> has a Sparta Unextended Remix".
                arr.title = f"{self.project.name} has a {arr.title}"
            return arr

    def set_variant(self, variant: str, options: Optional[dict] = None) -> Arrangement:
        if variant == "base" and not self.project.base:
            raise ValueError("load a Sparta base first to fit the remix to it")
        if variant not in VARIANTS and variant != "base":
            raise ValueError(f"unknown variant {variant}")
        with self.lock:
            self.project.variant = variant
            if options is not None:
                self.project.options = dict(options)
            self.project.arrangement = None
        return self.arrangement()

    # ── render ──
    def render(self, quality: str = "preview", progress: Progress = None, out_path: Optional[str] = None,
               stems: bool = False) -> dict:
        if quality not in QUALITIES:
            raise ValueError(f"quality must be one of {QUALITIES}")

        def sub(a: float, b: float):
            return (lambda p, m: progress(a + (b - a) * p, m)) if progress else None

        bank = self.bank(sub(0.0, 0.2))
        arr = self.arrangement()
        events = compile_events(arr, set(bank.samples))
        if not events:
            raise ValueError("the arrangement produced no notes — check the sample selection")
        mix_cfg = MixConfig.from_dict({"pitching": arr.pitching, "polish": arr.polish, **self.project.mix})
        mix, info = render_mix(arr, events, bank, mix_cfg, sub(0.2, 0.55 if quality != "audio" else 0.95),
                               stems_dir=self.path("stems") if stems else None)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        wav = self.path("renders", f"mix-{quality}-{stamp}.wav")
        dsp.write_wav(wav, mix, SAMPLE_RATE)
        result = {"quality": quality, "audio": wav, "lufs": info["lufs"], "peak_db": info["peak_db"],
                  "duration": info["duration"], "events": len(events), "title": arr.title}
        if quality == "audio":
            if out_path:
                ff.encode_audio(wav, out_path)
                result["file"] = out_path
            else:
                result["file"] = wav
        else:
            vcfg = VideoConfig.from_dict({"preset_name": quality, **self.project.video})
            video = out_path or self.path("renders", f"remix-{quality}-{stamp}.mp4")
            muted = muted_stems(mix_cfg)
            shown = [e for e in events if e.stem not in muted]      # the picture shows what is heard
            render_video(video, self.project.source_path, arr, shown, bank, wav, vcfg, sub(0.55, 1.0),
                         duration=info["duration"])
            result["file"] = video
            result["video"] = video
        if progress:
            progress(1.0, "done")
        with self.lock:
            self.project.outputs[quality] = result
        return result

    def export_pack(self, folder: Optional[str] = None, video: bool = True, progress: Progress = None) -> dict:
        bank = self.bank(progress)
        folder = folder or self.path("sample_pack")
        files = bank.export(folder, self.project.source_path, video=video)
        meta = os.path.join(folder, "samples.json")
        with open(meta, "w", encoding="utf-8") as fh:
            json.dump({"source": self.project.source_path, "key": self.project.samples.get("key", "D"),
                       "samples": bank.to_dict()}, fh, indent=1)
        files.append(meta)
        if progress:
            progress(1.0, "sample pack exported")
        return {"folder": folder, "files": files}
