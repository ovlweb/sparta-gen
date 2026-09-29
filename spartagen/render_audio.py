"""Render compiled note events into a polished stereo mix.

Pipeline: note voices (pitched with PSOLA or the classic sampler method,
ChorusCrisp pluck, chokes) → stems → per-stem chains → kick sidechain →
section bus FX (filter sweeps, tape stop) → optional Sparta base underneath
→ master chain (Xleth OTT, saturation, glue compression, limiter) → loudness
target.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .arrangement import Arrangement, NoteEvent
from .audio import dsp, fx, psola
from .samples import Sample, SampleBank

Progress = Optional[Callable[[float, str], None]]

POLISH_TARGET_LUFS = {"light": -12.0, "normal": -10.0, "hard": -8.5}

# Gain staging: the source pitches lead (they ARE the remix), drums punch just
# under them, the bass supports.  Measured on chorus sections after the stem chains.
STEM_LEVEL_DB = {
    "pitch": 2.0, "chorus": 4.5, "pitch_layers": 5.0, "pitch_soft": 3.0, "pad": -1.0, "bass": -4.0,
    "drums": -3.5, "chop": 4.0, "quotes": 2.0, "misc": 0.0,
}

BACKING_STEMS = {"drums", "bass", "pad"}
REMIX_DRUMS_DB = 0.0      # source percussion on top of a base's own drums (heard, like a remixer's percs)
REMIX_BASS_DB = 3.0       # the bass pitch (a pitch like the others) heard over a base's own bass


#: Sound FX presets: what each sets (amounts are multipliers of the usual polish; anything chosen by hand wins).
FX_PRESETS: dict[str, dict] = {
    "xleth": {},
    "clean": {"ott": 0.0, "drive": 0.3, "pump": 0.3, "reverb": 0.6, "delay": 0.5},
    "loud": {"ott": 1.6, "drive": 1.6, "pump": 1.3, "width": 1.2},
    "lofi": {"lofi": 0.6, "reverb": 0.7, "ott": 0.6, "width": 0.8, "tape_stop_end": True},
    "big_room": {"reverb": 2.0, "delay": 1.5, "width": 1.3, "risers": True, "pump": 1.3},
    "retro": {"ott": 0.0, "drive": 0.5, "pump": 0.0, "reverb": 0.5, "delay": 0.0, "lofi": 0.25},
}
FX_PRESET_NAMES = {"xleth": "Xleth polish", "clean": "Clean", "loud": "Loud & crisp", "lofi": "Lo-fi",
                   "big_room": "Big room", "retro": "Retro 2010"}
#: Every FX amount, its default and its range.
FX_AMOUNTS = {"reverb": (1.0, 0.0, 2.5), "delay": (1.0, 0.0, 2.5), "ott": (1.0, 0.0, 2.0), "pump": (1.0, 0.0, 2.0),
              "drive": (1.0, 0.0, 2.0), "width": (1.0, 0.5, 1.8), "lofi": (0.0, 0.0, 1.0)}
FX_SWITCHES = {"tape_stop_end": False, "risers": False, "stutter_fills": False}
#: The volume faders, and the stems each one moves (the base file under the remix has its own: base_gain_db).
VOLUME_GROUPS = {
    "phrase": ("Main phrase", ("chorus", "chop")),
    "pitches": ("Pitches", ("pitch", "pitch_soft")),
    "chords": ("Chords", ("pitch_layers", "pad")),
    "bass": ("Bass", ("bass",)),
    "drums": ("Percussion", ("drums",)),
    "quotes": ("Quotes", ("quotes",)),               # (the Madness words too)
}
VOLUME_RANGE = (-24.0, 12.0)            # dB a fader moves its stems by
GROUP_OF_STEM = {stem: g for g, (_n, stems) in VOLUME_GROUPS.items() for stem in stems}


@dataclass
class MixConfig:
    sr: int = 44100
    pitching: str = "normal"          # classic | normal | hard
    polish: str = "normal"            # light | normal | hard
    target_lufs: Optional[float] = None
    base_path: Optional[str] = None   # a Sparta base (backing track) to put under the remix
    base_offset: float = 0.0          # seconds into the base where bar 1 starts
    base_gain_db: float = -3.0
    base_mode: str = "replace"        # replace (mute our drums/bass/pad) | remix (keep the source percussion) | layer
    stem_gains: dict = field(default_factory=dict)
    mute: list = field(default_factory=list)
    volumes: dict = field(default_factory=dict)      # fader (VOLUME_GROUPS) → dB
    mute_groups: list = field(default_factory=list)  # faders switched off: out of the mix and the picture
    tail_s: float = 2.5
    # ── sound FX (see FX_PRESETS) ──
    fx_preset: str = "xleth"
    reverb: float = 1.0               # reverb sends ×
    delay: float = 1.0                # delay sends ×
    ott: float = 1.0                  # OTT depth ×
    pump: float = 1.0                 # sidechain pump depth ×
    drive: float = 1.0                # saturation ×
    width: float = 1.0                # master stereo width
    lofi: float = 0.0                 # 0-1: bit crush on the master
    tape_stop_end: bool = False       # the remix ends on a tape stop (a base's ending too)
    risers: bool = False              # a rising filter over the bar before each Chorus
    stutter_fills: bool = False       # the last beat before each part stutters

    @staticmethod
    def from_dict(d: dict) -> "MixConfig":
        """Defaults, then the FX preset's settings, then what was chosen by hand."""
        d = d or {}
        c = MixConfig()
        preset = d.get("fx_preset") or "xleth"
        if preset not in FX_PRESETS:
            raise ValueError(f"unknown FX preset {preset!r} (presets: {', '.join(FX_PRESETS)})")
        for k, v in FX_PRESETS[preset].items():
            setattr(c, k, v)
        for k, v in d.items():
            if hasattr(c, k):
                setattr(c, k, v)
        c.fx_preset = preset
        for k, (_d, lo, hi) in FX_AMOUNTS.items():
            setattr(c, k, float(min(hi, max(lo, float(getattr(c, k))))))
        for k in FX_SWITCHES:
            setattr(c, k, bool(getattr(c, k)))
        lo, hi = VOLUME_RANGE
        c.volumes = {g: float(min(hi, max(lo, float(v)))) for g, v in dict(c.volumes or {}).items()
                     if g in VOLUME_GROUPS and v is not None}
        c.mute_groups = [g for g in (c.mute_groups or []) if g in VOLUME_GROUPS]
        return c

    def stem_db(self, stem: str) -> float:
        """What the faders add to a stem's level."""
        return self.volumes.get(GROUP_OF_STEM.get(stem, ""), 0.0)


