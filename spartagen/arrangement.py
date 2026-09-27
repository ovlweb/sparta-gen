"""Sparta Remix structure: base variants, section templates and the note compiler.

A remix is a list of sections (Intro, Chorus, DunDunDenDen, Epicness,
Awesomeness, Madness, Execution, Ending …).  Each section has tracks; each
track plays a pattern from the wiki library (or typed by the user) with one
or more samples from the bank.  ``compile_events`` turns that into a flat,
sample-accurate list of note events used by both the audio and the video
renderers, so picture and sound always agree.

Harmony follows the classic D bases: progression "0 1 -2 1" (D, Eb, C, Eb)
with one chord per half bar.  Semitone patterns already spell it out; index
patterns (the standard Chorus, Madness call & response) follow it via their
slots.  Picking another "Progression Twist" re-targets every semitone
pattern written over the original progression.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from typing import Optional

from .patterns import library as lib
from .patterns.notation import (ORIGINAL_PROGRESSION, ParsedPattern, parse, parse_progression, retarget,
                                STEPS_PER_BAR)


# ── Spec types ───────────────────────────────────────────────────────────────


@dataclass
class TrackSpec:
    id: str
    kind: str                                   # pitch | bass | drum | oneshot | chop | words
    pattern: str = ""                           # library id, "text:<notation>", "drum:<groove>:<part>", "bass:<name>"
    mode: str = "auto"
    sample: str = ""                            # sample for semitone patterns / drums / oneshots
    slots: dict = field(default_factory=dict)   # index digit -> sample id or {"sample": id, "offset": semis}
    octave: int = 0
    transpose: int = 0
    gain_db: float = 0.0
    pan: float = 0.0
    crisp: bool = False                         # ChorusCrisp / Jario pluck
    sustain: bool = False                       # stretch notes longer than the sample
    choke: bool = True                          # a new note cuts the last one on this track
    oneshot: bool = False                       # play the whole sample whatever the note length
    pitched: bool = True
    follow: str = ""                            # "progression" | "@<track id>" (copy that track's onsets)
    start_bar: float = 0.0
    end_bar: Optional[float] = None
    visual: str = "auto"                        # layout cell hint (see render_video.CELLS)
    flip: str = "alternate"                     # none | alternate | rotate
    stem: str = ""
    muted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "TrackSpec":
        t = TrackSpec(id=d["id"], kind=d["kind"])
        for k, v in d.items():
            if hasattr(t, k):
                setattr(t, k, v)
        return t


@dataclass
class SectionSpec:
    kind: str
    bars: int
    tracks: list[TrackSpec]
    name: str = ""
    layout: str = "grid3"                       # main | full | split2 | grid3 | grid4
    fx: list = field(default_factory=list)      # bus FX over the section
    progression: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tracks"] = [t.to_dict() for t in self.tracks]
        return d

    @staticmethod
    def from_dict(d: dict) -> "SectionSpec":
        return SectionSpec(kind=d["kind"], bars=int(d["bars"]), tracks=[TrackSpec.from_dict(t) for t in d["tracks"]],
                           name=d.get("name", ""), layout=d.get("layout", "grid3"), fx=list(d.get("fx", [])),
                           progression=d.get("progression"))


@dataclass
class Arrangement:
    title: str
    variant: str
    bpm: float = 140.0
    key: str = "D"
    progression: str = ORIGINAL_PROGRESSION
    pitching: str = "normal"                    # classic | normal | hard
    polish: str = "normal"                      # light | normal | hard
    sections: list[SectionSpec] = field(default_factory=list)

    @property
    def step_s(self) -> float:
        return 60.0 / self.bpm / 4.0

    @property
    def bar_s(self) -> float:
        return self.step_s * STEPS_PER_BAR

    @property
    def total_bars(self) -> int:
        return sum(s.bars for s in self.sections)

    @property
    def duration(self) -> float:
        return self.total_bars * self.bar_s

    def section_starts(self) -> list[float]:
        out, t = [], 0.0
        for s in self.sections:
            out.append(t)
            t += s.bars * self.bar_s
        return out

    def to_dict(self) -> dict:
        return {"title": self.title, "variant": self.variant, "bpm": self.bpm, "key": self.key,
                "progression": self.progression, "pitching": self.pitching, "polish": self.polish,
                "sections": [s.to_dict() for s in self.sections],
                "duration": round(self.duration, 3), "total_bars": self.total_bars}

    @staticmethod
    def from_dict(d: dict) -> "Arrangement":
        return Arrangement(title=d.get("title", "Sparta Remix"), variant=d.get("variant", "custom"),
                           bpm=float(d.get("bpm", 140.0)), key=d.get("key", "D"),
                           progression=d.get("progression", ORIGINAL_PROGRESSION),
                           pitching=d.get("pitching", "normal"), polish=d.get("polish", "normal"),
                           sections=[SectionSpec.from_dict(s) for s in d.get("sections", [])])


# ── Section templates ────────────────────────────────────────────────────────

SLOTS_12 = {"1": "pitch1", "2": "pitch2", "3": "pitch3", "4": "pitch1"}
#: The Chorus plays the main source clip cut in two: 1 = first part, 2 = second part.
SLOTS_CHORUS = {"1": "chorus_a", "2": "chorus_b", "3": "pitch3", "4": "pitch1"}


def _rests(steps: int) -> str:
    return "_" * max(0, steps)


def _placements(total_steps: int, hits: list[tuple[int, str]]) -> str:
    """Index-notation string with digit d at step s (for one-shot placements)."""
    cells = ["_"] * total_steps
    for step, digit in hits:
        if 0 <= step < total_steps:
            cells[step] = digit
    return "".join(cells)


def _drums(groove: str, start_bar: float = 0, end_bar: Optional[float] = None, gain: float = 0.0,
           clap: bool = True, hat_open: bool = False, suffix: str = "") -> list[TrackSpec]:
    g = lib.DRUMS[groove]
    out = []
    if g.get("kick"):
        out.append(TrackSpec(f"kick{suffix}", "drum", f"drum:{groove}:kick", sample="kick", gain_db=gain,
                             pitched=False, start_bar=start_bar, end_bar=end_bar, visual="kick", flip="alternate"))
    if g.get("snare"):
        out.append(TrackSpec(f"snare{suffix}", "drum", f"drum:{groove}:snare", sample="clap" if clap else "snare",
                             gain_db=gain - 2.0, pitched=False, start_bar=start_bar, end_bar=end_bar, visual="snare"))
    if g.get("hat_closed"):
        out.append(TrackSpec(f"hat{suffix}", "drum", f"drum:{groove}:hat_closed", sample="hat_closed",
                             gain_db=gain - 9.0, pitched=False, start_bar=start_bar, end_bar=end_bar, visual="hat",
                             pan=0.25))
    if hat_open or g.get("hat_open"):
        pat = f"drum:{groove}:hat_open" if g.get("hat_open") else "text:__1___1___1___1_"
        out.append(TrackSpec(f"ohat{suffix}", "drum", pat, sample="hat_open", gain_db=gain - 11.0, pitched=False,
                             start_bar=start_bar, end_bar=end_bar, visual="hat", pan=-0.25))
    return out


def _perc(pattern: str, start_bar: float = 0, end_bar: Optional[float] = None, gain: float = 0.0,
          suffix: str = "") -> TrackSpec:
    """A wiki percussion pattern (1 kick, 2 clap/snare with the kick paralleled, 3 hi-hat)."""
    return TrackSpec(f"perc{suffix}", "drum", pattern, mode="index", slots=copy.deepcopy(lib.PERC_SLOTS),
                     gain_db=gain, pitched=False, start_bar=start_bar, end_bar=end_bar, visual="kick",
                     flip="alternate", stem="drums")


def _crash(bar: float = 0.0, gain: float = -6.0, tid: str = "crash") -> TrackSpec:
    return TrackSpec(tid, "oneshot", "text:1", sample="crash", gain_db=gain, pitched=False, oneshot=True,
                     start_bar=bar, end_bar=bar + 1, visual="crash", choke=False, stem="drums")


def _bass(style: str = "offbeat", start_bar: float = 0, end_bar: Optional[float] = None, gain: float = -2.0,
          tid: str = "bass") -> TrackSpec:
    return TrackSpec(tid, "bass", f"bass:{style}", mode="index", slots={"1": "bass"}, follow="progression",
                     gain_db=gain, start_bar=start_bar, end_bar=end_bar, visual="bass")


def sec_intro(bars: int, opts: dict) -> SectionSpec:
    total = bars * STEPS_PER_BAR
    hits = [(0, "1")]
    if bars >= 4:
        hits.append((total // 2, "2"))
    if bars >= 8:
        hits.append((total * 3 // 4, "3"))
    tracks = [
        TrackSpec("quotes", "oneshot", "text:" + _placements(total, hits), mode="index",
                  slots={"1": "quote1", "2": "quote2", "3": "quote3"}, oneshot=True, pitched=False, gain_db=0.0,
                  visual="center", flip="none", choke=False),
        TrackSpec("pad", "pitch", "chords.minor" if opts.get("minor") else "chords.major", sample="pitch2",
                  gain_db=-17.0, sustain=True, octave=-1 if opts.get("low_pad") else 0, visual="none", stem="pad"),
        TrackSpec("hat", "drum", "text:__1___1___1___1_", sample="hat_closed", gain_db=-12.0, pitched=False,
                  start_bar=max(0, bars - 2), visual="hat"),
        TrackSpec("build", "drum", "drum:build:snare", sample="snare", gain_db=-6.0, pitched=False,
                  start_bar=bars - 1, visual="snare"),
    ]
    return SectionSpec("intro", bars, tracks, "Intro", layout="full",
                       fx=[{"fx": "filter_sweep", "kind": "lowpass", "f_start": 600.0, "f_end": 16000.0, "track": "pad"}])


def sec_intro_hits(pattern: str, bars: int, opts: dict) -> SectionSpec:
    tracks = [
        TrackSpec("pitch", "pitch", pattern, sample="pitch1", gain_db=0.0, visual="center", flip="alternate"),
        TrackSpec("pitch_b", "pitch", pattern, sample="pitch2", octave=1 if opts.get("hard") else 0,
                  gain_db=-7.0, visual="none"),
        TrackSpec("chop", "chop", pattern, sample="phrase", gain_db=-3.0, visual="full_flash", flip="alternate"),
        TrackSpec("kick", "drum", "", sample="kick", follow="@pitch", pitched=False, visual="none"),
        TrackSpec("snare", "drum", "", sample="clap", follow="@pitch", pitched=False, gain_db=-2.0, visual="none"),
        TrackSpec("bass", "bass", pattern, sample="bass", gain_db=-2.0, visual="none"),
        _crash(0.0, -5.0),
    ]
    return SectionSpec("intro_hits", bars, tracks, "Intro hits", layout="full")


def sec_chorus(bars: int, opts: dict, final: bool = False, name: str = "Chorus") -> SectionSpec:
    hard = opts.get("hard", False)
    # The Chorus has two layers (Sparta Remix Wiki):
    # * the main phrase on the standard Chorus pattern — "the chorus always contains the main phrase":
    #   its two parts as they are ("1" = part 1, "2" = part 2); ``chorus_pitch`` tunes them to the chords;
    # * the pitch playing a Chorus pitch pattern under it — the tutorial's basic one (quarter notes on the
    #   chord roots, "D***D***D#***D#***C***C***D#***D#***") in the first Chorus, then "0*, 12*", the
    #   foundational root/octave pattern "commonly used in the chorus section".
    pattern = opts.get("chorus_pattern", "chorus.standard")
    tune_main = bool(opts.get("chorus_pitch", False))
    main_slots = dict(SLOTS_CHORUS if opts.get("chorus_split", True) else SLOTS_12)
    minor = opts.get("minor", False)
    pitch_pat = opts.get("chorus_pitch_pattern") or (
        "chorus.original" if opts.get("first_chorus") else ("chorus.0_3_minor" if minor else "chorus.0_12"))
    tracks = [
        TrackSpec("main", "pitch", pattern, mode="index", slots=main_slots,
                  follow="progression" if tune_main else "", pitched=tune_main, crisp=True, gain_db=0.0,
                  visual="main", flip="alternate", stem="chorus"),
        TrackSpec("pitch", "pitch", pitch_pat, sample="pitch1", crisp=True, sustain=True, gain_db=-0.5,
                  visual="pitch_cycle", flip="alternate"),
        _bass("offbeat"),
        _crash(0.0),
    ]
    if hard or final:
        # A second pitch in fifths under the main one, and the main one an octave up.
        tracks.append(TrackSpec("pitch_b", "pitch", "chorus.0_7", sample="pitch2", crisp=True, sustain=True,
                                gain_db=-6.0, visual="pitch_cycle", flip="alternate", stem="pitch_layers"))
        tracks.append(TrackSpec("pitch_oct", "pitch", pitch_pat, sample="pitch1", octave=1, crisp=True,
                                sustain=True, gain_db=-9.0, visual="none", stem="pitch_layers"))
    if hard:
        tracks.append(TrackSpec("chords", "pitch", "chords.minor" if minor else "chords.major",
                                sample="pitch3", gain_db=-15.0, sustain=True, visual="none", stem="pad"))
    if opts.get("wiki_perc", False):
        tracks.append(_perc("perc.vitro" if hard else "perc.normal", end_bar=bars - 1))
    else:
        tracks += _drums("four_on_floor_16" if hard else "four_on_floor", end_bar=bars - 1, hat_open=hard)
    tracks += _drums("build", start_bar=bars - 1, suffix="_fill")
    return SectionSpec("chorus", bars, tracks, name, layout="main")


def sec_dundundenden(bars: int, opts: dict) -> SectionSpec:
    first = min(bars, 4)
    tracks = [
        TrackSpec("chop", "chop", "dun.original", sample="phrase", gain_db=0.0, end_bar=first, visual="full_flash",
                  flip="alternate"),
        TrackSpec("pitch", "pitch", "dun.original", sample="pitch1", gain_db=-5.0, end_bar=first, visual="none"),
        TrackSpec("kick", "drum", "", sample="kick", follow="@chop", pitched=False, end_bar=first, visual="none"),
        TrackSpec("snare", "drum", "", sample="snare", follow="@chop", pitched=False, gain_db=-2.0, end_bar=first,
                  visual="none"),
        TrackSpec("crash_hits", "drum", "", sample="crash", follow="@chop", pitched=False, gain_db=-12.0,
                  end_bar=first, visual="none"),
        TrackSpec("bass", "bass", "dun.original", sample="bass", gain_db=-1.0, end_bar=first, visual="none"),
    ]
    if bars > 4:
        second = opts.get("dun_second", "dun.madhouse_xye")
        tracks += [
            TrackSpec("pitch2", "pitch", second, sample="pitch1", start_bar=first, crisp=True, visual="pitch_cycle"),
            TrackSpec("pitch2_b", "pitch", second, sample="pitch2", start_bar=first, octave=-1, gain_db=-8.0,
                      visual="none", stem="pitch_layers"),
            _bass("rolling", start_bar=first),
            _crash(first),
        ]
        tracks += _drums("four_on_floor_16", start_bar=first, end_bar=bars - 1, suffix="_b")
        tracks += _drums("build", start_bar=bars - 1, suffix="_fill")
    return SectionSpec("dundundenden", bars, tracks, "DunDunDenDen", layout="full" if bars <= 4 else "grid3")


def sec_epicness(bars: int, opts: dict, pattern: Optional[str] = None) -> SectionSpec:
    """The Epicness: the index pattern (lead-in "1*" before the downbeat, a roll of 16ths at the end)
    over 4-bar blocks; long Epicness parts alternate the original with a community edit."""
    first = pattern or opts.get("epicness_pattern", "epic.original")
    edit = opts.get("epicness_edit", "epic.catmanteam_late2015")
    blocks = []
    b = 0
    while b < bars:
        n = min(4, bars - b)
        use_edit = (b // 4) % 2 == 1 and b + n < bars          # the last block keeps the original's roll
        blocks.append((b, n, edit if use_edit else first))
        b += n
    tracks: list[TrackSpec] = []
    for i, (b0, n, pid) in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        pick = lib.get(nxt[2]).pickup if nxt else 0.0
        end = b0 + n - pick / STEPS_PER_BAR       # leave the lead-in steps to the next block
        tracks.append(TrackSpec("pitch" if i == 0 else f"pitch_{i}", "pitch", pid, mode="index",
                                slots=dict(SLOTS_12), follow="progression", crisp=True, sustain=True,
                                visual="pitch_cycle", flip="rotate", start_bar=b0, end_bar=end))
    tracks += [
        TrackSpec("chords", "pitch", "chords.minor" if opts.get("minor") else "chords.major", sample="pitch3",
                  gain_db=-14.0, sustain=True, visual="none", stem="pad"),
        TrackSpec("arp", "pitch", "chords.arp_minor" if opts.get("minor") else "chords.arp_major", sample="pitch2",
                  gain_db=-16.0, crisp=True, visual="none", stem="pitch_layers"),
        _bass("rolling"),
        _crash(0.0),
    ]
    if opts.get("wiki_perc", False):
        tracks.append(_perc("perc.sparta_crash_mix", end_bar=bars - 1))
        tracks += _drums("build", start_bar=bars - 1, suffix="_fill")
    else:
        tracks += _drums("four_on_floor_16", end_bar=bars - 1, hat_open=True)
        tracks += _drums("build", start_bar=bars - 1, suffix="_fill")
    return SectionSpec("epicness", bars, tracks, "Epicness", layout="grid4")


def sec_chords(bars: int, opts: dict) -> SectionSpec:
    """Held chords before an Awesomeness ("Pre-Awesomeness" on the wiki's Chords list)."""
    minor = opts.get("minor", False)
    tracks = [
        TrackSpec("pitch", "pitch", "chorus.0_3_minor" if minor else "chorus.0_12", sample="pitch1", crisp=True,
                  visual="pitch_cycle", flip="alternate"),
        TrackSpec("chords", "pitch", "chords.minor" if minor else "chords.major", sample="pitch2", gain_db=-9.0,
                  sustain=True, visual="none", stem="pitch_soft"),
        _bass("roots"),
        _crash(0.0),
    ]
    if opts.get("wiki_perc", False):
        tracks.append(_perc("perc.generic", end_bar=bars - 1))
        tracks += _drums("build", start_bar=bars - 1, suffix="_fill")
    else:
        tracks += _drums("four_on_floor", end_bar=bars - 1)
        tracks += _drums("build", start_bar=bars - 1, suffix="_fill")
    return SectionSpec("chords", bars, tracks, "Chords (Pre-Awesomeness)", layout="grid3")


def sec_awesomeness(which: int, opts: dict, bars: int = 4) -> SectionSpec:
    minor = opts.get("minor", False)
    pid = opts.get(f"awesomeness{which}_pattern") or f"awe.{which}_{'minor' if minor else 'major'}"
    tracks = [
        TrackSpec("pitch", "pitch", pid, sample="pitch1", crisp=True, sustain=True, visual="pitch_cycle",
                  flip="rotate"),
        TrackSpec("pitch_low", "pitch", pid, sample="pitch2", octave=-1, gain_db=-9.0, sustain=True, visual="none",
                  stem="pitch_layers"),
        _bass("offbeat"),
        _crash(0.0),
    ]
    if opts.get("wiki_perc", False):
        tracks.append(_perc("perc.normal"))
    else:
        tracks += _drums("four_on_floor_16", hat_open=True)
    return SectionSpec("awesomeness", bars, tracks, f"Awesomeness {which}", layout="grid4")


def sec_madness(bars: int, opts: dict) -> SectionSpec:
    """The soft breakdown: the call & response words on top; the first pitch pattern runs from the
    first half to the end, the second one (the Trance Gates) joins from the second half (Madness article)."""
    half = bars // 2
    tracks = [
        TrackSpec("words", "words", opts.get("madness_words", "madwords.original"), mode="index",
                  slots={"1": "word_a", "2": "word_b"}, pitched=False, gain_db=0.0, visual="madness", flip="none"),
        TrackSpec("pitch", "pitch", "mad.first", sample="pitch1", gain_db=-9.0, crisp=True, visual="none",
                  stem="pitch_soft"),
        TrackSpec("pitch_gate", "pitch", "mad.second_half", sample="pitch2", gain_db=-10.0, start_bar=half,
                  visual="none", stem="pitch_soft"),
        TrackSpec("bass", "bass", "bass:held", mode="index", slots={"1": "bass"}, follow="progression",
                  gain_db=-5.0, sustain=True, visual="none"),
    ]
    tracks += _drums("breakdown", end_bar=half)
    tracks += _drums("half_time", start_bar=half, end_bar=bars - 1, suffix="_h")
    tracks += _drums("build", start_bar=bars - 1, suffix="_fill")
    return SectionSpec("madness", bars, tracks, "Madness", layout="split2",
                       fx=[{"fx": "filter_sweep", "kind": "lowpass", "f_start": 500.0, "f_end": 14000.0,
                            "track": "pitch_soft"}])


def sec_execution(bars: int, opts: dict, pattern: str = "exec.original") -> SectionSpec:
    tracks = [
        TrackSpec("pitch", "pitch", pattern, sample="pitch1", crisp=True, visual="pitch_cycle"),
        TrackSpec("pitch_b", "pitch", pattern, sample="pitch2", octave=-1, gain_db=-9.0, visual="none",
                  stem="pitch_layers"),
        _bass("offbeat"),
        _crash(0.0),
    ]
    tracks += _drums("four_on_floor_16")
    return SectionSpec("execution", bars, tracks, "Execution", layout="grid3")


def sec_ending(bars: int, opts: dict) -> SectionSpec:
    r = int(opts.get("ending_root", 0))          # the base's last chord (0 = the key root)
    g = -4.0 if opts.get("base") else 0.0         # on a base: sit in its fade-out
    tracks = [
        TrackSpec("final", "pitch", "text:0******", sample="pitch1", sustain=True, visual="center", flip="none",
                  transpose=r, gain_db=g),
        TrackSpec("final_b", "pitch", "text:0******\n7******\n12******", sample="pitch2", sustain=True,
                  gain_db=-8.0, visual="none", stem="pad", transpose=r),
        TrackSpec("bass", "bass", "text:0******", sample="bass", sustain=True, gain_db=-1.0, visual="none",
                  transpose=r),
        TrackSpec("kick", "drum", "text:1", sample="kick", pitched=False, visual="none"),
        TrackSpec("snare", "drum", "text:1", sample="clap", pitched=False, visual="none"),
        _crash(0.0, -4.0),
        TrackSpec("phrase", "oneshot", "text:" + _placements(bars * 16, [(8, "1")]), mode="index",
                  slots={"1": "phrase"}, oneshot=True, pitched=False, gain_db=g, visual="center_late", flip="none",
                  choke=False),
    ]
    fx = [] if opts.get("base") else [{"fx": "tape_stop", "duration_s": 0.9, "track": "*"}]
    return SectionSpec("ending", bars, tracks, "Ending", layout="full", fx=fx)


_STARS = {1: "", 2: "*", 3: "**", 4: "***", 5: "****", 6: "*****", 8: "******"}


def _hits_text(hits: list[tuple[int, int]], total: int, length: int = 4) -> str:
    """Semitone notation with note r at step st (each ``length`` steps long, clipped at the next hit)."""
    out, pos = [], 0
    for i, (st, r) in enumerate(hits):
        if st < pos:
            continue
        out.append("_" * (st - pos))
        nxt = hits[i + 1][0] if i + 1 < len(hits) else total
        dur = max(1, min(length, nxt - st))
        while dur not in _STARS:
            dur -= 1
        out.append(f"{r}{_STARS[dur]}")
        pos = st + dur
    out.append("_" * max(0, total - pos))
    return "".join(out)


def sec_base_intro(bars: int, hits: list, opts: dict) -> SectionSpec:
    """Intro over a base's own intro hits: a quote and the pitch on each hit's note (the wiki's
    Intro patterns are three hits: "-2*** -2*** -2***")."""
    total = bars * STEPS_PER_BAR
    hits = sorted((int(st), int(r)) for st, r in hits if 0 <= int(st) < total) or \
        [(st, -2) for st in (0, 8, 16) if st < total]
    placements = _placements(total, [(st, str(1 + i % 3)) for i, (st, _r) in enumerate(hits)])
    text = _hits_text(hits, total)
    tracks = [
        TrackSpec("quotes", "oneshot", "text:" + placements, mode="index",
                  slots={"1": "quote1", "2": "quote2", "3": "quote3"}, oneshot=True, pitched=False, gain_db=-2.0,
                  visual="center", flip="none", choke=True),
        TrackSpec("pitch", "pitch", "text:" + text, mode="semitone", sample="pitch1", gain_db=-3.0,
                  sustain=True, visual="none", stem="pitch"),
        TrackSpec("pitch_b", "pitch", "text:" + text, mode="semitone", sample="pitch2", octave=-1,
                  gain_db=-10.0, sustain=True, visual="none", stem="pitch_layers"),
    ]
    return SectionSpec("intro", bars, tracks, "Intro", layout="full")


# ── Variants ─────────────────────────────────────────────────────────────────

VARIANTS: dict[str, dict] = {
    "unextended": {
        "title": "Sparta Unextended Remix",
        "description": "Short base (~1:15): Intro, Chorus, DunDunDenDen, Chorus, Madness, final Chorus. "
                       "No Epicness — the classic short structure.",
        "bpm": 140, "pitching": "normal", "polish": "normal",
        "plan": [("intro", 4), ("intro_hits", 1), ("chorus", 8), ("dundundenden", 4), ("chorus", 8),
                 ("madness", 8), ("chorus_final", 8), ("ending", 2)],
    },
    "semi_extended": {
        "title": "Sparta Semi-Extended Remix",
        "description": "Medium length with an Epicness and Awesomeness 1, hard pitching (octave/chord/arp "
                       "layers) and hard FX polishing (heavy OTT, pumping, stutter gates).",
        "bpm": 140, "pitching": "hard", "polish": "hard",
        "plan": [("intro", 4), ("intro_hits", 1), ("chorus", 8), ("dundundenden", 4), ("chorus", 8),
                 ("epicness", 8), ("awesomeness1", 4), ("madness", 8), ("chorus_final", 8), ("ending", 2)],
    },
    "extended": {
        "title": "Sparta Extended Remix",
        "description": "The 2:08 extended base's layout: 3 intro hits, short first Chorus, DunDunDenDen, an "
                       "Epicness after the Chorus that follows it, Awesomeness 1 (the last pattern before the "
                       "Madness), the Madness, a 12-bar Epicness after the next Chorus and Awesomeness 2 opening "
                       "the final Chorus.",
        "bpm": 140, "pitching": "normal", "polish": "normal", "wiki_perc": True,
        "plan": [("intro3", 2), ("chorus", 4), ("dundundenden", 6), ("chorus", 4), ("epicness", 4),
                 ("awesomeness1", 4), ("chorus", 8), ("madness", 8), ("chorus", 8), ("epicness", 12),
                 ("awesomeness2", 4), ("chorus_final", 8), ("ending", 2)],
    },
    "hyper": {
        "title": "Sparta Hyper Remix",
        "description": "Faster (160 BPM) semi-extended structure with the Hyper/Vertex execution pattern, "
                       "hard pitching and hard FX.",
        "bpm": 160, "pitching": "hard", "polish": "hard",
        "plan": [("intro", 4), ("intro_hits", 1), ("chorus", 8), ("dundundenden", 4), ("execution:exec.hyper_vertex", 4),
                 ("chorus", 8), ("epicness", 8), ("madness", 8), ("chorus_final", 8), ("ending", 2)],
    },
    "minor": {
        "title": "Sparta Extended Remix (Minor)",
        "description": "Extended structure with the wiki's minor variants: Metro/Minor intro, minor chords, "
                       "0*,3* minor arps and the minor Awesomeness patterns.",
        "bpm": 140, "pitching": "hard", "polish": "normal", "minor": True, "intro_pattern": "intro.metro_minor",
        "plan": [("intro", 8), ("intro_hits", 1), ("chorus", 8), ("dundundenden", 8), ("chorus", 8),
                 ("epicness", 8), ("awesomeness1", 4), ("madness", 8), ("awesomeness2", 4), ("chorus_final", 8),
                 ("ending", 2)],
    },
    "classic": {
        "title": "Sparta Remix (2010 style)",
        "description": "Old-school unextended remix: sampler (chipmunk) pitching, no OTT, light polish.",
        "bpm": 140, "pitching": "classic", "polish": "light",
        "plan": [("intro", 4), ("intro_hits", 1), ("chorus", 8), ("dundundenden", 4), ("chorus", 8),
                 ("madness", 8), ("chorus_final", 8), ("ending", 2)],
    },
}


def build_arrangement(variant: str = "unextended", bpm: Optional[float] = None, key: str = "D",
                      progression: Optional[str] = None, pitching: Optional[str] = None,
                      polish: Optional[str] = None, minor: Optional[bool] = None,
                      intro_pattern: Optional[str] = None, chorus_pattern: Optional[str] = None,
                      title: Optional[str] = None, chorus_pitch: bool = False) -> Arrangement:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {', '.join(VARIANTS)}")
    v = VARIANTS[variant]
    opts = {
        "hard": (pitching or v["pitching"]) == "hard",
        "minor": v.get("minor", False) if minor is None else minor,
        "wiki_perc": v.get("wiki_perc", False),
        "chorus_pitch": bool(chorus_pitch),
    }
    if chorus_pattern:
        opts["chorus_pattern"] = chorus_pattern
    ip = intro_pattern or v.get("intro_pattern") or ("intro.metro_minor" if opts["minor"] else "intro.d_note")
    sections: list[SectionSpec] = []
    chorus_count = 0
    for kind, bars in v["plan"]:
        base, _, arg = kind.partition(":")
        if base == "intro":
            sections.append(sec_intro(bars, opts))
        elif base == "intro3":
            sections.append(sec_base_intro(bars, [], opts))
        elif base == "intro_hits":
            sections.append(sec_intro_hits(ip, bars, opts))
        elif base == "chorus":
            chorus_count += 1
            o = dict(opts, first_chorus=chorus_count == 1)
            sections.append(sec_chorus(bars, o, name=f"Chorus {chorus_count}"))
        elif base == "chorus_final":
            sections.append(sec_chorus(bars, opts, final=True, name="Final Chorus"))
        elif base == "dundundenden":
            sections.append(sec_dundundenden(bars, opts))
        elif base == "epicness":
            sections.append(sec_epicness(bars, opts))
        elif base == "chords":
            sections.append(sec_chords(bars, opts))
        elif base == "awesomeness1":
            sections.append(sec_awesomeness(1, opts))
        elif base == "awesomeness2":
            sections.append(sec_awesomeness(2, opts))
        elif base == "madness":
            sections.append(sec_madness(bars, opts))
        elif base == "execution":
            sections.append(sec_execution(bars, opts, arg or "exec.original"))
        elif base == "ending":
            sections.append(sec_ending(bars, opts))
        else:
            raise ValueError(f"unknown section kind {kind!r}")
    return Arrangement(
        title=title or v["title"], variant=variant, bpm=float(bpm or v["bpm"]), key=key,
        progression=progression or ORIGINAL_PROGRESSION, pitching=pitching or v["pitching"],
        polish=polish or v["polish"], sections=sections,
    )


BASE_SECTION_NAMES = {
    "intro": "Intro", "chorus": "Chorus", "dundundenden": "DunDunDenDen", "chords": "Chords (Pre-Awesomeness)",
    "awesomeness1": "Awesomeness 1", "awesomeness2": "Awesomeness 2", "madness": "Madness", "epicness": "Epicness",
    "execution": "Execution", "ending": "Ending",
}


def build_from_base(base_map, pitching: str = "normal", polish: str = "normal", minor: bool = False,
                    title: Optional[str] = None, chorus_pattern: Optional[str] = None,
                    progression: Optional[str] = None, chorus_pitch: bool = False,
                    extra: Optional[dict] = None) -> Arrangement:
    """An arrangement that follows a base's own bars: each section of the base gets its remix part
    (see ``spartagen.audio.base``).  ``base_map`` is a BaseMap or its dict."""
    from .audio.base import BaseMap
    bm = base_map if isinstance(base_map, BaseMap) else BaseMap.from_dict(base_map)
    opts = {"hard": pitching == "hard", "minor": minor, "base": True, "wiki_perc": True,
            "chorus_pitch": bool(chorus_pitch)}
    if chorus_pattern:
        opts["chorus_pattern"] = chorus_pattern
    opts.update(extra or {})
    kinds = [s.kind for s in bm.sections]
    n_chorus_total = kinds.count("chorus")
    sections: list[SectionSpec] = []
    n_chorus = 0
    for sec in bm.sections:
        k, bars = sec.kind, int(sec.bars)
        if bars <= 0:
            continue
        if k == "intro":
            spec = sec_base_intro(bars, bm.intro_hits, opts)
        elif k == "chorus":
            n_chorus += 1
            final = n_chorus == n_chorus_total and n_chorus > 1
            o = dict(opts, first_chorus=n_chorus == 1)
            spec = sec_chorus(bars, o, final=final, name="Final Chorus" if final else f"Chorus {n_chorus}")
        elif k == "dundundenden":
            spec = sec_dundundenden(bars, opts)
        elif k == "chords":
            spec = sec_chords(bars, opts)
        elif k in ("awesomeness1", "awesomeness2"):
            spec = sec_awesomeness(int(k[-1]), opts, bars=bars)
        elif k == "madness":
            spec = sec_madness(bars, opts)
        elif k == "epicness":
            spec = sec_epicness(bars, opts)
        elif k == "execution":
            spec = sec_execution(bars, opts, opts.get("execution_pattern", "exec.original"))
        elif k == "ending":
            spec = sec_ending(bars, dict(opts, ending_root=bm.ending_root))
        else:
            spec = sec_chorus(bars, opts, name=BASE_SECTION_NAMES.get(k, k.title()))
        sections.append(spec)
    return Arrangement(title=title or "Sparta Remix", variant="base", bpm=float(bm.bpm), key=bm.key,
                       progression=progression or bm.progression or ORIGINAL_PROGRESSION, pitching=pitching,
                       polish=polish, sections=sections)


SECTION_BUILDERS = {
    "intro": lambda bars, o: sec_intro(bars, o),
    "intro_hits": lambda bars, o: sec_intro_hits(o.get("intro_pattern", "intro.d_note"), bars, o),
    "intro3": lambda bars, o: sec_base_intro(bars, [], o),
    "chorus": lambda bars, o: sec_chorus(bars, o),
    "chorus_final": lambda bars, o: sec_chorus(bars, o, final=True, name="Final Chorus"),
    "dundundenden": lambda bars, o: sec_dundundenden(bars, o),
    "epicness": lambda bars, o: sec_epicness(bars, o),
    "chords": lambda bars, o: sec_chords(bars, o),
    "awesomeness1": lambda bars, o: sec_awesomeness(1, o),
    "awesomeness2": lambda bars, o: sec_awesomeness(2, o),
    "madness": lambda bars, o: sec_madness(bars, o),
    "execution": lambda bars, o: sec_execution(bars, o, o.get("execution_pattern", "exec.original")),
    "ending": lambda bars, o: sec_ending(bars, o),
}


def make_section(kind: str, bars: int, opts: Optional[dict] = None) -> SectionSpec:
    fn = SECTION_BUILDERS.get(kind)
    if fn is None:
        raise ValueError(f"unknown section kind {kind!r}")
    return fn(bars, opts or {})


# ── Compiler ─────────────────────────────────────────────────────────────────


@dataclass
class NoteEvent:
    t: float                 # start, seconds from the remix start
    dur: float               # nominal note length, seconds
    track: str               # "<section index>:<track id>"
    track_id: str
    stem: str
    kind: str
    sample: str
    semis: float             # pitch offset from the sample's own D (pattern semitones)
    gain_db: float
    pan: float
    crisp: bool
    sustain: bool
    oneshot: bool
    pitched: bool
    choke: bool
    section: int
    section_kind: str
    visual: str
    flip: str
    index: int = 0           # nth note on this track (drives flips / cell cycling)
    max_len: float = 0.0     # hard cut (choke), filled in by the compiler

    def to_dict(self) -> dict:
        return asdict(self)


#: When a bank lacks a sample, these stand in (chorus halves → the main pitches …).
FALLBACKS = {
    "chorus_a": ("pitch1",), "chorus_b": ("pitch2", "pitch1"), "pitch2": ("pitch1",), "pitch3": ("pitch2", "pitch1"),
    "clap": ("snare",), "snare": ("clap",), "hat_open": ("hat_closed",), "word_b": ("word_a",),
}


def _available(sample: str, available: Optional[set]) -> Optional[str]:
    if available is None or sample in available:
        return sample
    for alt in FALLBACKS.get(sample, ()):
        if alt in available:
            return alt
    return None


def _pattern_source(track: TrackSpec) -> tuple[Optional[ParsedPattern], Optional[str], float, float]:
    """(parsed pattern, progression it was written over, loop length in steps, pickup steps)."""
    p = track.pattern
    if not p:
        return None, None, 0.0, 0.0
    if p.startswith("text:"):
        pp = parse(p[5:], track.mode)
        return pp, ORIGINAL_PROGRESSION, pp.loop_length(), 0.0
    if p.startswith("drum:"):
        _, groove, part = p.split(":", 2)
        text = lib.DRUMS[groove].get(part, "")
        pp = parse(text or "_" * 16, "index")
        return pp, None, 16.0, 0.0
    if p.startswith("bass:"):
        text = lib.BASS[p.split(":", 1)[1]]
        pp = parse(text, "index")
        return pp, None, max(16.0, pp.loop_length()), 0.0
    d = lib.get(p)
    mode = track.mode if track.mode != "auto" else d.mode
    pp = parse(d.text, mode) if not (d.lines == "sequence" and "\n" in d.text) else d.parsed()
    if mode != "auto" and pp.mode != mode and d.lines != "sequence":
        pp = parse(d.text, mode)
    if d.length:
        loop = d.length
    elif d.pickup:
        loop = ParsedPattern([], pp.length - d.pickup, pp.mode).loop_length()
    else:
        loop = pp.loop_length()
    return pp, d.progression, loop, float(d.pickup or 0.0)


def _track_slots(tr: TrackSpec) -> dict:
    if tr.slots:
        return tr.slots
    if tr.kind == "drum" and tr.pattern.startswith(("perc.", "hat.")):
        return lib.PERC_SLOTS            # wiki percussion: 1 kick, 2 clap (+kick), 3 hi-hat
    return {}


def _slot_entries(tr: TrackSpec, value: int) -> list[dict]:
    """What an index digit plays: one or more {"sample", "offset", "gain", "visual"} entries."""
    slots = _track_slots(tr)
    if not slots:
        return [{"sample": tr.sample}]
    slot = slots.get(str(value))
    if slot is None:
        # Unmapped digit: cycle through the slots that exist.
        keys = sorted(slots)
        slot = slots[keys[(value - 1) % len(keys)]]
    items = slot if isinstance(slot, list) else [slot]
    out = []
    for it in items:
        if isinstance(it, str):
            out.append({"sample": it})
        elif isinstance(it, dict):
            out.append(dict(it, sample=it.get("sample", tr.sample)))
    return out or [{"sample": tr.sample}]


def compile_events(arr: Arrangement, available: Optional[set] = None) -> list[NoteEvent]:
    """Flatten the arrangement into note events (seconds), with choke lengths resolved."""
    step = arr.step_s
    events: list[NoteEvent] = []
    target_prog = parse_progression(arr.progression)
    starts = arr.section_starts()
    for si, (sec, t0) in enumerate(zip(arr.sections, starts)):
        sec_prog = parse_progression(sec.progression) if sec.progression else target_prog
        sec_steps = sec.bars * STEPS_PER_BAR
        t0_steps = t0 / step
        onsets_by_track: dict[str, list[tuple[float, float, float]]] = {}
        ordered = sorted(sec.tracks, key=lambda tr: 1 if tr.follow.startswith("@") else 0)
        for tr in ordered:
            if tr.muted:
                continue
            a_step = tr.start_bar * STEPS_PER_BAR
            b_step = (tr.end_bar if tr.end_bar is not None else sec.bars) * STEPS_PER_BAR
            b_step = min(b_step, sec_steps)
            notes: list[tuple[float, float, int, int, int]] = []  # (step, dur, value, sharp, voice)
            if tr.follow.startswith("@"):
                src = onsets_by_track.get(tr.follow[1:], [])
                for st, du, _v in src:
                    if a_step <= st < b_step:
                        notes.append((st, du, 1, 0, 0))
                parsed_mode = "index"
                written = None
            else:
                pp, written, loop, pickup = _pattern_source(tr)
                if pp is None or not pp.notes:
                    continue
                parsed_mode = pp.mode
                loop = max(loop, 0.25)
                rep = 0
                while a_step + rep * loop < b_step:
                    base = a_step + rep * loop
                    more = a_step + (rep + 1) * loop < b_step
                    for n in pp.notes:
                        pos = n.start - pickup
                        if pos >= loop - pickup and more:
                            continue          # the next repetition's lead-in takes these steps
                        if pos >= loop + pickup:
                            continue
                        st = base + pos
                        if st >= b_step:
                            break
                        if st < a_step and (rep > 0 or t0_steps + st < -1e-9):
                            continue          # a lead-in can reach back into the previous section only
                        notes.append((st, n.dur, n.value, n.sharp, n.voice))
                    rep += 1
            notes.sort(key=lambda z: (z[0], z[4]))
            onsets_by_track[tr.id] = [(st, du, v) for st, du, v, _s, _vo in notes]
            count = 0
            written_prog = parse_progression(written) if written else None
            for st, du, value, sharp, voice in notes:
                # Which sample(s), and how many semitones from its D?
                if parsed_mode == "index" or tr.follow == "progression":
                    entries = _slot_entries(tr, value)
                    root = sec_prog.root_at(st) if tr.follow == "progression" or tr.kind == "bass" else 0
                    if tr.follow.startswith("@"):
                        root = 0
                else:
                    entries = [{"sample": tr.sample}]
                    root = value
                    # "Progression Twist": move notes written over another progression.
                    if written_prog is not None and written_prog.roots != sec_prog.roots:
                        root = retarget(value, st, written_prog, sec_prog)
                if tr.kind == "chop":
                    syls = sorted([s for s in (available or set()) if s.startswith("syl")],
                                  key=lambda s: int(s[3:]) if s[3:].isdigit() else 0)
                    entries = [{"sample": syls[count % len(syls)] if syls else tr.sample}]
                emitted = False
                for k, ent in enumerate(entries):
                    sample = _available(ent["sample"], available)
                    if sample is None:
                        continue
                    offset = int(ent.get("offset", 0))
                    semis = root + offset + sharp + 12 * tr.octave + tr.transpose
                    events.append(NoteEvent(
                        t=t0 + st * step, dur=du * step, track=f"{si}:{tr.id}" + (f"#{k}" if k else ""),
                        track_id=tr.id, stem=tr.stem or _default_stem(tr), kind=tr.kind, sample=sample,
                        semis=float(semis), gain_db=tr.gain_db + float(ent.get("gain", 0.0)), pan=tr.pan,
                        crisp=tr.crisp, sustain=tr.sustain, oneshot=tr.oneshot,
                        pitched=tr.pitched and tr.kind in ("pitch", "bass", "chop", "words"),
                        choke=tr.choke, section=si, section_kind=sec.kind,
                        visual=ent.get("visual", tr.visual if k == 0 else "none"), flip=tr.flip, index=count,
                    ))
                    emitted = True
                if emitted:
                    count += 1
    events.sort(key=lambda e: (e.t, e.track))
    _resolve_chokes(events, arr.duration)
    return events


def _default_stem(tr: TrackSpec) -> str:
    return {"pitch": "pitch", "bass": "bass", "drum": "drums", "oneshot": "quotes", "chop": "chop",
            "words": "quotes"}.get(tr.kind, "misc")


def _resolve_chokes(events: list[NoteEvent], total: float) -> None:
    """Each note may sound until the next note on the same track (and voice) starts."""
    by_track: dict[str, list[NoteEvent]] = {}
    for e in events:
        by_track.setdefault(e.track, []).append(e)
    for evs in by_track.values():
        # Chord voices share a start time — they must not choke each other.
        for i, e in enumerate(evs):
            nxt = None
            for j in range(i + 1, len(evs)):
                if evs[j].t > e.t + 1e-6:
                    nxt = evs[j]
                    break
            if e.choke and nxt is not None:
                e.max_len = nxt.t - e.t
            else:
                e.max_len = max(total - e.t, e.dur) + 4.0


def with_progression(arr: Arrangement, progression: str) -> Arrangement:
    a = copy.deepcopy(arr)
    a.progression = progression
    return a
