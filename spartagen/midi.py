"""MIDI bases: a base's notes from a MIDI file, each channel played by a part of the remix.

Any base can be used this way, public or not: its MIDI (from the base maker, a transcription, a DAW
export) is read, every channel/track becomes a *part* with a role — the main phrase, a pitch sample,
the chords, the bass, the drums, quotes, the Madness words — or is switched off, and the remix plays
the MIDI's notes with the source's samples.  A MIDI without drums can get the usual Sparta
percussion added, and the main phrase can go on the Chorus pattern where no channel plays it.

Standard MIDI files, format 0, 1 or 2; tempo from the first tempo event (120 BPM when there is none);
bars of 4/4 (16 sixteenth steps).
"""

from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass, field, asdict
from typing import Optional

from .patterns.notation import STEPS_PER_BAR

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

#: Roles a part can play: (label, how its notes pick samples).
ROLES: dict[str, str] = {
    "off": "Off",
    "chorus": "Chorus — main phrase (lowest note = part 1, next = part 2 …)",
    "pitch1": "Main pitch",
    "pitch2": "Second pitch",
    "pitch3": "Third pitch",
    "pitch4": "Fourth pitch",
    "chords": "Chords (a pitch sample per voice)",
    "bass": "Bass pitch",
    "drums": "Drums (General MIDI drum map)",
    "kick": "Kick",
    "snare": "Snare",
    "clap": "Clap",
    "hat": "Hi-hat",
    "crash": "Crash",
    "perc": "Other percussion",
    "quotes": "Quotes (note order → quote 1, 2, 3)",
    "words": "Madness words (note order → word 1, 2)",
}
DRUM_ROLES = ("drums", "kick", "snare", "clap", "hat", "crash", "perc")
PITCH_ROLES = ("pitch1", "pitch2", "pitch3", "pitch4")

#: General MIDI drum notes → our drum slots.
GM_DRUMS = {35: 1, 36: 1, 38: 2, 40: 2, 37: 3, 39: 3, 42: 4, 44: 4, 46: 5, 49: 6, 52: 6, 55: 6, 57: 6,
            51: 7, 53: 7, 59: 7}
DRUM_SLOTS = {
    "1": {"sample": "kick", "visual": "kick"},
    "2": {"sample": "snare", "gain": -2.0, "visual": "snare"},
    "3": {"sample": "clap", "gain": -2.0, "visual": "snare"},
    "4": {"sample": "hat_closed", "gain": -9.0, "visual": "hat"},
    "5": {"sample": "hat_open", "gain": -10.0, "visual": "hat"},
    "6": {"sample": "crash", "gain": -5.0, "visual": "crash"},
    "7": {"sample": "hat2", "gain": -9.0, "visual": "hat2"},
    "8": {"sample": "perc", "gain": -6.0, "visual": "perc"},
}
SINGLE_DRUM = {"kick": ("kick", 0.0, "kick"), "snare": ("snare", -2.0, "snare"), "clap": ("clap", -2.0, "snare"),
               "hat": ("hat_closed", -9.0, "hat"), "crash": ("crash", -5.0, "crash"), "perc": ("perc", -6.0, "perc")}

GM_FAMILIES = ["Piano", "Chromatic percussion", "Organ", "Guitar", "Bass", "Strings", "Ensemble", "Brass", "Reed",
               "Pipe", "Synth lead", "Synth pad", "Synth effects", "Ethnic", "Percussive", "Sound effects"]


class MidiError(ValueError):
    pass


@dataclass
class MidiNote:
    start: float            # beats (quarter notes) from the start of the file
    dur: float              # beats
    pitch: int
    velocity: int
    channel: int            # 0-15
    track: int


@dataclass
class MidiPart:
    id: str                 # "t<track>c<channel>"
    name: str
    track: int
    channel: int            # 1-16, as MIDI programs show it
    program: int = -1
    notes: int = 0
    low: int = 0
    high: int = 0
    median: int = 60
    drums: bool = False
    polyphony: int = 1      # most notes starting together
    first_beat: float = 0.0
    last_beat: float = 0.0
    onsets: int = 0         # distinct note starts (a chord counts once)
    double_of: str = ""     # the part that plays the same notes (maybe an octave apart), if any

    @property
    def range_text(self) -> str:
        return f"{note_name(self.low)}–{note_name(self.high)}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["range"] = self.range_text
        return d


@dataclass
class MidiSong:
    path: str
    ticks_per_beat: int
    bpm: float
    key_pc: int = 2
    minor: bool = False
    time_signature: tuple = (4, 4)
    beats: float = 0.0
    notes: list = field(default_factory=list)
    parts: list = field(default_factory=list)
    tempo_changes: int = 0
    warnings: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return NOTE_NAMES[self.key_pc % 12]

    @property
    def bars(self) -> int:
        return max(1, int(math.ceil(self.beats / 4.0 - 1e-6)))

    def part(self, pid: str) -> MidiPart:
        for p in self.parts:
            if p.id == pid:
                return p
        raise KeyError(pid)

    def summary(self) -> dict:
        return {"path": self.path, "bpm": round(self.bpm, 3), "key": self.key, "minor": self.minor,
                "time_signature": list(self.time_signature), "bars": self.bars, "beats": round(self.beats, 3),
                "duration": round(self.beats * 60.0 / self.bpm, 2), "notes": len(self.notes),
                "parts": [p.to_dict() for p in self.parts], "warnings": list(self.warnings)}