def muted_stems(cfg: MixConfig) -> set:
    """Stems left out of the mix (and so out of the picture): the user's mutes, plus what a base
    replaces — on a base the remix keeps its source-made percussion and bass ("remix") or not
    ("replace"), and leaves the held chords to the base."""
    muted = set(cfg.mute)
    for g in cfg.mute_groups:
        muted |= set(VOLUME_GROUPS.get(g, ("", ()))[1])
    if cfg.base_path and os.path.isfile(cfg.base_path):
        if cfg.base_mode == "replace":
            muted |= BACKING_STEMS
        elif cfg.base_mode == "remix":
            muted |= {"pad"}
    return muted


# ── voices ───────────────────────────────────────────────────────────────────


def crisp_envelope(n: int, sr: int, splice_ms: float = 40.0, offset: float = 0.8, duck_db: float = -3.0) -> np.ndarray:
    """ChorusCrisp ("Jario Style"): split at the splice point, overlap the second
    part backwards by ``offset`` of it, crossfade, and duck the second part.
    Both parts carry the same audio, so the effect is a gain envelope: full
    attack, a slight equal-power bump through the overlap, then ``duck_db``."""
    env = np.ones(n, dtype=np.float32)
    s = int(splice_ms * 1e-3 * sr)
    o = int(offset * s)
    a = max(0, s - o)
    g = dsp.db_to_gain(duck_db)
    if a >= n:
        return env
    b = min(n, s)
    k = b - a
    if k > 0:
        u = np.linspace(0.0, 1.0, k, dtype=np.float32)
        env[a:b] = np.cos(u * np.pi / 2) + g * np.sin(u * np.pi / 2)
    env[b:] = g
    return env


