"""Project state (JSON) and the analyse → sample → arrange → render pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field, asdict, replace
from typing import Callable, Optional

import numpy as np

from . import SAMPLE_RATE, __version__
from . import ffmpeg as ff
from .arrangement import PERC_DEFAULT, Arrangement, build_arrangement, build_from_base, compile_events, variant_def
from .audio import dsp
from .audio.analysis import Analysis, analyze
from .render_audio import MixConfig, muted_stems, render_mix
from .render_video import VideoConfig, render_video
from .samples import PITCH_ROLES, SOURCE_FOLLOWS, SOURCE_SLOTS, SampleBank, SampleConfig, build_bank

Progress = Optional[Callable[[float, str], None]]

QUALITIES = ("audio", "preview", "720p", "1080p")
#: The base a remix is built on until another is chosen: the Sparta Remix's own (Extended) base.
DEFAULT_VARIANT = "extended"
#: How far the pitches go deeper or higher (Samples → Tuning), in octaves: the key stays.
PITCH_REGISTER = (-2, 2)


def pitch_register(samples: dict) -> int:
    """The deep ↔ high setting of a project's samples (octaves; 0: where they are tuned)."""
    try:
        k = int(round(float((samples or {}).get("pitch_register") or 0)))
    except (TypeError, ValueError):
        return 0
    return max(PITCH_REGISTER[0], min(PITCH_REGISTER[1], k))


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
    variant: str = "extended"
    arrangement: Optional[dict] = None       # full Arrangement.to_dict() once built/edited
    options: dict = field(default_factory=dict)  # bpm, key, progression, pitching, polish, minor …
    mix: dict = field(default_factory=dict)
    base: Optional[dict] = None              # BaseMap of the Sparta base (tempo, bars, sections …)
    midi: Optional[dict] = None              # a MIDI base: path, its parts, their roles (see spartagen.midi)
    sources: list = field(default_factory=list)  # the other videos samples are cut from: {id, path, info, analysis}
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