def note_name(pitch: int) -> str:
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


# ── reading ──────────────────────────────────────────────────────────────────


def _vlq(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if pos >= len(data):
            raise MidiError("the file ends inside a number")
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, pos
    raise MidiError("a number longer than four bytes")


def read_midi(path: str) -> MidiSong:
    with open(path, "rb") as fh:
        data = fh.read()
    song = parse_midi(data)
    song.path = os.path.abspath(path)
    return song


def parse_midi(data: bytes) -> MidiSong:
    if data[:4] == b"RIFF" and data[8:12] == b"RMID":        # RIFF-wrapped MIDI
        i = data.find(b"MThd")
        data = data[i:] if i >= 0 else data
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiError("not a MIDI file (no MThd header)")
    hlen = struct.unpack(">I", data[4:8])[0]
    fmt, ntracks, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise MidiError("SMPTE-timed MIDI files are not supported — export with beats (ticks per quarter note)")
    tpb = division or 480
    pos = 8 + hlen
    tempos: list[tuple[int, int]] = []          # (tick, microseconds per beat)
    time_sig: Optional[tuple[int, int]] = None
    key_sig: Optional[tuple[int, int]] = None
    raw: list[tuple[int, int, int, int, int, int]] = []   # (start tick, end tick, pitch, velocity, channel, track)
    names: dict[int, str] = {}
    programs: dict[tuple[int, int], int] = {}
    track_index = 0
    while pos + 8 <= len(data) and track_index < max(ntracks, 1) + 64:
        cid = data[pos:pos + 4]
        clen = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + clen]
        pos += 8 + clen
        if cid != b"MTrk":
            continue
        t = track_index
        track_index += 1
        tick = 0
        p = 0
        status = 0
        on: dict[tuple[int, int], list[tuple[int, int]]] = {}
        while p < len(body):
            delta, p = _vlq(body, p)
            tick += delta
            if p >= len(body):
                break
            b = body[p]
            if b == 0xFF:                            # meta
                if p + 2 > len(body):
                    break
                mtype = body[p + 1]
                mlen, q = _vlq(body, p + 2)
                mdata = body[q:q + mlen]
                p = q + mlen
                if mtype == 0x51 and mlen == 3:
                    tempos.append((tick, (mdata[0] << 16) | (mdata[1] << 8) | mdata[2]))
                elif mtype == 0x58 and mlen >= 2 and time_sig is None:
                    time_sig = (mdata[0], 2 ** mdata[1])
                elif mtype == 0x59 and mlen >= 2 and key_sig is None:
                    key_sig = (struct.unpack("b", mdata[:1])[0], mdata[1])
                elif mtype == 0x03 and t not in names:
                    names[t] = mdata.decode("latin-1", "replace").strip()
                elif mtype == 0x2F:
                    break
                continue
            if b in (0xF0, 0xF7):                    # sysex
                slen, q = _vlq(body, p + 1)
                p = q + slen
                continue
            if b & 0x80:
                status = b
                p += 1
            elif not status:
                raise MidiError(f"track {t + 1}: data without a status byte")
            kind, ch = status & 0xF0, status & 0x0F
            if kind in (0xC0, 0xD0):
                if p >= len(body):
                    break
                if kind == 0xC0 and (t, ch) not in programs:
                    programs[(t, ch)] = body[p]
                p += 1
                continue
            if p + 2 > len(body):
                break
            d1, d2 = body[p], body[p + 1]
            p += 2
            if kind == 0x90 and d2 > 0:
                on.setdefault((ch, d1), []).append((tick, d2))
            elif kind == 0x80 or (kind == 0x90 and d2 == 0):
                stack = on.get((ch, d1))
                if stack:
                    st, vel = stack.pop(0)
                    raw.append((st, max(tick, st + 1), d1, vel, ch, t))
        for (ch, pitch), stack in on.items():       # notes never switched off: a beat long
            for st, vel in stack:
                raw.append((st, st + tpb, pitch, vel, ch, t))
    if not raw:
        raise MidiError("the MIDI file has no notes")
    tempos.sort()
    song_tempo = tempos[0][1] if tempos else 500000
    song = MidiSong(path="", ticks_per_beat=tpb, bpm=60_000_000.0 / song_tempo)
    distinct = sorted({us for _t, us in tempos})
    song.tempo_changes = max(0, len(distinct) - 1)
    if song.tempo_changes:
        song.warnings.append(f"the tempo changes {song.tempo_changes} time(s); the remix keeps "
                             f"{song.bpm:.2f} BPM from the start")
    song.time_signature = time_sig or (4, 4)
    if song.time_signature != (4, 4):
        song.warnings.append(f"time signature {song.time_signature[0]}/{song.time_signature[1]}: parts are laid "
                             "out in bars of 4/4")
    raw.sort()
    song.notes = [MidiNote(st / tpb, (en - st) / tpb, pitch, vel, ch, t) for st, en, pitch, vel, ch, t in raw]
    song.beats = max(n.start + n.dur for n in song.notes)
    song.parts = _parts(song.notes, names, programs, fmt)
    found = sparta_key(song.notes)
    if found is not None:
        song.key_pc, song.minor = found
    elif key_sig is not None and key_sig != (0, 0):          # C major is many DAWs' "no key"
        sf, mi = key_sig
        major_pc = (sf * 7) % 12
        song.key_pc, song.minor = ((major_pc + 9) % 12, True) if mi else (major_pc, False)
    else:
        song.key_pc, song.minor = estimate_key(song.notes)
    return song