class VoiceRenderer:
    """Renders (and caches) the audio of every note."""

    def __init__(self, bank: SampleBank, cfg: MixConfig):
        self.bank = bank
        self.cfg = cfg
        self.sr = bank.sr
        self._shift_cache: dict[tuple, np.ndarray] = {}

    def _pitched_source(self, s: Sample) -> tuple[np.ndarray, Optional[psola.TunedSample]]:
        if s.tuned is not None:
            return s.tuned.audio, s.tuned
        return s.audio, None

    def _shifted(self, s: Sample, semis: float, length: int) -> np.ndarray:
        """Sample transposed by ``semis``, at least ``length`` samples long if sustain is needed."""
        semis = round(float(semis), 3)
        mode = self.cfg.pitching
        if s.role == "bass":
            mode = "classic"
        key = (s.id, semis, mode, length)
        hit = self._shift_cache.get(key)
        if hit is not None:
            return hit
        src, tuned = self._pitched_source(s)
        if mode == "classic" or tuned is None:
            y = dsp.varispeed(src, semis)
            if length > y.shape[0]:
                # Sustain on the classic path: PSOLA-stretch the shifted audio.
                y = psola.stretch_raw(y, self.sr, length)
        else:
            out_len = max(length, tuned.audio.shape[0])
            y = psola.shift(tuned, semis, out_len=out_len)
            if semis > 0 and dsp.rms(y) < dsp.rms(tuned.audio) * 10 ** (-9.0 / 20.0):
                # Keeping the formants left the note all but silent (a voice with too few overtones
                # for this jump): play it the way a sampler does instead, so it is still heard.
                y = dsp.varispeed(tuned.audio, semis)
                if length > y.shape[0]:
                    y = psola.stretch_raw(y, self.sr, length)
        self._shift_cache[key] = y
        return y

    def render(self, e: NoteEvent) -> Optional[np.ndarray]:
        s = self.bank.get(e.sample)
        if s is None:
            return None
        sr = self.sr
        max_len = int(max(e.max_len, 0.0) * sr)
        note_len = int(e.dur * sr)
        release = int(0.012 * sr)
        if e.oneshot or not e.pitched and e.kind in ("drum", "oneshot"):
            y = s.audio
            n = min(y.shape[0], max_len) if e.choke else y.shape[0]
            out = np.array(y[:n], dtype=np.float32)
            if n < y.shape[0]:
                out = dsp.apply_fades(out, sr, 0.0, 4.0)
            return out
        if e.pitched and s.pitched:
            want = note_len + release if not e.sustain else note_len + release
            need_len = want if e.sustain else 0
            y = self._shifted(s, e.semis, need_len)
        else:
            y = s.audio
        gate = note_len + release
        n = min(y.shape[0], gate, max_len + release if e.choke else gate)
        if n <= 0:
            return None
        out = np.array(y[:n], dtype=np.float32)
        if e.crisp:
            out *= crisp_envelope(n, sr)
        out = dsp.apply_fades(out, sr, 0.8, 8.0 if n < y.shape[0] else 3.0)
        return out


def audible_length(e: NoteEvent, s: Optional[Sample]) -> float:
    """Seconds a note is heard — the video shows the clip for the same span."""
    if s is None:
        return 0.0
    if e.oneshot or (not e.pitched and e.kind in ("drum", "oneshot")):
        return min(s.duration, e.max_len) if e.choke else s.duration
    if e.sustain:
        return min(e.dur, e.max_len)
    return min(e.dur + 0.012, s.duration if not (e.pitched and s.pitched) else max(s.duration, e.dur), e.max_len + 0.012)


# ── stems & chains ───────────────────────────────────────────────────────────


def scaled_chain(chain: list[dict], cfg: "MixConfig") -> list[dict]:
    """A stem chain with the FX amounts applied: drive scales saturation, ott the OTT depth (0: left out)."""
    out = []
    for step in chain:
        step = dict(step)
        if step["fx"] == "saturate":
            if cfg.drive <= 0:
                continue
            step["drive_db"] = step.get("drive_db", 6.0) * cfg.drive
        elif step["fx"] == "ott":
            if cfg.ott <= 0:
                continue
            step["depth"] = min(1.0, step.get("depth", 0.5) * cfg.ott)
        out.append(step)
    return out


