"""Turn analysis candidates into a playable Sparta sample bank.

Every sample is cut from the source audio (so its video clip is known) and
processed the way remixers prepare them by hand:

* pitch1/2/3 — held vowels hard-tuned to D (the key of the classic bases)
* bass       — the main pitch dropped to D2, low-passed and saturated
* kick       — a thump from the source, pitched down for body, with a pitch
               sweep for punch and the original transient on top
* snare/clap — a noisy "bang" from the source, EQ'd for body + snap
* hat_closed / hat_open — sibilants or cymbal hiss, high-passed
* crash      — a loud noisy stretch with a long reverb tail
* quote1..3  — speech phrases (intro, fills, ending)
* phrase + syl1..N — the main phrase and its syllables (DunDunDenDen chops)
* word_a / word_b  — call & response words for the Madness
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .audio import dsp, fx
from .audio.analysis import Analysis, Candidate, similar_word, split_syllables
from .audio.pitch import midi_to_hz, hz_to_midi, pitch_class, note_name
from .audio.psola import TunedSample, tune_to_note, find_marks

PITCH_ROLES = ("pitch1", "pitch2", "pitch3")


@dataclass
class Sample:
    id: str
    role: str                  # pitch | bass | kick | snare | hat_closed | hat_open | crash | quote | phrase | syllable | word
    label: str
    src_start: float           # source time range (drives the video clip)
    src_end: float
    audio: np.ndarray
    sr: int
    root_midi: float = float("nan")      # note the processed audio sits on
    tuned: Optional[TunedSample] = None  # formant-preserving transposition source
    video_rate: float = 1.0              # source seconds per sample second
    meta: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.audio.shape[0] / self.sr

    @property
    def pitched(self) -> bool:
        return np.isfinite(self.root_midi)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "role": self.role, "label": self.label,
            "src_start": round(self.src_start, 4), "src_end": round(self.src_end, 4),
            "duration": round(self.duration, 4),
            "root_midi": None if not self.pitched else round(float(self.root_midi), 3),
            "root_note": None if not self.pitched else note_name(self.root_midi),
            "video_rate": round(self.video_rate, 4),
            "meta": {k: v for k, v in self.meta.items() if isinstance(v, (int, float, str, bool, type(None)))},
        }


@dataclass
class SampleConfig:
    key: str = "D"                   # pitch class every pitch sample is tuned to
    pitch_octave: Optional[int] = None  # force D3/D4/D5; None = nearest to the voice
    flatten: float = 1.0             # 1 = dead-straight note, 0 = keep intonation
    bass_octave: int = 2             # bass root = D2
    max_quotes: int = 3
    selections: dict = field(default_factory=dict)  # role -> candidate index or {"start":…, "end":…}

    @staticmethod
    def from_dict(d: dict) -> "SampleConfig":
        c = SampleConfig()
        for k, v in (d or {}).items():
            if hasattr(c, k):
                setattr(c, k, v)
        return c


# ── helpers ──────────────────────────────────────────────────────────────────


def _cut(x: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    a = max(0, int(round(start * sr)))
    b = min(x.shape[0], int(round(end * sr)))
    return np.array(x[a:b], dtype=np.float32) if b > a else np.zeros(int(0.05 * sr), dtype=np.float32)


def _trim_silence(x: np.ndarray, sr: int, thresh_db: float = -45.0, pad_ms: float = 4.0) -> tuple[np.ndarray, int]:
    """Trim leading/trailing silence relative to the clip peak; returns (clip, samples cut at start)."""
    if x.size == 0:
        return x, 0
    env = dsp.envelope(x, sr, 1.0, 20.0, mode="peak", block=16)
    pk = float(env.max())
    if pk <= 1e-7:
        return x, 0
    above = np.flatnonzero(env > pk * dsp.db_to_gain(thresh_db))
    if above.size == 0:
        return x, 0
    pad = int(pad_ms * 1e-3 * sr)
    a = max(0, int(above[0]) - pad)
    b = min(x.shape[0], int(above[-1]) + pad)
    return x[a:b], a


def _pick(cands: list[Candidate], sel, avoid: list[tuple[float, float]] = (), min_gap: float = 0.0) -> Optional[Candidate]:
    """Selected candidate: an explicit index, a manual range, or the best one clear of `avoid`."""
    if isinstance(sel, dict) and "start" in sel and "end" in sel:
        kind = cands[0].kind if cands else "manual"
        return Candidate(kind, float(sel["start"]), float(sel["end"]), 1.0, {"manual": True})
    if isinstance(sel, int) and 0 <= sel < len(cands):
        return cands[sel]
    for c in cands:
        if all(c.end + min_gap <= a or c.start >= b + min_gap for a, b in avoid):
            return c
    return cands[0] if cands else None


def _clear_of(c: Candidate, used: list[tuple[float, float]], gap: float) -> bool:
    return all(c.end + gap <= a or c.start >= b + gap for a, b in used)


def _target_midi(f0: float, key_pc: int, octave: Optional[int]) -> int:
    if octave is not None:
        return 12 * (octave + 1) + key_pc
    m = hz_to_midi(f0) if np.isfinite(f0) and f0 > 0 else 62.0
    best = None
    for cand in range(12 * 3 + key_pc, 12 * 7 + key_pc, 12):  # D2..D5 for key D
        if best is None or abs(cand - m) < abs(best - m):
            best = cand
    return best


# ── designers ────────────────────────────────────────────────────────────────


def make_pitch(x: np.ndarray, sr: int, cand: Candidate, sid: str, cfg: SampleConfig) -> Sample:
    seg = _cut(x, sr, cand.start, cand.end)
    seg = dsp.highpass(seg, sr, 60.0, order=2)
    marks = find_marks(seg, sr)
    vper = marks.period[marks.voiced]
    f0 = float(sr / np.median(vper)) if vper.size else float(cand.info.get("f0", float("nan")))
    target = _target_midi(f0, pitch_class(cfg.key), cfg.pitch_octave)
    ts = tune_to_note(seg, sr, midi_to_hz(target), flatten=float(cfg.flatten), marks=marks)
    y = dsp.normalize_rms(ts.audio, -16.0, -1.0)
    scale = (dsp.rms(y) / max(dsp.rms(ts.audio), 1e-9))
    ts = TunedSample(y, sr, ts.f0, ts.marks, ts.source_f0)
    meta = {"source_f0": round(f0, 2) if np.isfinite(f0) else None,
            "source_note": note_name(hz_to_midi(f0)) if np.isfinite(f0) else None,
            "shift_semitones": round(target - hz_to_midi(f0), 2) if np.isfinite(f0) else None,
            "score": round(float(cand.score), 4), "gain": round(float(scale), 4)}
    return Sample(sid, "pitch", f"{sid} ({note_name(target)})", cand.start, cand.end, y, sr,
                  float(target), ts, 1.0, meta)


def make_bass(p: Sample, cfg: SampleConfig) -> Sample:
    sr = p.sr
    target = 12 * (cfg.bass_octave + 1) + pitch_class(cfg.key)
    shift = target - p.root_midi
    y = dsp.varispeed(p.audio, shift)
    y = dsp.lowpass(y, sr, 700.0, order=4)
    y = dsp.highpass(y, sr, 28.0, order=2)
    y = fx.saturate(y, 6.0, "tanh")
    y = dsp.lowpass(y, sr, 1800.0, order=2)
    y = dsp.declick(dsp.normalize_rms(y, -15.0, -1.0), sr, 2.0)
    return Sample("bass", "bass", f"bass ({note_name(target)})", p.src_start, p.src_end, y, sr,
                  float(target), None, 2.0 ** (shift / 12.0), {"from": p.id})


def make_kick(x: np.ndarray, sr: int, cand: Candidate) -> Sample:
    seg = _cut(x, sr, cand.start, cand.start + 0.45)
    cen = float(cand.info.get("centroid", 300.0))
    low = float(cand.info.get("low", 0.0))
    # Pitch the thump down until its energy sits in the kick range (real kicks barely move).
    shift = 0.0 if (low > 0.6 and cen < 200) else float(np.clip(-12.0 * math.log2(max(cen, 60.0) / 110.0), -24.0, 0.0))
    body = dsp.varispeed(seg, shift) if shift < -0.5 else seg.copy()
    body = body[: int(0.32 * sr)]
    body = fx.pitch_sweep(body, sr, 7.0, 0.0, 45.0)          # punch: glide down onto the body
    body = dsp.lowpass(body, sr, 180.0, order=4)
    body = dsp.highpass(body, sr, 30.0, order=2)
    click = dsp.highpass(seg[: int(0.015 * sr)], sr, 1500.0, order=2)
    n = body.shape[0]
    y = body * dsp.exp_decay_env(n, sr, 300.0)
    y = dsp.normalize_peak(y, -1.0)
    ck = dsp.normalize_peak(click, -10.0) * dsp.exp_decay_env(click.shape[0], sr, 12.0)
    y[: ck.shape[0]] += ck
    y = fx.saturate(y, 5.0, "tanh")
    y = dsp.apply_fades(y, sr, 0.3, 8.0)
    y = dsp.normalize_peak(y, -1.0)
    return Sample("kick", "kick", "kick", cand.start, cand.start + 0.3, y, sr,
                  meta={"shift_semitones": round(shift, 2), "score": round(float(cand.score), 4)})


def make_snare(x: np.ndarray, sr: int, cand: Candidate, clap: bool = False) -> Sample:
    seg = _cut(x, sr, cand.start, cand.start + 0.3)
    y = dsp.highpass(seg, sr, 160.0, order=2)
    y = fx.eq(y, sr, [{"type": "peak", "freq": 220.0, "q": 1.0, "gain": 3.0},
                      {"type": "highshelf", "freq": 5000.0, "q": 0.7, "gain": 4.0}])
    y = fx.transient(y, sr, 6.0, -2.0)
    y = y[: int(0.24 * sr)] * dsp.exp_decay_env(min(y.shape[0], int(0.24 * sr)), sr, 220.0)
    if clap:  # the classic clap trick: a few retriggers of the same burst
        n = y.shape[0] + int(0.03 * sr)
        c = np.zeros(n, dtype=np.float32)
        for k, (d, g) in enumerate(((0.0, 0.7), (0.011, 0.8), (0.023, 1.0))):
            dsp.mix_into(c, y, int(d * sr), g)
        y = c
    y = fx.saturate(y, 3.0, "soft")
    y = dsp.apply_fades(y, sr, 0.3, 10.0)
    y = dsp.normalize_peak(y, -1.0)
    sid = "clap" if clap else "snare"
    return Sample(sid, "snare", sid, cand.start, cand.start + 0.25, y, sr, meta={"score": round(float(cand.score), 4)})


def make_hat(x: np.ndarray, sr: int, cand: Candidate, open_hat: bool) -> Sample:
    length = 0.22 if open_hat else 0.05
    seg = _cut(x, sr, cand.start, max(cand.end, cand.start + length + 0.02))
    if not open_hat and seg.shape[0] > int(0.06 * sr):
        # Start the closed hat at the loudest part of the hiss.
        env = dsp.envelope(seg, sr, 1.0, 10.0, mode="peak", block=16)
        a = max(0, int(np.argmax(env)) - int(0.003 * sr))
        seg = seg[a:]
    cen = float(cand.info.get("centroid", 5000.0))
    hp = float(np.clip(0.6 * cen, 2500.0, 7000.0))
    y = dsp.highpass(seg, sr, hp, order=4)
    y = fx.eq(y, sr, [{"type": "highshelf", "freq": 8000.0, "q": 0.7, "gain": 3.0}])
    n = min(y.shape[0], int((length + 0.02) * sr))
    y = y[:n] * dsp.exp_decay_env(n, sr, length * 1000.0)
    y = dsp.apply_fades(y, sr, 0.2, 5.0)
    y = dsp.normalize_peak(y, -1.0)
    sid = "hat_open" if open_hat else "hat_closed"
    return Sample(sid, sid, "open hat" if open_hat else "closed hat", cand.start, cand.start + length, y, sr,
                  meta={"highpass": round(hp), "score": round(float(cand.score), 4)})


def make_crash(x: np.ndarray, sr: int, cand: Candidate) -> Sample:
    seg = _cut(x, sr, cand.start, cand.start + max(0.25, min(cand.duration, 0.9)))
    y = dsp.highpass(seg, sr, 1500.0, order=2)
    y = y * dsp.exp_decay_env(y.shape[0], sr, 900.0)
    wet = fx.reverb(y, sr, mix_amount=0.8, decay_s=1.8, predelay_ms=5.0, damping=0.3, lowcut=1500.0)
    y = dsp.to_mono(wet)
    y = y * dsp.exp_decay_env(y.shape[0], sr, 1900.0)
    y = dsp.apply_fades(y, sr, 0.5, 30.0)
    y = dsp.normalize_peak(y, -1.0)
    return Sample("crash", "crash", "crash", cand.start, cand.end, y, sr, meta={"score": round(float(cand.score), 4)})


def make_speech(x: np.ndarray, sr: int, cand: Candidate, sid: str, role: str, label: str,
                fade_ms: float = 5.0) -> Sample:
    seg = _cut(x, sr, cand.start, cand.end)
    seg = dsp.highpass(seg, sr, 70.0, order=2)
    seg, cut = _trim_silence(seg, sr, -42.0, 6.0)
    y = dsp.apply_fades(seg, sr, fade_ms, fade_ms * 2)
    y = dsp.normalize_rms(y, -17.0, -1.0)
    start = cand.start + cut / sr
    return Sample(sid, role, label, start, start + y.shape[0] / sr, y, sr, meta={"score": round(float(cand.score), 4)})


def tune_speech(s: Sample, cfg: SampleConfig) -> Sample:
    """Give a word/syllable a D-tuned version for pitched chops (keeps the raw one too)."""
    marks = find_marks(s.audio, s.sr)
    vper = marks.period[marks.voiced]
    if vper.size < 4:
        return s
    f0 = float(s.sr / np.median(vper))
    target = _target_midi(f0, pitch_class(cfg.key), cfg.pitch_octave)
    ts = tune_to_note(s.audio, s.sr, midi_to_hz(target), flatten=float(cfg.flatten), marks=marks)
    s.tuned = ts
    s.root_midi = float(target)
    s.meta["tuned_to"] = note_name(target)
    return s


# ── bank ─────────────────────────────────────────────────────────────────────


@dataclass
class SampleBank:
    sr: int
    samples: dict[str, Sample] = field(default_factory=dict)

    def get(self, sid: str) -> Optional[Sample]:
        return self.samples.get(sid)

    def first(self, *ids: str) -> Optional[Sample]:
        for i in ids:
            s = self.samples.get(i)
            if s is not None:
                return s
        return None

    def by_role(self, role: str) -> list[Sample]:
        return [s for s in self.samples.values() if s.role == role]

    def syllables(self) -> list[Sample]:
        out = [s for s in self.samples.values() if s.role == "syllable"]
        return sorted(out, key=lambda s: s.src_start)

    def to_dict(self) -> dict:
        return {k: v.to_dict() for k, v in self.samples.items()}

    def export(self, folder: str, source_path: Optional[str] = None, video: bool = True) -> list[str]:
        """Write every sample as WAV (+ its cut video clip) — a ready-to-use sample pack."""
        from . import ffmpeg as ff
        os.makedirs(folder, exist_ok=True)
        written = []
        for sid, s in self.samples.items():
            wav = os.path.join(folder, f"{sid}.wav")
            dsp.write_wav(wav, s.audio, s.sr)
            written.append(wav)
            if video and source_path:
                clip = os.path.join(folder, f"{sid}.mp4")
                dur = max(0.05, (s.src_end - s.src_start))
                try:
                    ff.cut_clip(source_path, s.src_start, dur, clip, audio_wav=wav)
                    written.append(clip)
                except ff.FFmpegError:
                    pass
        return written


def build_bank(x: np.ndarray, sr: int, an: Analysis, cfg: Optional[SampleConfig] = None,
               progress=None) -> SampleBank:
    cfg = cfg or SampleConfig()
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    sel = cfg.selections or {}
    bank = SampleBank(sr)
    C = an.candidates

    def step(p: float, msg: str) -> None:
        if progress:
            progress(p, msg)

    # ── pitches ──
    used: list[tuple[float, float]] = []
    pitches = C.get("pitch", [])
    for i, sid in enumerate(PITCH_ROLES):
        # Second/third pitch: prefer another moment of the source (another word,
        # speaker or note) so the call & response between slots is audible.
        cand = _pick(pitches, sel.get(sid), used, 2.0) if i > 0 else None
        if cand is None or (i > 0 and not _clear_of(cand, used, 2.0)):
            cand = _pick(pitches, sel.get(sid), used, 0.3)
        if cand is None:
            # No voiced material at all: fall back to the loudest word/quote so the remix still has a "pitch".
            cand = _pick(C.get("word", []) or C.get("quote", []), None, used)
        if cand is None:
            continue
        if i > 0 and cand in [bank.samples[k].meta.get("_cand") for k in bank.samples]:
            continue
        step(0.05 + 0.1 * i, f"tuning {sid} to {cfg.key}")
        s = make_pitch(x, sr, cand, sid, cfg)
        s.meta["_cand"] = cand
        bank.samples[sid] = s
        used.append((cand.start, cand.end))
    pitched = [bank.samples[k] for k in PITCH_ROLES if k in bank.samples]
    if pitched:
        step(0.35, "building bass")
        # The lowest tuned pitch needs the smallest drop to reach the bass octave,
        # so it keeps the most body and the fewest resampling artefacts.
        src = bank.samples.get(sel.get("bass")) if isinstance(sel.get("bass"), str) else None
        if src is None or not src.pitched:
            src = min(pitched, key=lambda smp: (smp.root_midi, smp.id))
        bank.samples["bass"] = make_bass(src, cfg)

    # ── percussion ──
    step(0.45, "designing percussion")
    kick_c = _pick(C.get("kick", []) or C.get("hit", []), sel.get("kick"))
    snare_c = _pick(C.get("snare", []) or C.get("hit", []), sel.get("snare"),
                    [(kick_c.start, kick_c.end)] if kick_c else [])
    if kick_c:
        bank.samples["kick"] = make_kick(x, sr, kick_c)
    if snare_c:
        bank.samples["snare"] = make_snare(x, sr, snare_c)
        bank.samples["clap"] = make_snare(x, sr, snare_c, clap=True)
    hats = C.get("hat", [])
    hc = _pick(hats, sel.get("hat_closed"))
    if hc is None:
        hc = snare_c
    if hc:
        bank.samples["hat_closed"] = make_hat(x, sr, hc, open_hat=False)
    longest = sorted(hats, key=lambda c: -(c.score * min(c.duration, 0.3)))
    ho = _pick(longest, sel.get("hat_open"), [(hc.start, hc.end)] if hc else []) or hc
    if ho:
        bank.samples["hat_open"] = make_hat(x, sr, ho, open_hat=True)
    cr = _pick(C.get("crash", []), sel.get("crash")) or ho or snare_c
    if cr:
        bank.samples["crash"] = make_crash(x, sr, cr)

    # ── quotes, phrase, syllables, words ──
    step(0.65, "cutting quotes")
    quotes = C.get("quote", [])
    q_used: list[tuple[float, float]] = []
    for i in range(cfg.max_quotes):
        sid = f"quote{i + 1}"
        qc = _pick(quotes, sel.get(sid), q_used, 0.1)
        if qc is None or (i > 0 and (qc.start, qc.end) in q_used):
            break
        bank.samples[sid] = make_speech(x, sr, qc, sid, "quote", f"quote {i + 1}")
        q_used.append((qc.start, qc.end))
    phrase_c = _pick(quotes, sel.get("phrase"))
    if phrase_c is not None:
        ph = make_speech(x, sr, phrase_c, "phrase", "phrase", "main phrase")
        bank.samples["phrase"] = ph
        step(0.75, "chopping syllables")
        for j, (a, b) in enumerate(_syllable_ranges(ph, sr)):
            c = Candidate("syllable", ph.src_start + a, ph.src_start + b, 1.0)
            syl = make_speech(x, sr, c, f"syl{j + 1}", "syllable", f"syllable {j + 1}", fade_ms=3.0)
            bank.samples[syl.id] = tune_speech(syl, cfg)
    words = C.get("word", [])
    wa = _pick(words, sel.get("word_a"))
    if wa is not None:
        step(0.85, "pairing Madness words")
        wb_sel = sel.get("word_b")
        wb = _pick(words, wb_sel) if wb_sel is not None else (similar_word(words, wa) or _pick(words, None, [(wa.start, wa.end)]))
        bank.samples["word_a"] = tune_speech(make_speech(x, sr, wa, "word_a", "word", "word 1 (call)", 3.0), cfg)
        if wb is not None:
            bank.samples["word_b"] = tune_speech(make_speech(x, sr, wb, "word_b", "word", "word 2 (response)", 3.0), cfg)
    for s in bank.samples.values():
        s.meta.pop("_cand", None)
    step(1.0, "sample bank ready")
    return bank


def _syllable_ranges(ph: Sample, sr: int, max_syl: int = 8) -> list[tuple[float, float]]:
    """Syllable boundaries (seconds, relative to the phrase) from energy valleys."""
    y = ph.audio
    hop = 256
    frame = 1024
    if y.shape[0] < frame * 2:
        return [(0.0, y.shape[0] / sr)]
    fr = dsp.block_features(y, frame, hop)
    db = 20 * np.log10(np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5.0, mode="same")
    n = db.shape[0]
    w = max(2, int(0.12 * sr / hop))
    cuts = []
    for m in range(1, n - 1):
        if db[m] <= db[m - 1] and db[m] <= db[m + 1]:
            left = db[max(0, m - w):m].max(initial=db[m])
            right = db[m + 1:m + 1 + w].max(initial=db[m])
            if min(left, right) - db[m] >= 4.0:
                cuts.append(m)
    min_len = int(0.1 * sr / hop)
    bounds = [0]
    for c in cuts:
        if c - bounds[-1] >= min_len:
            bounds.append(c)
    if n - bounds[-1] < min_len and len(bounds) > 1:
        bounds.pop()
    bounds.append(n)
    segs = [((a * hop) / sr, (b * hop + frame) / sr) for a, b in zip(bounds[:-1], bounds[1:])]
    if len(segs) == 1:
        # One long syllable: split into beats of ~0.25 s so the chop still works.
        total = y.shape[0] / sr
        k = int(np.clip(round(total / 0.25), 2, 4))
        segs = [(total * i / k, total * (i + 1) / k) for i in range(k)]
    # Keep the loudest ones if there are too many.
    if len(segs) > max_syl:
        energy = [float(np.mean(db[int(a * sr / hop):max(int(a * sr / hop) + 1, int(b * sr / hop))])) for a, b in segs]
        keep = sorted(np.argsort(energy)[-max_syl:])
        segs = [segs[i] for i in keep]
    return [(a, min(b, y.shape[0] / sr)) for a, b in segs]