#: The project as the user saved it last, and the project as it is now (every change is kept there at once, so
#: nothing is lost if the app is closed by force — and "Don't save" can go back to the saved one).
PROJECT_FILE = "project.spartagen.json"
AUTOSAVE_FILE = "autosave.spartagen.json"


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
        self._pitch_cache: dict = {}         # tried pitch candidates of this source (see build_bank)
        self._audios: dict = {}              # the other videos': their sound, analysis and tried pitches, by id
        self._analyses: dict = {}
        self._pitch_caches: dict = {}
        self._midi = None                    # the parsed MIDI base (spartagen.midi.MidiSong)
        self._still: dict = {}               # the picture drawn last for the look's live preview, and its clips
        self._clean: Optional[str] = None    # the project as saved (or as it began): see autosave

    # ── saving ──
    @property
    def saved_path(self) -> str:
        return os.path.join(self.project.workspace, PROJECT_FILE)

    @property
    def autosave_path(self) -> str:
        return os.path.join(self.project.workspace, AUTOSAVE_FILE)

    @property
    def saved(self) -> bool:
        """Whether the project was ever saved (it is in Recent projects)."""
        return os.path.isfile(self.saved_path)

    @property
    def dirty(self) -> bool:
        """Whether it changed since it was saved last (or was never saved)."""
        return os.path.isfile(self.autosave_path)

    def _state(self) -> str:
        return json.dumps(self.project.to_dict(), sort_keys=True, default=str)

    def mark_clean(self) -> None:
        """What the project is now is what it was saved as (or began as): no changes yet."""
        self._clean = self._state()

    def autosave(self) -> Optional[str]:
        """Keep the project as it is now, apart from the saved one — when it differs from it (back as it was, the
        changes are gone: nothing is kept)."""
        if self._clean is None and self.saved:
            try:
                self._clean = json.dumps(Project.load(self.saved_path).to_dict(), sort_keys=True, default=str)
            except (OSError, ValueError):
                self._clean = ""
        if self._state() == self._clean:
            try:
                os.remove(self.autosave_path)
            except FileNotFoundError:
                pass
            return None
        return self.project.save(self.autosave_path)

    def save(self) -> str:
        """Save the project: it is what opens again, and Recent projects lists it."""
        where = self.project.save(self.saved_path)
        self.mark_clean()
        try:
            os.remove(self.autosave_path)
        except FileNotFoundError:
            pass
        return where

    def discard(self) -> bool:
        """Forget the changes since the last save; True when the project was never saved (nothing to go back to:
        its folder may go — see the engine's ``/api/project/discard``)."""
        try:
            os.remove(self.autosave_path)
        except FileNotFoundError:
            pass
        return not self.saved

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
            frm = self.sample_sources()
            self.project.source_path = path
            self.project.source_info = info.to_dict()
            self.project.analysis = None
            self.project.arrangement = None
            # The picks made in the old video go; those made in the project's other videos stay.
            sel = self.project.samples.get("selections") or {}
            self.project.samples["selections"] = {k: v for k, v in sel.items() if frm.get(k, "main") != "main"}
            self._audio = None
            self._analysis = None
            self._bank = None
            self._pitch_cache = {}
            if self.project.name.startswith("Untitled"):
                self.project.name = os.path.splitext(os.path.basename(path))[0][:60]
        return self.project.source_info

    # ── the project's other videos ──
    def source_list(self) -> list[dict]:
        """The project's videos: the main one ("main"), then the others samples may be cut from — each
        ``{id, path, info}``."""
        p = self.project
        main = [{"id": "main", "path": p.source_path, "info": p.source_info or {}}] if p.source_path else []
        return main + [v for v in p.sources if v.get("path")]

    def _source(self, sid: str) -> dict:
        for v in self.source_list():
            if v["id"] == (sid or "main"):
                return v
        raise KeyError(f"no video {sid!r} in this project")

    def add_source(self, path: str) -> dict:
        """Another video to cut samples from (the main one stays the main one)."""
        path = os.path.abspath(path)
        if not self.project.source_path:
            raise ValueError("open the main video first")
        if any(os.path.abspath(v["path"]) == path for v in self.source_list()):
            raise ValueError("this video is in the project already")
        info = ff.probe(path)
        if not info.has_audio:
            raise ValueError("this video has no sound — there is nothing to cut from it")
        with self.lock:
            ids = {v.get("id") for v in self.project.sources}
            n = 2
            while f"v{n}" in ids:
                n += 1
            entry = {"id": f"v{n}", "path": path, "info": info.to_dict(), "analysis": None}
            self.project.sources.append(entry)
        return entry

    def remove_source(self, sid: str) -> None:
        """Take a video out of the project: what was cut from it is cut from the main one again."""
        with self.lock:
            if not any(v.get("id") == sid for v in self.project.sources):
                raise KeyError(f"no video {sid!r} in this project")
            gone = {slot for slot, v in self.sample_sources().items() if v == sid}
            self.project.sources = [v for v in self.project.sources if v.get("id") != sid]
            self.project.samples["from"] = {k: v for k, v in (self.project.samples.get("from") or {}).items()
                                            if v != sid}
            self.project.samples["selections"] = {k: v for k, v in (self.project.samples.get("selections") or {}).items()
                                                  if k not in gone}
            for cache in (self._audios, self._analyses, self._pitch_caches):
                cache.pop(sid, None)

    def sample_sources(self) -> dict:
        """The video each pick of the Samples page is cut from (``{slot: video id}``): the user's choices, and the
        picks that go with them (see ``samples.SOURCE_FOLLOWS``) — "main" for the rest."""
        ids = {v["id"] for v in self.source_list()} | {"main"}
        chosen = {k: v for k, v in (self.project.samples.get("from") or {}).items() if k in SOURCE_SLOTS and v in ids}
        out = {slot: chosen.get(slot, "main") for slot in SOURCE_SLOTS}
        for slot, lead in SOURCE_FOLLOWS.items():
            if slot not in chosen:
                out[slot] = out[lead]
        return out

    def set_sample_source(self, slot: str, sid: str) -> None:
        """Cut ``slot``'s sample (and the picks that go with it) from another of the project's videos."""
        if slot not in SOURCE_SLOTS:
            raise ValueError(f"there is no sample {slot!r} to cut")
        sid = sid or "main"
        self._source(sid)                                  # (an unknown video is refused)
        with self.lock:
            before = self.sample_sources()
            self.project.samples["from"] = dict(self.project.samples.get("from") or {}, **{slot: sid})
            after = self.sample_sources()
            # A pick in one video means nothing in another: those that moved are cut automatically again.
            self.project.samples["selections"] = {k: v for k, v in (self.project.samples.get("selections") or {}).items()
                                                  if before.get(k) == after.get(k)}

    def audio(self, sid: str = "main") -> np.ndarray:
        with self.lock:
            if sid in ("", "main"):
                if self._audio is None:
                    if not self.project.source_path:
                        raise ValueError("no source loaded")
                    self._audio = self._decode(self.project.source_path)
                return self._audio
            x = self._audios.get(sid)
            if x is None:
                x = self._audios[sid] = self._decode(self._source(sid)["path"])
            return x

    def _decode(self, path: str) -> np.ndarray:
        cache = self.path("cache", f"source-{_file_key(path)}.f32")
        if os.path.isfile(cache):
            return np.fromfile(cache, dtype=np.float32)
        x = ff.decode_audio(path, sr=SAMPLE_RATE, mono=True)
        x.tofile(cache)
        return x

    # ── analysis ──
    def analysis(self, progress: Progress = None, force: bool = False, sid: str = "main") -> Analysis:
        if sid not in ("", "main"):
            entry = self._source(sid)
            with self.lock:
                an = self._analyses.get(sid)
                if an is not None and not force:
                    return an
                if entry.get("analysis") and not force:
                    an = self._analyses[sid] = Analysis.from_dict(entry["analysis"])
                    return an
            an = analyze(self.audio(sid), SAMPLE_RATE, progress)
            with self.lock:
                self._analyses[sid] = an
                entry["analysis"] = an.to_dict()
                self._bank = None
            return an
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

    def videos_in_use(self) -> list[str]:
        """The other videos some sample is cut from."""
        return sorted({v for v in self.sample_sources().values() if v != "main"})

    # ── samples ──
    def bank(self, progress: Progress = None) -> SampleBank:
        # (Deeper or higher pitches are the same samples played elsewhere: nothing to cut again.)
        key = json.dumps({"samples": {k: v for k, v in self.project.samples.items() if k != "pitch_register"},
                          "videos": [[v.get("id"), v.get("path")] for v in self.project.sources]},
                         sort_keys=True, default=str)
        with self.lock:
            if self._bank is not None and self._bank_key == key:
                return self._bank
        frm = self.sample_sources()
        others: dict[str, list] = {}
        for slot, sid in frm.items():
            if sid != "main":
                others.setdefault(sid, []).append(slot)
        if others:
            bank = self._bank_of_videos(frm, others, progress)
        else:
            an = self.analysis(progress)
            bank = build_bank(self.audio(), SAMPLE_RATE, an, SampleConfig.from_dict(self.project.samples), progress,
                              shot_cuts=self._shot_cuts(), cache=self._pitch_cache)
        with self.lock:
            self._bank = bank
            self._bank_key = key
        return bank

    def _bank_of_videos(self, frm: dict, others: dict, progress: Progress) -> SampleBank:
        """Samples cut from several videos: a bank from each video a pick comes from, then each pick's samples taken
        from its own video's bank (a video's own best pitches go to the pitches it gives, in order).  The pitches
        share one octave — the main pitch's — wherever they come from."""
        cfg = SampleConfig.from_dict(self.project.samples)
        sel = cfg.selections or {}
        first = frm.get("pitch1", "main")
        order = [first] + [sid for sid in ("main", *others) if sid != first]
        octave = cfg.pitch_octave
        banks: dict[str, SampleBank] = {}

        def local_names(slots: list) -> dict:
            pitches = [r for r in PITCH_ROLES if r in slots]
            return {r: PITCH_ROLES[k] for k, r in enumerate(pitches)}
        for i, sid in enumerate(order):
            sub = (lambda p, m, i=i: progress((i + p) / len(order), m)) if progress else None
            if sid == "main":
                local_sel = {k: v for k, v in sel.items() if frm.get(k, "main") == "main"}
            else:
                names = local_names(others[sid])
                local_sel = {names.get(k, k): v for k, v in sel.items() if k in others[sid]}
            local = replace(cfg, selections=local_sel, pitch_octave=cfg.pitch_octave if sid == first else octave)
            b = build_bank(self.audio(sid), SAMPLE_RATE, self.analysis(sub, sid=sid), local, sub,
                           shot_cuts=self._shot_cuts(sid),
                           cache=self._pitch_cache if sid == "main" else self._pitch_caches.setdefault(sid, {}))
            banks[sid] = b
            p1 = b.samples.get("pitch1")
            if sid == first and octave is None and p1 is not None and p1.pitched:
                octave = int(round(p1.root_midi)) // 12 - 1
        out = banks["main"]
        for sid, slots in others.items():
            b, path, names = banks[sid], self._source(sid)["path"], local_names(slots)
            for slot in slots:
                ids = SOURCE_SLOTS[slot]
                if slot == "phrase":                         # the main phrase's chops come with it
                    for k in [k for k, smp in out.samples.items() if smp.role == "syllable"]:
                        del out.samples[k]
                    ids = ids + tuple(k for k, smp in b.samples.items() if smp.role == "syllable")
                for gid in ids:
                    lid = names.get(gid, gid)
                    smp = b.samples.get(lid)
                    if smp is None:                          # (none in that video: the main one's stays)
                        continue
                    smp = replace(smp, meta=dict(smp.meta), source=path, source_id=sid)
                    if lid != gid:
                        smp.id, smp.label = gid, smp.label.replace(lid, gid)
                    out.samples[gid] = smp
        return out

    def _shot_cuts(self, sid: str = "main"):
        """Camera cuts of a video in a time range (None for audio-only sources)."""
        if sid in ("", "main"):
            info, src = self.project.source_info or {}, self.project.source_path
        else:
            v = self._source(sid)
            info, src = v.get("info") or {}, v["path"]
        if not src or not info.get("has_video"):
            return None
        fps = min(max(float(info.get("fps") or 25.0), 10.0), 60.0)
        return lambda a, b: ff.shot_cuts(src, a, b, fps=fps)

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

    def candidate_wav(self, kind: str, index: int, sid: str = "main") -> str:
        """Raw (unprocessed) audio of an analysis candidate (of the main video, or of video ``sid``)."""
        an = self.analysis(sid=sid)
        c = an.candidates[kind][index]
        src = self._source(sid)["path"]
        out = self.path("candidates", f"{_file_key(src)}-{kind}-{index}-{int(c.start * 1000)}.wav")
        if not os.path.isfile(out):
            x = self.audio(sid)
            seg = x[int(c.start * SAMPLE_RATE):int(c.end * SAMPLE_RATE)]
            dsp.write_wav(out, dsp.apply_fades(seg, SAMPLE_RATE, 3, 6), SAMPLE_RATE)
        return out

    # ── key ──
    def follow_key(self, key: Optional[str]) -> None:
        """Tune the pitch samples to a base's (or template's, or MIDI's) key — unless the user chose the
        key themselves (``options["key_mode"] == "manual"``)."""
        if not key or self.project.options.get("key_mode") == "manual":
            return
        with self.lock:
            if self.project.samples.get("key") != key:
                self.project.samples["key"] = key

    def set_key(self, key: Optional[str]) -> None:
        """The user's own key (None or "auto": follow the base again)."""
        with self.lock:
            if key in (None, "", "auto"):
                self.project.options["key_mode"] = "auto"
            else:
                from .audio.pitch import pitch_class
                pitch_class(key)
                self.project.options["key_mode"] = "manual"
                self.project.samples["key"] = key

    # ── base ──
    def base_template(self):
        """The base template the base file is played as (None: read everything from the file)."""
        tid = self.project.options.get("base_template")
        if not tid:
            return None
        from .bases import get_template
        try:
            return get_template(tid)
        except KeyError:
            return None

    def set_base(self, path: str, progress: Progress = None, fit: bool = True,
                 template: Optional[str] = None, base_map: Optional[dict] = None) -> dict:
        """Load a Sparta base: map its tempo, bars, chords and sections, line bar 1 up with the remix
        and (``fit``) build the remix on the base's own structure.  ``template`` names the base
        template it is (its tempo guides the analysis, its patterns go on the parts); ``base_map`` is
        the base's map already read (a template's own base)."""
        from .audio.base import BaseMap, analyze_base_file
        path = os.path.abspath(path)
        if self.project.options.get("base_from_template") and template is None:
            # Another base after a template's own: read as it is (the template's guide went with its base).
            self.project.options.pop("base_template", None)
            if self.project.options.get("base_structure") == "template":
                self.project.options["base_structure"] = "detected"
        if template is not None:
            self.project.options["base_template"] = template or ""
        tpl = self.base_template()
        if base_map:
            bm = BaseMap.from_dict(dict(base_map, path=path))
        else:
            bm = analyze_base_file(path, progress, bpm_hint=tpl.bpm if tpl else None)
        with self.lock:
            self.project.options.pop("base_from_template", None)    # the user's own base now
            self.project.base = bm.to_dict()
            self.project.mix.update({"base_path": path, "base_offset": bm.offset,
                                     "base_mode": self.project.mix.get("base_mode") or "remix"})
            if self.project.mix.get("base_mode") == "replace" and fit:
                self.project.mix["base_mode"] = "remix"
            if fit:
                self.project.variant = "base"
                self.project.arrangement = None
        self.follow_key(bm.key)
        if fit and tpl is not None and tpl.midi:
            # A MIDI base's template: the remix plays its MIDI — its bass line, its drums, its parts bar for bar —
            # and this file plays under it, its bar 1 on the MIDI's first.
            self.use_midi_template(tpl)
        return self.project.base

    def follow_base(self, template: Optional[str] = None) -> None:
        """Build the remix on the loaded base (``template``: which base it is, "" for none): on a MIDI base's
        template the remix plays the template's MIDI over the file, else it follows the base (see
        :meth:`base_map`)."""
        if template is not None:
            self.project.options["base_template"] = template or ""
        tpl = self.base_template()
        if tpl is not None and tpl.midi:
            self.use_midi_template(tpl)
            return
        if not self.project.base:
            raise ValueError("load a Sparta base first to fit the remix to it")
        with self.lock:
            self.project.variant = "base"
            self.project.arrangement = None

    def base_map(self) -> Optional[dict]:
        """The base as the remix follows it: as read from the file — or, when the template it is knows this base
        (its audio's map, kept beside it), the template's own parts, chords and tempo, from where this file's
        bar 1 is.  Drums and bass then follow the template, not a reading of the audio."""
        b = self.project.base
        if not b:
            return None
        tpl = self.base_template()
        known = tpl.audio_map() if tpl is not None else None
        if not known:
            return b
        return dict(known, path=b.get("path", ""), offset=b.get("offset", known.get("offset", 0.0)),
                    duration=b.get("duration", known.get("duration", 0.0)))

    def own_base(self) -> bool:
        """Whether the base file is one the user opened (not the audio a template comes with)."""
        return bool(self.project.mix.get("base_path")) and not self.project.options.get("base_from_template")

    def clear_base(self) -> None:
        with self.lock:
            self.project.base = None
            self.project.options.pop("base_from_template", None)
            for k in ("base_path", "base_offset"):
                self.project.mix.pop(k, None)
            if self.project.variant == "base":
                self.project.variant = DEFAULT_VARIANT
                self.project.arrangement = None

    # ── MIDI base ──
    def midi_song(self):
        from .midi import read_midi
        with self.lock:
            m = self.project.midi
            if not m:
                return None
            if self._midi is None or self._midi.path != os.path.abspath(m["path"]):
                self._midi = read_midi(m["path"])
            return self._midi

    def set_midi(self, path: str, copy_into_workspace: bool = True, use: bool = True) -> dict:
        """Load a MIDI base: its parts get suggested roles and (``use``) the remix follows its notes."""
        from .midi import read_midi, suggest_roles
        path = os.path.abspath(path)
        song = read_midi(path)                          # raises MidiError for a bad file
        if copy_into_workspace:
            dst = self.path("midi", os.path.basename(path))
            if os.path.abspath(dst) != path:
                shutil.copy2(path, dst)
            path = dst
            song.path = dst
        if use:
            self._drop_template_base()                 # another base's audio would play under these notes
        with self.lock:
            self._midi = song
            self.project.midi = {"path": path, "summary": song.summary(), "mapping": suggest_roles(song),
                                 "auto_percussion": True, "auto_phrase": True, "section_bars": 8}
            if use:
                self.project.variant = "midi"
                self.project.arrangement = None
        self.follow_key(song.key)
        return self.project.midi

    @staticmethod
    def _template(tid: Optional[str]):
        """A base template by id (None: no such template)."""
        if not tid:
            return None
        from .bases import get_template
        try:
            return get_template(tid)
        except KeyError:
            return None

    def use_midi_template(self, tpl, options: Optional[dict] = None) -> dict:
        """Build the remix on a MIDI base's template: its MIDI, what the samples play of each of its parts,
        its parts bar for bar and its key."""
        from .midi import clean_mapping
        self.set_midi(tpl.midi_path())
        song = self.midi_song()
        with self.lock:
            m = self.project.midi
            m["mapping"] = clean_mapping(song, dict(m.get("mapping") or {}, **tpl.midi_mapping()))
            m.update({"template": tpl.id, "plan": [list(p) for p in tpl.plan], "minor": bool(tpl.minor)})
            for k in ("auto_percussion", "auto_phrase"):        # (a template saved with its MIDI keeps them)
                if k in tpl.options:
                    m[k] = bool(tpl.options[k])
            if options is not None:
                keep = {k: self.project.options[k] for k in ("key_mode", "base_template", "base_structure")
                        if k in self.project.options}
                self.project.options = dict(keep, **options)
            self.project.arrangement = None
        self.follow_key(tpl.key)
        if tpl.audio and not self.own_base() and os.path.isfile(tpl.audio_path()):
            self._template_audio(tpl)                  # its base's own audio under its notes
        return self.project.midi

    def _template_audio(self, tpl) -> None:
        """Put the audio a MIDI base's template comes with under the remix (its map, kept beside it, says where
        bar 1 is; without one it is read from the file)."""
        from .audio.base import BaseMap, analyze_base_file
        path = tpl.audio_path()
        known = tpl.audio_map()
        bm = BaseMap.from_dict(dict(known, path=path)) if known else analyze_base_file(path, bpm_hint=tpl.bpm)
        with self.lock:
            self.project.base = bm.to_dict()
            self.project.mix.update({"base_path": path, "base_offset": bm.offset,
                                     "base_mode": self.project.mix.get("base_mode") or "remix"})
            self.project.options["base_from_template"] = tpl.id

    def use_audio_template(self, tpl, options: Optional[dict] = None) -> dict:
        """Build the remix on a template that comes with its base's audio (the Extended base): that base
        plays under the remix, and the remix follows it as it is read from the audio — its parts bar for
        bar, just as when the base file is opened by hand."""
        if options is not None:
            with self.lock:
                keep = {k: self.project.options[k] for k in ("key_mode",) if k in self.project.options}
                self.project.options = dict(keep, **options)
        with self.lock:
            self.project.options["base_structure"] = "detected"
        self.set_base(tpl.audio_path(), template="", base_map=tpl.audio_map())
        with self.lock:
            self.project.options["base_from_template"] = tpl.id
        return self.project.base

    def _drop_template_base(self) -> None:
        """Take away the base a template brought (another base is being used)."""
        if self.project.options.get("base_from_template"):
            self.clear_base()
            with self.lock:
                for k in ("base_template", "base_structure"):
                    self.project.options.pop(k, None)

    def apply_template_base(self) -> None:
        """A remix on a template that comes with its base's audio plays on that audio: put it under the remix
        (a new project, or one saved before the template brought it)."""
        tpl = self._template(self.project.variant)
        if tpl is not None and tpl.audio and not self.project.arrangement and os.path.isfile(tpl.audio_path()):
            self.use_audio_template(tpl)

    def set_midi_mapping(self, mapping: Optional[dict] = None, auto_percussion: Optional[bool] = None,
                         auto_phrase: Optional[bool] = None, section_bars: Optional[int] = None) -> dict:
        """Roles for the MIDI's parts (``{part id: {"role", "octave", "gain_db"}}``; "off" disables one)."""
        from .midi import clean_mapping
        song = self.midi_song()
        if song is None:
            raise ValueError("load a MIDI base first")
        with self.lock:
            m = self.project.midi
            before = {pid: dict(v) for pid, v in (m.get("mapping") or {}).items()}
            if mapping is not None:
                merged = dict(m.get("mapping") or {})
                merged.update(mapping)
                m["mapping"] = clean_mapping(song, merged)
            if auto_percussion is not None:
                m["auto_percussion"] = bool(auto_percussion)
            if auto_phrase is not None:
                m["auto_phrase"] = bool(auto_phrase)
            if section_bars is not None:
                m["section_bars"] = max(2, min(32, int(section_bars)))
            if self.project.variant == "midi":
                gains_only = (auto_percussion is None and auto_phrase is None and section_bars is None
                              and all({k: v for k, v in r.items() if k != "gain_db"}
                                      == {k: v for k, v in before.get(pid, {}).items() if k != "gain_db"}
                                      for pid, r in m["mapping"].items()))
                if gains_only and self.project.arrangement:
                    # Only channel volumes changed: the remix keeps its parts as edited, its tracks' levels move.
                    for sec in self.project.arrangement.get("sections", []):
                        for tr in sec.get("tracks", []):
                            pid = str(tr.get("id", ""))[5:] if str(tr.get("id", "")).startswith("midi_") else None
                            if pid in m["mapping"]:
                                delta = float(m["mapping"][pid].get("gain_db", 0.0)) - \
                                    float(before.get(pid, {}).get("gain_db", 0.0))
                                tr["gain_db"] = round(float(tr.get("gain_db", 0.0)) + delta, 2)
                else:
                    self.project.arrangement = None
        return self.project.midi

    def as_template(self, name: str, description: str = "", with_midi: bool = True,
                    with_audio: bool = True) -> tuple:
        """The remix as a template of the user's: its parts, tempo, key and pattern choices — on a MIDI, the MIDI
        with what the samples play of each channel (``with_midi``), and the base audio the user put under it
        (``with_audio``).  Returns (template, the audio's map or None) for :func:`bases.save_user_template`."""
        from .bases import MIDI_PLAN_KINDS, BaseTemplate, _slug, template_from_arrangement
        p = self.project
        arr = self.arrangement()
        patterns = dict(p.options.get("patterns") or {})
        if with_midi and p.variant == "midi" and p.midi:
            song = self.midi_song()
            m = p.midi
            fold = {"intro_hits": "intro", "intro3": "intro", "chorus_final": "chorus", "awesomeness1": "awesomeness",
                    "awesomeness2": "awesomeness"}
            plan = [[k if k in MIDI_PLAN_KINDS else "chorus", int(sec.bars)]
                    for sec in arr.sections for k in [fold.get(sec.kind, sec.kind)]]
            t = BaseTemplate(id=_slug(name), name=name, bpm=float(song.bpm), key=arr.key,
                             minor=bool(m.get("minor") if m.get("minor") is not None else song.minor), plan=plan,
                             roles={pid: dict(r) for pid, r in (m.get("mapping") or {}).items()},
                             midi=os.path.abspath(m["path"]), pitching=arr.pitching, polish=arr.polish,
                             options=dict(patterns, wiki_perc=True, auto_percussion=bool(m.get("auto_percussion", True)),
                                          auto_phrase=bool(m.get("auto_phrase", True))),
                             description=description or f"Saved from “{arr.title}”.", user=True)
        else:
            t = template_from_arrangement(arr, name, description, key=p.samples.get("key"), options=patterns)
        audio_map = None
        base = p.mix.get("base_path")
        if with_audio and base and os.path.isfile(base) and self.own_base() and self.base_heard():
            t.audio = os.path.abspath(base)
            if p.base:
                audio_map = dict(p.base, path="", offset=float(p.mix.get("base_offset", p.base.get("offset", 0.0))))
        return t, audio_map

    def clear_midi(self) -> None:
        with self.lock:
            self.project.midi = None
            self._midi = None
            if self.project.variant == "midi":
                self.project.variant = "base" if self.project.base else DEFAULT_VARIANT
                self.project.arrangement = None

    # ── arrangement ──
    def arrangement(self) -> Arrangement:
        self.apply_template_base()
        with self.lock:
            if self.project.arrangement:
                return Arrangement.from_dict(self.project.arrangement)
            o = self.project.options
            key = self.project.samples.get("key") or None
            if self.project.variant == "midi" and self.project.midi:
                from .midi import build_from_midi
                m = self.project.midi
                tpl = self._template(m.get("template"))
                arr = build_from_midi(self.midi_song(), m.get("mapping"), bool(m.get("auto_percussion", True)),
                                      bool(m.get("auto_phrase", True)), key=key,
                                      pitching=o.get("pitching") or "normal", polish=o.get("polish") or "normal",
                                      section_bars=int(m.get("section_bars", 8)),
                                      perc_pattern=(o.get("patterns") or {}).get("perc_pattern")
                                      or (tpl.options.get("perc_pattern") if tpl is not None else None) or PERC_DEFAULT,
                                      plan=m.get("plan") or None, minor=m.get("minor"))
                arr.title = o.get("title") or (f"{self.project.name} has a Sparta Remix" if self.project.source_path
                                               else "Sparta Remix")
                return arr
            if self.project.variant == "base" and self.project.base:
                tpl = self.base_template()
                extra = dict(tpl.options) if tpl else {}
                extra.update(o.get("patterns") or {})
                arr = build_from_base(self.base_map(), pitching=o.get("pitching") or (tpl.pitching if tpl else "normal"),
                                      polish=o.get("polish") or (tpl.polish if tpl else "normal"),
                                      minor=None if o.get("minor") is None else bool(o.get("minor")),
                                      title=o.get("title") or None, chorus_pattern=o.get("chorus_pattern"),
                                      progression=o.get("progression") or (tpl.progression if tpl else None) or None,
                                      chorus_pitch=bool(o.get("chorus_pitch")), extra=extra,
                                      plan=tpl.plan if tpl and o.get("base_structure") == "template" else None)
                if key:
                    arr.key = key
                if not o.get("title"):
                    arr.title = f"{self.project.name} has a Sparta Remix" if self.project.source_path else arr.title
                return arr
            variant = self.project.variant
            try:
                variant_def(variant)
            except ValueError:                        # a template that is gone (an older project's): the usual base
                variant = DEFAULT_VARIANT
            arr = build_arrangement(
                variant, bpm=o.get("bpm"), key=key, progression=o.get("progression"),
                pitching=o.get("pitching"), polish=o.get("polish"), minor=o.get("minor"),
                intro_pattern=o.get("intro_pattern"), chorus_pattern=o.get("chorus_pattern"),
                title=o.get("title") or None, chorus_pitch=bool(o.get("chorus_pitch")),
                options=o.get("patterns") or None,
            )
            if o.get("title"):
                arr.title = o["title"]
            elif self.project.source_path:
                # Community naming: "<Source> has a Sparta Unextended Remix".
                arr.title = f"{self.project.name} has a {arr.title}"
            return arr

    def events(self, arr: Optional[Arrangement] = None, bank: Optional[SampleBank] = None) -> list:
        """The remix's notes on the samples there are — the pitches moved deeper or higher by whole octaves as
        the samples' tuning asks (``pitch_register``), so the key stays."""
        bank = bank or self.bank()
        ev = compile_events(arr or self.arrangement(), set(bank.samples))
        k = pitch_register(self.project.samples)
        if k:
            ev = [replace(e, semis=e.semis + 12 * k) if e.pitched and e.sample.startswith("pitch") else e for e in ev]
        return ev

    def still(self, t: float, width: int = 640, height: int = 360) -> np.ndarray:
        """The remix's picture at t seconds, with the current look — what the video shows then, drawn on its own
        in a moment (the clips it needs stay decoded, so changing an effect redraws at once)."""
        from .render_video import Compositor, backdrop_for
        if not self.project.source_path:
            raise ValueError("open a video first")
        if self.project.analysis is None:
            raise ValueError("cut the samples first")
        bank = self.bank()
        arr = self.arrangement()
        mix_cfg = MixConfig.from_dict({"pitching": arr.pitching, "polish": arr.polish, **self.mix_settings()})
        muted = muted_stems(mix_cfg)
        cfg = VideoConfig.from_dict({"preset_name": "preview", **self.project.video, "width": width, "height": height})
        key = json.dumps([arr.to_dict(), self.project.video, sorted(muted), self._bank_key, width, height,
                          pitch_register(self.project.samples)], sort_keys=True, default=str)
        with self.lock:
            st = self._still
            comp = st.get("comp") if st.get("key") == key else None
            if comp is None:
                events = [e for e in self.events(arr, bank) if e.stem not in muted]
                media = (self.project.source_path, self._bank_key, width, height)
                same = st.get("media") == media
                info = self.project.source_info or {}
                behind = (media, cfg.background, cfg.background_file, cfg.background_blur)
                backdrop = st.get("backdrop") if st.get("behind") == behind else backdrop_for(
                    cfg, self.project.source_path, bool(info.get("has_video", True)),
                    float(info.get("duration") or 0.0))
                comp = Compositor(self.project.source_path, arr, events, bank, cfg,
                                  cache=st.get("cache") if same else None, backdrop=backdrop)
                self._still = {"key": key, "comp": comp, "media": media, "cache": comp.cache, "backdrop": backdrop,
                               "behind": behind}
            return comp.still(t)

    def base_heard(self) -> bool:
        """Whether the loaded base file plays under the remix: a base you opened plays under whatever the remix
        is built on — that base, your MIDI or any template; the audio a template comes with only under that
        template (never under another one's notes)."""
        p = self.project
        tid = p.options.get("base_from_template")
        if not tid:
            return True
        return p.variant == "base" or (p.variant == "midi" and (p.midi or {}).get("template") == tid)

    def mix_settings(self) -> dict:
        """The mix as rendered: the loaded base file plays under the remix when :meth:`base_heard`."""
        mix = dict(self.project.mix)
        tid = self.project.options.get("base_from_template")
        if tid and not os.path.isfile(mix.get("base_path") or ""):
            tpl = self._template(tid)                 # the app moved since the project was saved: its base came along
            if tpl is not None and tpl.audio:
                mix["base_path"] = tpl.audio_path()
        if not self.base_heard():
            mix.pop("base_path", None)
        return mix

    def set_variant(self, variant: str, options: Optional[dict] = None) -> Arrangement:
        """Build the remix on a base template (or a variant; "base": on the loaded base file)."""
        key = None
        if variant == "base":
            if not self.project.base:
                raise ValueError("load a Sparta base first to fit the remix to it")
        elif variant == "midi":
            if not self.project.midi:
                raise ValueError("load a MIDI base first")
            if self.project.midi.get("template") != self.project.options.get("base_from_template"):
                self._drop_template_base()             # another template's base does not go under these notes
            tpl = self._template(self.project.midi.get("template"))
            key = tpl.key if tpl is not None else self.midi_song().key
        else:
            tpl = self._template(variant)
            if tpl is not None and tpl.midi:
                self.use_midi_template(tpl, options)
                return self.arrangement()
            if tpl is not None and tpl.audio and os.path.isfile(tpl.audio_path()):
                self.use_audio_template(tpl, options)
                return self.arrangement()
            self._drop_template_base()
            key = variant_def(variant).get("key") or "D"  # raises for an unknown template
        with self.lock:
            self.project.variant = variant
            if options is not None:
                keep = {k: self.project.options[k] for k in ("key_mode", "base_template", "base_structure")
                        if k in self.project.options}
                self.project.options = dict(keep, **options)
            self.project.arrangement = None
        if key:
            self.follow_key(key)
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
        events = self.events(arr, bank)
        if not events:
            raise ValueError("the arrangement produced no notes — check the sample selection")
        mix_cfg = MixConfig.from_dict({"pitching": arr.pitching, "polish": arr.polish, **self.mix_settings()})
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

    def listen(self, track: dict, section: int = 0) -> str:
        """One track's pattern on its own, as the remix plays it in that part — a loop of it, or two of a short
        one, with the remix's sound but not the base: a WAV of what the block editor holds."""
        import math
        from .arrangement import SectionSpec, TrackSpec, pattern_blocks
        if self.project.analysis is None:
            raise ValueError("cut the samples first")
        arr = self.arrangement()
        sec = arr.sections[min(max(int(section), 0), len(arr.sections) - 1)]
        tr = TrackSpec.from_dict(dict(track, id=track.get("id") or "listen", kind=track.get("kind") or "pitch"))
        tr.muted, tr.start_bar, tr.end_bar = False, 0.0, None
        if tr.follow.startswith("@"):
            raise ValueError("this track plays when another one does — listen to that one")
        b = pattern_blocks(tr)
        bars = math.ceil((b["pickup"] + b["loop"]) / 16 - 1e-9)
        bars = min(8, bars * 2 if bars == 1 else bars)
        part = SectionSpec(sec.kind, max(1, bars), [tr], sec.name, sec.layout, [], sec.progression)
        one = Arrangement(title="listen", variant=arr.variant, bpm=arr.bpm, key=arr.key, progression=arr.progression,
                          pitching=arr.pitching, polish=arr.polish, sections=[part])
        bank = self.bank()
        events = self.events(one, bank)
        if not events:
            raise ValueError("this pattern plays no notes")
        mix = {k: v for k, v in self.mix_settings().items() if k not in ("base_path", "base_offset", "mute_groups")}
        cfg = MixConfig.from_dict(dict(mix, pitching=arr.pitching, polish=arr.polish, tail_s=1.0, tape_stop_end=False,
                                       risers=False, stutter_fills=False))
        audio, _info = render_mix(one, events, bank, cfg)
        wav = self.path("renders", "listen.wav")
        dsp.write_wav(wav, audio, SAMPLE_RATE)
        return wav

    def export_pack(self, folder: Optional[str] = None, video: bool = True, progress: Progress = None) -> dict:
        bank = self.bank(progress)
        folder = folder or self.path("sample_pack")
        files = bank.export(folder, self.project.source_path, video=video)
        meta = os.path.join(folder, "samples.json")
        from .samples import pack_path
        samples = {k: dict(v, file=pack_path(bank.samples[k]) + ".wav") for k, v in bank.to_dict().items()}
        with open(meta, "w", encoding="utf-8") as fh:
            json.dump({"source": self.project.source_path, "key": self.project.samples.get("key", "D"),
                       "samples": samples}, fh, indent=1)
        files.append(meta)
        if progress:
            progress(1.0, "sample pack exported")
        return {"folder": folder, "files": files}