def stem_chain(stem: str, polish: str, sr: int) -> list[dict]:
    hard = polish == "hard"
    light = polish == "light"
    if stem == "pitch":
        chain = [{"fx": "highpass", "freq": 110.0},
                 {"fx": "eq", "bands": [{"type": "peak", "freq": 3000.0, "q": 0.9, "gain": 2.5},
                                        {"type": "peak", "freq": 350.0, "q": 1.0, "gain": -2.0}]},
                 {"fx": "compressor", "threshold_db": -20.0, "ratio": 3.0, "attack_ms": 3.0, "release_ms": 60.0,
                  "makeup_db": 3.0}]
        if not light:
            chain.append({"fx": "saturate", "drive_db": 4.0 if hard else 2.0, "mode": "tanh", "mix_amount": 0.5})
        if hard:
            chain.append({"fx": "ott", "depth": 0.35, "time": 0.4})
        return chain
    if stem == "pitch_layers":
        return [{"fx": "highpass", "freq": 180.0}, {"fx": "chorus", "rate_hz": 0.9, "depth_ms": 3.0, "mix_amount": 0.35},
                {"fx": "width", "width": 1.5}]
    if stem == "pitch_soft":
        return [{"fx": "highpass", "freq": 120.0}, {"fx": "lowpass", "freq": 7000.0}]
    if stem == "pad":
        return [{"fx": "highpass", "freq": 150.0}, {"fx": "lowpass", "freq": 5500.0},
                {"fx": "chorus", "rate_hz": 0.5, "depth_ms": 5.0, "mix_amount": 0.5}, {"fx": "width", "width": 1.6}]
    if stem == "bass":
        chain = [{"fx": "highpass", "freq": 30.0}, {"fx": "lowpass", "freq": 3000.0},     # keep the voice
                 {"fx": "compressor", "threshold_db": -18.0, "ratio": 4.0, "attack_ms": 8.0, "release_ms": 90.0,
                  "makeup_db": 3.0}]
        if not light:
            chain.append({"fx": "saturate", "drive_db": 5.0 if hard else 3.0, "mode": "tanh", "mix_amount": 0.6})
        return chain
    if stem == "drums":
        chain = [{"fx": "compressor", "threshold_db": -14.0, "ratio": 3.0, "attack_ms": 10.0, "release_ms": 80.0,
                  "makeup_db": 2.0}]
        if not light:
            chain.append({"fx": "transient", "attack_db": 3.0, "sustain_db": -1.0})
            chain.append({"fx": "saturate", "drive_db": 3.0 if hard else 1.5, "mode": "soft", "mix_amount": 0.5})
        return chain
    if stem == "chorus":          # the main phrase: a voice, kept natural, pushed forward
        chain = [{"fx": "highpass", "freq": 90.0},
                 {"fx": "eq", "bands": [{"type": "peak", "freq": 3200.0, "q": 0.9, "gain": 2.0}]},
                 {"fx": "compressor", "threshold_db": -20.0, "ratio": 3.5, "attack_ms": 2.0, "release_ms": 70.0,
                  "makeup_db": 4.0}]
        if not light:
            chain.append({"fx": "saturate", "drive_db": 2.5 if hard else 1.5, "mode": "tanh", "mix_amount": 0.4})
        return chain
    if stem == "chop":
        return [{"fx": "highpass", "freq": 90.0},
                {"fx": "compressor", "threshold_db": -20.0, "ratio": 4.0, "attack_ms": 2.0, "release_ms": 70.0,
                 "makeup_db": 4.0},
                {"fx": "saturate", "drive_db": 3.0, "mode": "tanh", "mix_amount": 0.4}]
    if stem == "quotes":
        return [{"fx": "highpass", "freq": 80.0},
                {"fx": "compressor", "threshold_db": -22.0, "ratio": 3.0, "attack_ms": 5.0, "release_ms": 120.0,
                 "makeup_db": 4.0}]
    return []