def _parts(notes: list, names: dict, programs: dict, fmt: int) -> list[MidiPart]:
    groups: dict[tuple[int, int], list[MidiNote]] = {}
    for n in notes:
        groups.setdefault((n.track, n.channel), []).append(n)
    out = []
    for (t, ch), ns in sorted(groups.items()):
        pitches = sorted(n.pitch for n in ns)
        starts: dict[float, int] = {}
        for n in ns:
            k = round(n.start, 3)
            starts[k] = starts.get(k, 0) + 1
        prog = programs.get((t, ch), -1)
        drums = ch == 9
        name = names.get(t, "") if fmt != 0 else ""
        if not name:
            name = "Drums" if drums else (GM_FAMILIES[prog // 8] if prog >= 0 else f"Channel {ch + 1}")
        if fmt == 0 or sum(1 for (tt, _c) in groups if tt == t) > 1:
            name = f"{name} (ch {ch + 1})"
        out.append(MidiPart(id=f"t{t}c{ch}", name=name, track=t, channel=ch + 1, program=prog, notes=len(ns),
                            low=pitches[0], high=pitches[-1], median=pitches[len(pitches) // 2], drums=drums,
                            polyphony=max(starts.values()), first_beat=ns[0].start,
                            last_beat=max(n.start + n.dur for n in ns), onsets=len(starts)))
    # Doubled tracks (a base layering one line on two instruments): the same notes, maybe an octave apart.
    shapes = {(t, ch): {(round(n.start, 2), n.pitch % 12) for n in ns} for (t, ch), ns in groups.items()}
    for i, a in enumerate(out):
        for b in out[:i]:
            if a.drums or b.drums or b.double_of:
                continue
            sa, sb = shapes[(a.track, a.channel - 1)], shapes[(b.track, b.channel - 1)]
            if len(sa & sb) >= 0.9 * max(len(sa), len(sb)):
                a.double_of = b.id
                break
    return out


#: Krumhansl–Kessler key profiles.
_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _progressions() -> list[list[int]]:
    from .patterns import library as lib
    out = []
    for p in lib.PROGRESSIONS:
        roots = [int(x) for x in p.text.split("|")[0].split()]
        if roots not in out:
            out.append(roots)
    return out


def sparta_key(notes: list) -> Optional[tuple[int, bool]]:
    """The key the way Sparta bases have it: the root the progression starts from (D in D, Eb, C, Eb).
    The lowest note of every half bar is matched against the Sparta progressions in every key; a
    progression explaining at least half of them names the key.  None when none does."""
    lows: dict[int, int] = {}
    for n in notes:
        if n.channel == 9:
            continue
        w = int(n.start // 2)                        # half bars of 4/4 (two beats)
        if n.start - 2 * w < 1.0 and (w not in lows or n.pitch < lows[w]):
            lows[w] = n.pitch
    if len(lows) < 4:
        return None
    best = (0, 2, 0)
    for prog in _progressions():
        for k in range(12):
            for phase in range(len(prog)):
                score = sum(1 for w, low in lows.items() if (low - k - prog[(w + phase) % len(prog)]) % 12 == 0)
                if score > best[0] or (score == best[0] and k == 2 and best[1] != 2):
                    best = (score, k, phase)
    score, k, _ = best
    if score < 0.5 * len(lows):
        return None
    third = [0.0, 0.0]
    for n in notes:
        if n.channel != 9:
            iv = (n.pitch - k) % 12
            if iv in (3, 4):
                third[iv - 3] += n.dur
    return k, third[0] > third[1]


def estimate_key(notes: list) -> tuple[int, bool]:
    """(root pitch class, minor) from the notes' durations (drums left out)."""
    hist = [0.0] * 12
    for n in notes:
        if n.channel != 9:
            hist[n.pitch % 12] += min(n.dur, 4.0)
    if sum(hist) <= 0:
        return 2, False

    def corr(profile, root):
        xs = [hist[(root + i) % 12] for i in range(12)]
        mx, my = sum(xs) / 12, sum(profile) / 12
        num = sum((a - mx) * (b - my) for a, b in zip(xs, profile))
        den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in profile)) or 1.0
        return num / den

    best = max(((corr(_MAJOR, r) + (0.02 if r == 2 else 0.0), r, False) for r in range(12)))
    best_minor = max(((corr(_MINOR, r) + (0.02 if r == 2 else 0.0), r, True) for r in range(12)))
    top = max(best, best_minor)
    return top[1], top[2]


# ── roles ────────────────────────────────────────────────────────────────────


def suggest_roles(song: MidiSong) -> dict[str, dict]:
    """A first mapping: drums to the drum map, the busiest melodic channel (by note starts) to the main
    pitch, a bass channel (by its name, else the lowest) to the bass, a chordal one to the chords, the rest
    to the other pitches (then off).  A channel doubling another starts off — one line, one pitch."""
    mapping: dict[str, dict] = {}
    melodic = []
    for p in song.parts:
        n = p.name.lower()
        if p.double_of:
            mapping[p.id] = {"role": "off"}
        elif p.drums or any(w in n for w in ("drum", "perc", "kick", "snare", "hat", "cymbal")):
            role = "drums" if p.drums or "drum" in n or "perc" in n else next(
                r for r in ("kick", "snare", "hat", "crash") if r in n or (r == "crash" and "cymbal" in n))
            mapping[p.id] = {"role": role}
        elif any(w in n for w in ("chorus", "phrase", "vocal", "voice", "sample", "quote")):
            mapping[p.id] = {"role": "quotes" if "quote" in n else "chorus"}
        else:
            melodic.append(p)
    if melodic:
        named = [p for p in melodic if "bass" in p.name.lower()]
        bass = min(named or melodic, key=lambda p: p.median)
        if named or bass.median < 52:
            mapping[bass.id] = {"role": "bass"}
            melodic.remove(bass)
    chordal = [p for p in melodic if p.polyphony >= 3 and any(w in p.name.lower() for w in ("chord", "pad", "string"))]
    chordal = chordal or [p for p in melodic if p.polyphony >= 3]
    lead_pool = [p for p in melodic if p not in chordal[:1]] or melodic
    free = list(PITCH_ROLES)
    for p in sorted(lead_pool, key=lambda p: -p.onsets):
        mapping[p.id] = {"role": free.pop(0) if free else "off"}
    for p in chordal[:1]:
        if p.id not in mapping:
            mapping[p.id] = {"role": "chords"}
    for p in song.parts:
        mapping.setdefault(p.id, {"role": "off"})
        mapping[p.id].setdefault("octave", 0)
    return mapping


def clean_mapping(song: MidiSong, mapping: Optional[dict]) -> dict[str, dict]:
    """A mapping with every part in it, known roles only."""
    out = suggest_roles(song) if mapping is None else {}
    for p in song.parts:
        m = (mapping or {}).get(p.id) or out.get(p.id) or {"role": "off"}
        if isinstance(m, str):
            m = {"role": m}
        role = m.get("role", "off")
        if role not in ROLES:
            raise ValueError(f"{p.name}: unknown role {role!r}")
        out[p.id] = {"role": role, "octave": int(m.get("octave", 0)), "gain_db": float(m.get("gain_db", 0.0))}
    return out


# ── the remix ────────────────────────────────────────────────────────────────


def _ref_pitch(key_pc: int, median: int) -> int:
    """The key root nearest to a part's middle note: its notes become semitones around the sample's root."""
    base = median - ((median - key_pc) % 12)
    return base + 12 if median - base > 6 else base


# ── the base's structure ─────────────────────────────────────────────────────


@dataclass
class MidiSection:
    kind: str                   # intro | chorus | dundundenden | epicness | madness | ending
    start: int                  # first bar
    bars: int

    @property
    def end(self) -> int:
        return self.start + self.bars


def bar_parts(song: MidiSong) -> list[set]:
    """The parts playing in each bar: a note starting in it, or sounding in it for a 16th or more."""
    bars = song.bars
    out: list[set] = [set() for _ in range(bars)]
    for n in song.notes:
        pid = f"t{n.track}c{n.channel}"
        a, z = n.start, n.start + n.dur
        b = int(a // 4)
        if b < bars:
            out[b].add(pid)
        b += 1
        while b < bars and b * 4 + 0.25 <= z:
            out[b].add(pid)
            b += 1
    return out


def _distance(a: set, b: set) -> float:
    """How different two sets of playing parts are: 0 = the same, 1 = nothing in common."""
    return len(a ^ b) / max(1, len(a | b))


def _grid(parts: list[set]) -> int:
    """The bar the base's 4-bar phrases count from (0-3): where its parts come in and drop out.  A one-bar
    pickup puts it at 1."""
    score = [0.0] * 4
    for b in range(1, len(parts)):
        score[b % 4] += _distance(parts[b - 1], parts[b])
    best = max(range(4), key=lambda o: score[o])
    return best if score[best] > 1.25 * score[0] + 0.2 else 0


def song_structure(song: MidiSong) -> list[MidiSection]:
    """The base's parts the way Sparta bases have them, read from what its channels play: the Chorus is
    the full texture that comes back most, the Intro is what comes before the first Chorus (at most 8 bars),
    the Ending a sparse tail; a dip after the first Chorus is the DunDunDenDen, the deepest one later the
    Madness, and another full texture an Epicness.  Phrases are 4 bars, counted from the first bar where the
    parts change on that grid (a one-bar pickup makes a one-bar Intro)."""
    parts = bar_parts(song)
    bars = len(parts)
    if bars < 6:
        return [MidiSection("chorus", 0, bars)]
    o = _grid(parts)
    cuts = sorted({0, bars, *range(o, bars, 4)})
    blocks = []
    for a, z in zip(cuts, cuts[1:]):
        seen: dict[str, int] = {}
        for b in range(a, z):
            for p in parts[b]:
                seen[p] = seen.get(p, 0) + 1
        texture = {p for p, k in seen.items() if 2 * k >= z - a}
        count = sum(len(parts[b]) for b in range(a, z)) / (z - a)
        blocks.append({"a": a, "z": z, "tex": texture, "n": count})
    peak = max(bl["n"] for bl in blocks)
    for bl in blocks:
        bl["full"] = bl["n"] >= 0.6 * peak and bl["z"] - bl["a"] >= 2
    # The Chorus: the full texture that comes back most often, far apart in time.
    full = [bl for bl in blocks if bl["full"]]
    if not full:
        return [MidiSection("chorus", 0, bars)]

    def like(x, y) -> bool:
        return _distance(x["tex"], y["tex"]) <= 0.34

    proto = max(full, key=lambda x: (sum(y["z"] - y["a"] for y in full if like(x, y) and abs(y["a"] - x["a"]) >= 8),
                                     -x["a"]))
    for bl in blocks:
        bl["kind"] = "chorus" if bl["full"] and like(bl, proto) else ("epicness" if bl["full"] else "dip")
    # The Intro ends where the first Chorus starts, or after a gap the base climbs out of (a sparse bar in
    # its first 8, the break before the drop) — at most 8 bars.
    chorus_n = [bl["n"] for bl in blocks if bl["kind"] == "chorus"] or [peak]
    size = sum(chorus_n) / len(chorus_n)
    sparse = [len(p) <= 0.6 * size for p in parts]
    intro_end = next((bl["a"] for bl in blocks if bl["kind"] == "chorus"), 0)
    intro_end = intro_end if intro_end <= 8 else 0
    for b in range(min(8, bars - 1)):
        if sparse[b] and not sparse[b + 1]:
            intro_end = max(intro_end, b + 1)
    if intro_end:
        cut = []
        for bl in blocks:
            if bl["z"] <= intro_end:
                bl["kind"] = "intro"
            elif bl["a"] < intro_end:
                cut.append(bl)
        for bl in cut:                               # the block the Intro ends in: its Intro bars split off
            i = blocks.index(bl)
            blocks.insert(i, dict(bl, z=intro_end, kind="intro"))
            bl["a"] = intro_end
    if not any(bl["kind"] == "chorus" for bl in blocks):
        nxt = next((bl for bl in blocks if bl["kind"] != "intro"), blocks[-1])
        nxt["kind"] = "chorus"
    first = next(i for i, bl in enumerate(blocks) if bl["kind"] == "chorus")
    # The Ending: a short sparse tail.
    tail = len(blocks)
    while tail - 1 > first and blocks[tail - 1]["kind"] == "dip" and bars - blocks[tail - 1]["a"] <= 4:
        tail -= 1
    for bl in blocks[tail:]:
        bl["kind"] = "ending"
    # Dips between (a run of sparse blocks is one): right after the first Chorus the DunDunDenDen, the
    # deepest of the others the Madness.
    runs: list[list[int]] = []
    for i, bl in enumerate(blocks):
        if bl["kind"] == "dip":
            if runs and runs[-1][-1] == i - 1:
                runs[-1].append(i)
            else:
                runs.append([i])
    after_first = first
    while after_first + 1 < len(blocks) and blocks[after_first + 1]["kind"] == "chorus":
        after_first += 1
    dun = runs[0] if runs and runs[0][0] == after_first + 1 else None
    others = [r for r in runs if r is not dun]
    if others and bars >= 16:
        deepest = min(others, key=lambda r: (sum(blocks[i]["n"] for i in r) / len(r), -r[0]))
        for i in deepest:
            blocks[i]["kind"] = "madness"
    for r in runs:
        for i in r:
            if blocks[i]["kind"] == "dip":
                blocks[i]["kind"] = "dundundenden"
    # Neighbouring blocks of one kind are one part (the Chorus blocks join below).
    out: list[MidiSection] = []
    for bl in blocks:
        if out and out[-1].kind == bl["kind"] and bl["kind"] != "chorus":
            out[-1].bars += bl["z"] - bl["a"]
        else:
            out.append(MidiSection(bl["kind"], bl["a"], bl["z"] - bl["a"]))
    return _join_choruses(out, blocks)


def _join_choruses(secs: list[MidiSection], blocks: list[dict]) -> list[MidiSection]:
    """Chorus blocks in a row are one Chorus while they play the same parts, up to 8 bars each."""
    tex = {bl["a"]: bl["tex"] for bl in blocks}
    out: list[MidiSection] = []
    for s in secs:
        prev = out[-1] if out else None
        if (prev is not None and prev.kind == s.kind == "chorus" and prev.bars + s.bars <= 8
                and _distance(tex.get(prev.start, set()), tex.get(s.start, set())) <= 0.2):
            prev.bars += s.bars
        else:
            out.append(MidiSection(s.kind, s.start, s.bars))
    return out


#: The name and frame of each kind of section on a MIDI base: a box per line (the Madness: its words).
SECTION_LOOK = {"intro": ("Intro", "main"), "chorus": ("Chorus", "main"), "dundundenden": ("DunDunDenDen", "main"),
                "epicness": ("Epicness", "main"), "madness": ("Madness", "split2"), "ending": ("Ending", "main")}


def build_from_midi(song: MidiSong, mapping: Optional[dict] = None, auto_percussion: bool = True,
                    auto_phrase: bool = True, key: Optional[str] = None, title: str = "Sparta Remix",
                    pitching: str = "normal", polish: str = "normal", section_bars: int = 8,
                    perc_pattern: str = "perc.sparta"):
    """The remix on a MIDI base: its notes played by the samples (a track per enabled part), in the base's own
    parts (see :func:`song_structure`) — the main phrase comes in where the base's Chorus does, with the
    part's own pattern (Chorus, DunDunDenDen chops, Epicness, Madness words, quotes in the Intro and at the
    Ending), and the percussion where the MIDI has none."""
    from .arrangement import Arrangement, SectionSpec, TrackSpec, _crash, _drums, _perc_layers, _placements
    from .audio.pitch import pitch_class
    from .patterns.notation import ORIGINAL_PROGRESSION
    m = clean_mapping(song, mapping)
    key_pc = pitch_class(key) if key else song.key_pc
    enabled = [p for p in song.parts if m[p.id]["role"] != "off"]
    if not enabled and not auto_percussion:
        raise ValueError("every MIDI part is off — give at least one a role")
    steps_per_beat = STEPS_PER_BAR / 4.0
    roles = {m[p.id]["role"] for p in enabled}
    has_drums = bool(roles & set(DRUM_ROLES))
    structure: list[MidiSection] = []
    for sec in song_structure(song):             # long parts split at section_bars (on 4-bar lines)
        size = max(4, section_bars // 4 * 4)
        if sec.kind in ("chorus", "epicness") and sec.bars > max(section_bars, 4):
            for a in range(sec.start, sec.end, size):
                structure.append(MidiSection(sec.kind, a, min(size, sec.end - a)))
        else:
            structure.append(sec)
    by_part: dict[str, list[MidiNote]] = {}
    for n in song.notes:
        by_part.setdefault(f"t{n.track}c{n.channel}", []).append(n)
    opts = {"minor": song.minor, "base": True}
    totals = {k: sum(1 for x in structure if x.kind == k) for k in SECTION_LOOK}
    sections = []
    counts: dict[str, int] = {}
    for sec in structure:
        kind, bars = sec.kind, sec.bars
        label, layout = SECTION_LOOK.get(kind, ("Part", "main"))
        counts[label] = counts.get(label, 0) + 1
        name = label if totals.get(kind, 0) <= 1 else f"{label} {counts[label]}"
        tracks = []
        s0, s1 = sec.start * STEPS_PER_BAR, sec.end * STEPS_PER_BAR
        for p in enabled:
            ns = [n for n in by_part.get(p.id, []) if s0 <= n.start * steps_per_beat < s1]
            if ns:
                tr = _part_track(p, m[p.id]["role"], ns, s0, key_pc, m[p.id], steps_per_beat)
                if kind == "madness" and tr.stem != "quotes" and tr.kind != "words":
                    tr.visual = "none"          # the Madness shows its words; the base plays under them
                tracks.append(tr)
        if auto_phrase:
            tracks = _phrase_tracks(kind, bars, roles, opts) + tracks
        if auto_percussion and not has_drums:
            if kind in ("chorus", "epicness", "madness"):
                tracks += _perc_layers(perc_pattern, gain=-3.0 if kind == "madness" else 0.0, suffix="_auto")
                tracks.append(_crash(0.0, tid="crash_auto", visual="hit" if layout == "main" else "crash"))
            elif kind == "dundundenden":
                # It builds: the percussion joins a third of the way in.
                start = max(1, round(bars / 3)) if bars > 1 else 0
                tracks += _perc_layers(perc_pattern, start_bar=start, suffix="_auto")
                tracks.append(_crash(start, tid="crash_auto"))
            elif kind == "intro" and bars >= 2:
                tracks += _drums("build", start_bar=bars - 1, gain=-4.0, suffix="_auto")
            elif kind == "ending":
                hit = "text:" + _placements(bars * STEPS_PER_BAR, [(0, "1")])
                tracks += [TrackSpec("kick_auto", "drum", hit, mode="index", slots={"1": "kick"}, pitched=False,
                                     visual="none", stem="drums"),
                           TrackSpec("snare_auto", "drum", hit, mode="index", slots={"1": "clap"}, pitched=False,
                                     visual="none", stem="drums"),
                           _crash(0.0, -4.0, tid="crash_auto", visual="none")]
        if not tracks:
            tracks.append(TrackSpec("rest", "oneshot", "text:" + "_" * STEPS_PER_BAR, mode="index", visual="none"))
        sections.append(SectionSpec(kind, bars, tracks, name, layout=layout))
    return Arrangement(title=title, variant="midi", bpm=float(song.bpm), key=NOTE_NAMES[key_pc],
                       progression=ORIGINAL_PROGRESSION, pitching=pitching, polish=polish, sections=sections)


def _phrase_tracks(kind: str, bars: int, roles: set, opts: dict) -> list:
    """The source's main phrase, quotes and words for one part of a MIDI base (none a channel plays already):
    the part's own pattern from the usual section builders."""
    from .arrangement import (SLOTS_CHORUS, TrackSpec, _placements, sec_dundundenden, sec_ending, sec_epicness,
                              sec_madness)
    phrase = "chorus" in roles
    total = bars * STEPS_PER_BAR
    if kind == "chorus" and not phrase:
        return [TrackSpec("main_auto", "pitch", "chorus.standard", mode="index", slots=dict(SLOTS_CHORUS),
                          pitched=False, crisp=True, gain_db=-1.0, visual="main", flip="alternate", stem="chorus")]
    if kind == "epicness" and not phrase:
        return [t for t in sec_epicness(bars, opts).tracks if t.stem == "chorus"]
    if kind == "dundundenden" and not phrase:
        return [t for t in sec_dundundenden(bars, opts).tracks if t.stem == "chorus"]
    if kind == "madness" and "words" not in roles:
        return [t for t in sec_madness(bars, opts).tracks if t.kind == "words"]
    if kind == "intro" and bars >= 2 and "quotes" not in roles:
        hits = [(0, "1")] + ([(total // 2, "2")] if bars >= 4 else [])
        return [TrackSpec("quotes_auto", "oneshot", "text:" + _placements(total, hits), mode="index",
                          slots={"1": "quote1", "2": "quote2"}, oneshot=True, pitched=False, gain_db=-2.0,
                          visual="center", flip="none", choke=True, stem="quotes")]
    if kind == "ending" and "quotes" not in roles:
        return [t for t in sec_ending(bars, opts).tracks if t.id == "quote"]
    return []


def _part_track(p: MidiPart, role: str, ns: list, s0: float, key_pc: int, mp: dict, spb: float):
    from .arrangement import TrackSpec
    tid = f"midi_{p.id}"
    gain = float(mp.get("gain_db", 0.0))
    octave = int(mp.get("octave", 0))
    rows = []

    def st(n):
        return round(n.start * spb - s0, 4)

    def du(n):
        return max(0.25, round(n.dur * spb, 4))

    if role in DRUM_ROLES:
        if role == "drums":
            for n in ns:
                rows.append([st(n), du(n), GM_DRUMS.get(n.pitch, 8), 0])
            slots = DRUM_SLOTS
        else:
            sample, g, vis = SINGLE_DRUM[role]
            rows = [[st(n), du(n), 1, 0] for n in ns]
            slots = {"1": {"sample": sample, "gain": g, "visual": vis}}
        return TrackSpec(tid, "drum", "notes", mode="index", slots=dict(slots), notes=_sorted(rows), gain_db=gain,
                         pitched=False, oneshot=True, choke=False, visual="kick", flip="alternate", stem="drums")
    if role in ("chorus", "quotes", "words"):
        order = sorted({n.pitch for n in ns})
        rows = [[st(n), du(n), order.index(n.pitch) + 1, 0] for n in ns]
        if role == "chorus":
            return TrackSpec(tid, "pitch", "notes", mode="index", slots={"1": "chorus_a", "2": "chorus_b",
                                                                            "3": "chorus_c"},
                             notes=_sorted(rows), pitched=False, crisp=True, gain_db=gain, visual="main",
                             flip="alternate", stem="chorus")
        if role == "quotes":
            return TrackSpec(tid, "oneshot", "notes", mode="index", slots={"1": "quote1", "2": "quote2", "3": "quote3"},
                             notes=_sorted(rows), oneshot=True, pitched=False, choke=True, gain_db=gain,
                             visual="center", flip="none", stem="quotes")
        return TrackSpec(tid, "words", "notes", mode="index", slots={"1": "word_a", "2": "word_b"}, notes=_sorted(rows),
                         pitched=False, gain_db=gain, visual="madness", flip="none")
    ref = _ref_pitch(key_pc, p.median) - 12 * octave
    if role == "chords":
        by_start: dict[float, list] = {}
        for n in ns:
            by_start.setdefault(st(n), []).append(n)
        for t0, group in by_start.items():
            for v, n in enumerate(sorted(group, key=lambda n: n.pitch)[:3]):
                rows.append([t0, du(n), n.pitch - ref, v])
        return TrackSpec(tid, "pitch", "notes", mode="semitone", sample="pitch2",
                         voice_samples=["pitch2", "pitch3", "pitch4"], notes=_sorted(rows), sustain=True,
                         gain_db=gain - 8.0, visual="voices", flip="alternate", stem="pitch_layers")
    # One pitch sample: the top note of each chord (the bass: the lowest).
    by_start = {}
    for n in ns:
        k = st(n)
        cur = by_start.get(k)
        if cur is None or (n.pitch < cur.pitch if role == "bass" else n.pitch > cur.pitch):
            by_start[k] = n
    rows = [[k, du(n), n.pitch - ref, 0] for k, n in by_start.items()]
    if role == "bass":
        return TrackSpec(tid, "bass", "notes", mode="semitone", sample="bass", notes=_sorted(rows), sustain=True,
                         gain_db=gain - 2.0, visual="bass", stem="bass")
    return TrackSpec(tid, "pitch", "notes", mode="semitone", sample=role, notes=_sorted(rows), crisp=True,
                     sustain=True, gain_db=gain - (0.0 if role == "pitch1" else 4.0), visual="pitch_cycle",
                     flip="alternate")


def _sorted(rows: list) -> list:
    return sorted(rows, key=lambda r: (r[0], r[3]))


# ── writing ──────────────────────────────────────────────────────────────────


def _vlq_bytes(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def write_midi(path: str, tracks: list[dict], bpm: float = 140.0, tpb: int = 480,
               key_sig: Optional[tuple[int, int]] = None) -> str:
    """A format-1 MIDI file.  ``tracks``: [{"name", "channel" (0-15), "program", "notes": [(start beat,
    length in beats, pitch, velocity), …]}, …]."""
    chunks = []
    meta = bytearray()
    us = int(round(60_000_000 / bpm))
    meta += b"\x00\xFF\x51\x03" + us.to_bytes(3, "big")
    meta += b"\x00\xFF\x58\x04\x04\x02\x18\x08"
    if key_sig is not None:
        meta += b"\x00\xFF\x59\x02" + struct.pack("b", key_sig[0]) + bytes([key_sig[1]])
    meta += b"\x00\xFF\x2F\x00"
    chunks.append(bytes(meta))
    for tr in tracks:
        ch = int(tr.get("channel", 0)) & 0x0F
        evs = []
        for st, du, pitch, vel in tr.get("notes", []):
            a = int(round(st * tpb))
            b = max(a + 1, int(round((st + du) * tpb)))
            evs.append((a, 1, bytes([0x90 | ch, pitch & 0x7F, max(1, min(127, int(vel)))])))
            evs.append((b, 0, bytes([0x80 | ch, pitch & 0x7F, 0])))
        evs.sort(key=lambda e: (e[0], e[1]))
        body = bytearray()
        name = str(tr.get("name", "")).encode("latin-1", "replace")[:120]
        if name:
            body += b"\x00\xFF\x03" + _vlq_bytes(len(name)) + name
        if tr.get("program") is not None and int(tr.get("program", -1)) >= 0:
            body += b"\x00" + bytes([0xC0 | ch, int(tr["program"]) & 0x7F])
        last = 0
        for tick, _o, msg in evs:
            body += _vlq_bytes(tick - last) + msg
            last = tick
        body += b"\x00\xFF\x2F\x00"
        chunks.append(bytes(body))
    with open(path, "wb") as fh:
        fh.write(b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), tpb))
        for c in chunks:
            fh.write(b"MTrk" + struct.pack(">I", len(c)) + c)
    return path


def arrangement_to_midi(arr, events, path: str) -> str:
    """The remix's notes as a MIDI file (a track per stem; drums on channel 10), for a DAW."""
    from .arrangement import NoteEvent  # noqa: F401  (type of events)
    beat_s = 60.0 / arr.bpm
    root = 62 + (NOTE_NAMES.index(arr.key) - 2 if arr.key in NOTE_NAMES else 0)
    drum_notes = {"kick": 36, "snare": 38, "clap": 39, "hat_closed": 42, "hat_open": 46, "hat2": 51, "crash": 49,
                  "perc": 45}
    stems: dict[str, list] = {}
    for e in events:
        stems.setdefault(e.stem, []).append(e)
    tracks = []
    ch = 0
    for stem, evs in sorted(stems.items()):
        is_drum = stem == "drums" or all(not e.pitched for e in evs) and any(e.sample in drum_notes for e in evs)
        notes = []
        for e in evs:
            if is_drum:
                pitch = drum_notes.get(e.sample, 45)
            else:
                pitch = root + int(round(e.semis)) + (-12 if e.kind == "bass" else 0)
            notes.append((e.t / beat_s, max(0.05, min(e.dur, e.max_len or e.dur) / beat_s), pitch, 100))
        channel = 9 if is_drum else ch
        if not is_drum:
            ch = ch + 1 if ch + 1 != 9 else 10
            ch %= 16
        tracks.append({"name": stem, "channel": channel, "notes": notes})
    return write_midi(path, tracks, bpm=arr.bpm)