STEM_SENDS = {  # reverb / delay send amounts per stem
    "pitch": (0.10, 0.06), "chorus": (0.07, 0.04), "pitch_layers": (0.18, 0.1), "pad": (0.35, 0.0),
    "chop": (0.12, 0.08),
    "quotes": (0.08, 0.05), "pitch_soft": (0.25, 0.1), "drums": (0.04, 0.0), "bass": (0.0, 0.0),
}

SIDECHAINED = {"pitch": 0.6, "chorus": 0.35, "pitch_layers": 1.0, "pad": 1.0, "bass": 0.8, "pitch_soft": 0.7}


def render_mix(arr: Arrangement, events: list[NoteEvent], bank: SampleBank, cfg: Optional[MixConfig] = None,
               progress: Progress = None, stems_dir: Optional[str] = None) -> tuple[np.ndarray, dict]:
    """Returns (stereo mix float32, info)."""
    cfg = cfg or MixConfig(pitching=arr.pitching, polish=arr.polish)
    sr = bank.sr
    total = int((arr.duration + cfg.tail_s) * sr)
    voices = VoiceRenderer(bank, cfg)
    stems: dict[str, np.ndarray] = {}
    use_base = bool(cfg.base_path) and os.path.isfile(cfg.base_path or "")
    muted = set(cfg.mute)
    stem_gains = dict(cfg.stem_gains)
    muted |= muted_stems(cfg) - set(cfg.mute)
    if use_base and cfg.base_mode == "remix":
        stem_gains.setdefault("drums", REMIX_DRUMS_DB)
        stem_gains.setdefault("bass", REMIX_BASS_DB)
    kick_times: list[float] = []

    def say(p: float, m: str) -> None:
        if progress:
            progress(p, m)

    n_ev = max(1, len(events))
    # One stem at a time — its notes rendered, its FX run, then mixed in and let go: holding every stem of a
    # long remix at once does not fit a phone.  Stems are summed in the order of their first note.
    order: list[str] = []
    by_stem: dict[str, list[NoteEvent]] = {}
    for e in events:
        if e.stem in muted:
            continue
        if e.sample == "kick":
            kick_times.append(e.t)
        if e.stem not in by_stem:
            by_stem[e.stem] = []
            order.append(e.stem)
        by_stem[e.stem].append(e)

    # Section bus FX (e.g. the Madness low-pass on the soft pitch), in section order.
    starts = arr.section_starts()
    tape_ranges = []
    bus_fx: list[tuple[str, int, int, dict]] = []
    for si, sec in enumerate(arr.sections):
        t0 = starts[si]
        t1 = t0 + sec.bars * arr.bar_s
        for spec in sec.fx:
            spec = dict(spec)
            target = spec.pop("track", "*")
            name = spec.pop("fx")
            if name == "tape_stop":
                tape_ranges.append((t0, t1, spec))
                continue
            bus_fx.append((target, int(t0 * sr), min(total, int(t1 * sr)), dict(fx=name, **spec)))

    sidechain = None
    if kick_times and cfg.polish != "light" and cfg.pump > 0:
        depth = (7.0 if cfg.polish == "hard" else 3.5) * cfg.pump
        sidechain = fx.sidechain_env(total, sr, kick_times, depth_db=depth, release_ms=150.0)
    rev_bus = np.zeros((total, 2), dtype=np.float32)
    dly_bus = np.zeros((total, 2), dtype=np.float32)
    mix = np.zeros((total, 2), dtype=np.float32)
    stem_names: list[str] = []
    done = 0
    for name in order:
        buf = None
        rng = None                                   # where the stem has content (saves scanning the buffer)
        for e in by_stem.pop(name):
            done += 1
            y = voices.render(e)
            if y is None or y.size == 0:
                continue
            if buf is None:
                buf = np.zeros((total, 2), dtype=np.float32)
            g = dsp.db_to_gain(e.gain_db)
            gl, gr = dsp.pan_gains(e.pan)
            s0 = int(round(e.t * sr))
            seg = y * g
            e_end = min(total, s0 + seg.shape[0])
            if e_end > s0:
                k = e_end - s0
                buf[s0:e_end, 0] += seg[:k] * gl * math.sqrt(2)
                buf[s0:e_end, 1] += seg[:k] * gr * math.sqrt(2)
                rng = [s0, e_end] if rng is None else [min(rng[0], s0), max(rng[1], e_end)]
            if done % 200 == 0:
                say(0.05 + 0.6 * done / n_ev, f"rendering {name}")
        if buf is None or rng is None:
            continue
        for target, a, b, step in bus_fx:
            if target not in ("*", name):
                continue
            seg = buf[a:b]
            if seg.shape[0] < 64:
                continue
            buf[a:b] = fx.apply_chain(seg, sr, [step])
        # Only process where the stem is active (plus room for effect tails).
        a = max(0, rng[0] - int(0.25 * sr))
        b = min(total, rng[1] + int(1.5 * sr))
        y = np.zeros_like(buf)
        y[a:b] = dsp.fit_length(fx.apply_chain(buf[a:b], sr, scaled_chain(stem_chain(name, cfg.polish, sr), cfg)),
                                b - a)
        del buf
        if sidechain is not None and name in SIDECHAINED:
            amt = SIDECHAINED[name]
            y = fx.apply_env(y, 1.0 - amt * (1.0 - sidechain))
        lvl = STEM_LEVEL_DB.get(name, 0.0) + float(stem_gains.get(name, 0.0)) + cfg.stem_db(name)
        y *= dsp.db_to_gain(lvl)
        rv, dl = STEM_SENDS.get(name, (0.0, 0.0))
        if cfg.polish == "hard":
            dl *= 1.6
        if cfg.polish == "light":
            rv *= 0.6
            dl = 0.0
        rv *= cfg.reverb
        dl *= cfg.delay
        if rv:
            rev_bus += y * rv
        if dl:
            dly_bus += y * dl
        mix += y
        if stems_dir:
            os.makedirs(stems_dir, exist_ok=True)
            dsp.write_wav(os.path.join(stems_dir, f"{name}.wav"), np.clip(y, -1, 1), sr)
        del y
        stem_names.append(name)
    stem_names.sort()
    if stems_dir and os.path.isdir(stems_dir):
        # Stems from an earlier render that this one no longer has must not linger in the folder.
        for name in set(STEM_LEVEL_DB) - set(stem_names):
            old = os.path.join(stems_dir, f"{name}.wav")
            if os.path.isfile(old):
                os.remove(old)
    say(0.7, "reverb & delay")
    if np.any(rev_bus):
        wet = fx.reverb(dsp.to_mono(rev_bus), sr, mix_amount=1.0, decay_s=1.4, predelay_ms=15.0, damping=0.55,
                        lowcut=250.0)
        wet = wet[:total] - dsp.to_stereo(dsp.to_mono(rev_bus)) * 0.5  # keep only the wet part
        mix += dsp.fit_length(wet, total)
    if np.any(dly_bus):
        wet = fx.delay(dsp.to_mono(dly_bus), sr, time_s=arr.step_s * 3, feedback=0.35, mix_amount=1.0,
                       pingpong=True, lowpass_hz=5000.0)
        wet = wet[:total] - dsp.to_stereo(dsp.to_mono(dly_bus))
        mix += dsp.fit_length(wet, total)

    if use_base:
        say(0.75, "mixing the base")
        from . import ffmpeg as ff
        base = ff.decode_audio(cfg.base_path, sr=sr, mono=False)
        off = int(cfg.base_offset * sr)
        base = base[off:] if off >= 0 else np.pad(base, ((-off, 0), (0, 0)))
        base = dsp.fit_length(base, total) * dsp.db_to_gain(cfg.base_gain_db)
        mix += base

    if cfg.tape_stop_end and arr.sections and not any(t1 >= arr.duration - 1e-6 for _t0, t1, _s in tape_ranges):
        tape_ranges.append((starts[-1], arr.duration, {"duration_s": min(0.9, arr.sections[-1].bars * arr.bar_s)}))
    if cfg.risers or cfg.stutter_fills:
        say(0.78, "risers & fills")
        transitions(mix, sr, arr, starts, risers=cfg.risers, stutters=cfg.stutter_fills)
    for t0, t1, spec in tape_ranges:
        a = int(max(t0, t1 - float(spec.get("duration_s", 0.8)) - 0.05) * sr)
        b = min(total, int(t1 * sr))
        if b - a > 64:
            mix[a:b] = fx.tape_stop(mix[a:b], sr, duration_s=(b - a) / sr, curve=float(spec.get("curve", 1.5)))
            mix[b:] *= 0.0 if spec.get("silence_after", True) and t1 >= arr.duration - 1e-6 else 1.0

    say(0.8, "mastering")
    mix = master(mix, sr, cfg.polish, cfg.target_lufs, cfg)
    info = {"lufs": round(dsp.loudness_lufs(mix, sr), 2), "peak_db": round(float(dsp.gain_to_db(dsp.peak(mix))), 2),
            "duration": round(mix.shape[0] / sr, 3), "stems": stem_names}
    say(1.0, "mix done")
    return mix.astype(np.float32), info


def transitions(mix: np.ndarray, sr: int, arr: Arrangement, starts: list, risers: bool = False,
                stutters: bool = False) -> None:
    """Build-ups at the part boundaries: a rising high-pass over the bar before each Chorus (risers), the
    last beat before a new part stuttered in 16ths (fills).  In place."""
    bar = int(arr.bar_s * sr)
    beat = bar // 4
    for i, sec in enumerate(arr.sections):
        if i == 0:
            continue
        t = int(starts[i] * sr)
        if risers and sec.kind in ("chorus", "epicness") and t - bar > 0:
            a = t - bar
            mix[a:t] = dsp.fit_length(fx.filter_sweep(mix[a:t], sr, kind="highpass", f_start=60.0, f_end=1400.0),
                                      t - a)
        if stutters and t - beat > 0 and arr.sections[i - 1].kind not in ("intro", "ending"):
            a = t - beat
            piece = fx.stutter(mix[a:t], sr, slice_s=arr.step_s, repeats=4, decay=0.9)
            mix[a:t] = dsp.fit_length(piece, t - a)


def master(mix: np.ndarray, sr: int, polish: str = "normal", target_lufs: Optional[float] = None,
           cfg: Optional[MixConfig] = None) -> np.ndarray:
    cfg = cfg or MixConfig(polish=polish)
    target = POLISH_TARGET_LUFS.get(polish, -10.0) if target_lufs is None else float(target_lufs)
    y = fx.eq(mix, sr, [{"type": "highpass", "freq": 25.0, "q": 0.7},
                        {"type": "lowshelf", "freq": 90.0, "q": 0.7, "gain": 1.0},
                        {"type": "highshelf", "freq": 9000.0, "q": 0.7, "gain": 1.5 if polish != "light" else 0.5}])
    ott_depth, drive_db, sat_mix, width = {"hard": (0.45, 3.0, 0.5, 1.15), "normal": (0.22, 1.5, 0.35, 1.0)}.get(
        polish, (0.0, 0.0, 0.0, 1.0))
    if ott_depth * cfg.ott > 0:
        y = fx.ott(y, sr, depth=min(0.9, ott_depth * cfg.ott), time=0.45 if polish == "hard" else 0.5)
    if drive_db * cfg.drive > 0:
        y = fx.saturate(y, drive_db * cfg.drive, "tanh", mix_amount=sat_mix)
    if abs(width * cfg.width - 1.0) > 1e-3:
        y = fx.stereo_width(y, width * cfg.width)
    if cfg.lofi > 0:
        y = fx.bitcrush(y, sr, bits=int(round(14 - 8 * cfg.lofi)), downsample=1 + int(round(4 * cfg.lofi)),
                        mix_amount=0.35 + 0.5 * cfg.lofi)
        y = fx.eq(y, sr, [{"type": "lowpass", "freq": 12000.0 - 7000.0 * cfg.lofi, "q": 0.7}])
    y = fx.compressor(y, sr, threshold_db=-16.0, ratio=2.0, attack_ms=20.0, release_ms=150.0, knee_db=6.0)
    # Loudness: bring the mix to the target, then let the limiter catch the peaks.
    for _ in range(2):
        cur = dsp.loudness_lufs(y, sr)
        if cur <= -69.0:
            break
        y = y * dsp.db_to_gain(float(np.clip(target - cur, -20.0, 24.0)))
        y = fx.limiter(y, sr, ceiling_db=-1.0, release_ms=80.0, lookahead_ms=3.0)
    return np.clip(y, -1.0, 1.0).astype(np.float32)
