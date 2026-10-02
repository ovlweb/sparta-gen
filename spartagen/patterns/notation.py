"""Parser for the Sparta Remix Wiki pitch-pattern notation.

Key symbols (Sparta Remix Wiki, "Pitch Patterns"):

    ***  4th note          **  "6th note" (3 sixteenths)     *  8th note
    #    root key/note      +#  shifted up # semitones        -#  shifted down
    0    16th note          _   16th rest                     '   32nd note
    "    64th note          /   32nd rest                     \\   64th rest
    |    semi-progression (split) in progressions
    B    (index patterns) slots 1 and 2 at the same time

A bare number is a 16th note.  Longer asterisk runs used on the wiki are read
as ***** = dotted quarter (6) and ****** = half note (8); both are needed to
make e.g. "Vektor" and the "Chords"/"Tungsten" patterns add up to 2 bars.

Three notations are in circulation and all are supported:

* ``semitone`` — ``0* 12* 1* 13*``: signed numbers are semitones from the
  root (0 = D in the classic bases); numbers may have several digits.
* ``compact``  — ``00_00_0011_11_11-2-2_…`` (Madness "First Pattern"):
  every digit is its own note, a sign applies to the digit after it.
* ``index``    — ``11_11_111_1_1_11222_2_…`` (the standard Chorus, the
  Madness call & response): each digit picks a *slot* (1 = main pitch /
  first person, 2 = second pitch / second person, …) and the note follows
  the base's chord progression.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

STEPS_PER_BAR = 16

#: asterisk run length → duration in 16th steps
ASTERISKS = {1: 2.0, 2: 3.0, 3: 4.0, 4: 5.0, 5: 6.0, 6: 8.0, 7: 10.0, 8: 12.0, 9: 16.0}


@dataclass
class PNote:
    start: float          # 16th steps from pattern start
    dur: float            # 16th steps
    value: int            # semitones (semitone/compact) or slot digit (index)
    voice: int = 0        # line number for multi-line (chord) patterns
    sharp: int = 0        # '#' after an index digit raises it a semitone

    def to_dict(self) -> dict:
        return {"start": self.start, "dur": self.dur, "value": self.value, "voice": self.voice, "sharp": self.sharp}


@dataclass
class ParsedPattern:
    notes: list[PNote]
    length: float                  # steps, longest voice
    mode: str                      # semitone | compact | index
    voices: int = 1
    warnings: list[str] = field(default_factory=list)

    @property
    def bars(self) -> float:
        return self.length / STEPS_PER_BAR

    def padded_length(self, unit: int = STEPS_PER_BAR) -> float:
        """Length rounded up to whole bars (or beats with unit=4)."""
        if self.length <= 0:
            return float(unit)
        import math
        return math.ceil(self.length / unit - 1e-9) * unit

    def loop_length(self) -> float:
        """How long one repetition lasts when the pattern is looped.

        Short cells (a half bar or less, e.g. "Fruit") loop on the half bar.
        Transcriptions that spill over a bar line by at most one 16th (a
        frequent wiki typo) are trimmed back instead of padded to a new bar.
        """
        import math
        if self.length <= 0:
            return float(STEPS_PER_BAR)
        if self.length <= 8.0 + 1e-9:
            return 8.0
        floor_bars = math.floor(self.length / STEPS_PER_BAR + 1e-9) * STEPS_PER_BAR
        if floor_bars > 0 and self.length - floor_bars <= 1.0 + 1e-9:
            return float(floor_bars)
        return self.padded_length()

    def values(self) -> list[int]:
        return [n.value for n in self.notes]

    def to_dict(self) -> dict:
        return {"notes": [n.to_dict() for n in self.notes], "length": self.length, "mode": self.mode,
                "voices": self.voices, "bars": self.bars, "warnings": self.warnings}


_DIGIT_RUN = re.compile(r"\d+")


def detect_mode(text: str) -> str:
    """Guess which notation a pattern string uses."""
    body = text.replace("\n", " ")
    runs = _DIGIT_RUN.findall(body)
    if not runs:
        return "semitone"
    compact_like = any(
        (len(r) >= 2 and r[0] == "0")
        or int(r) > 36
        or (len(r) >= 3 and len(set(r)) == 1)
        for r in runs
    )
    has_sign = bool(re.search(r"[-+]\s*\d", body))
    has_zero_note = bool(re.search(r"(?<!\d)0(?!\d)", body)) or any(r[0] == "0" for r in runs)
    if compact_like:
        return "compact" if (has_sign or has_zero_note) else "index"
    if not has_sign and not has_zero_note and all(len(r) == 1 for r in runs):
        # Space-separated single digits reaching 5+ read as semitones ("SonyFive");
        # slot patterns written with spaces only use a few slots (Madness 1/2).
        spaced = bool(re.search(r"\d[*'\"]*\s+\d", body))
        if spaced and max(int(r) for r in runs) >= 5:
            return "semitone"
        return "index"
    return "semitone"


def _parse_line(line: str, mode: str, voice: int, warnings: list[str]) -> tuple[list[PNote], float]:
    notes: list[PNote] = []
    t = 0.0
    i, n = 0, len(line)
    last: Optional[PNote] = None
    while i < n:
        c = line[i]
        if c in " \t,|":
            i += 1
            continue
        if c == "_":
            t += 1.0
            last = None
            i += 1
            continue
        if c == "/":
            t += 0.5
            last = None
            i += 1
            continue
        if c == "\\":
            t += 0.25
            last = None
            i += 1
            continue
        if c == "=":  # tie: hold the previous note one more 16th
            if last is not None:
                last.dur += 1.0
            t += 1.0
            i += 1
            continue
        if c == "B" and mode == "index":  # "B" = slots 1 and 2 together (Madness freestyles)
            m = i + 1
            stars = 0
            while m < n and line[m] == "*":
                stars += 1
                m += 1
            dur = ASTERISKS.get(stars, 16.0) if stars else 1.0
            if not stars and m < n and line[m] == "'":
                dur, m = 0.5, m + 1
            for value in (1, 2):
                notes.append(PNote(t, dur, value, voice))
            last = notes[-1]
            t += dur
            i = m
            continue
        if c in "+-" or c.isdigit():
            sign = 1
            j = i
            if c in "+-":
                sign = -1 if c == "-" else 1
                j += 1
                while j < n and line[j] == " ":
                    j += 1  # tolerate "- 2" typos
                if j >= n or not line[j].isdigit():
                    if c == "-" and last is not None:  # "1-" in index freestyles = hold
                        last.dur += 1.0
                        t += 1.0
                    i = j
                    continue
            if mode == "semitone":
                k = j
                while k < n and line[k].isdigit():
                    k += 1
            else:
                k = j + 1
            value = sign * int(line[j:k])
            m = k
            stars = 0
            while m < n and line[m] == "*":
                stars += 1
                m += 1
            if stars:
                dur = ASTERISKS.get(stars, 16.0)
            elif m + 1 < n and line[m] == "'" and line[m + 1] == "'":  # '' typed for "
                dur = 0.25
                m += 2
            elif m < n and line[m] == "'":
                dur = 0.5
                m += 1
            elif m < n and line[m] == '"':
                dur = 0.25
                m += 1
            else:
                dur = 1.0
            sharp = 0
            while mode == "index" and m < n and line[m] == "#":
                sharp += 1
                m += 1
            note = PNote(t, dur, value, voice, sharp)
            notes.append(note)
            last = note
            t += dur
            i = m
            continue
        if c in "*'\"#":
            warnings.append(f"stray '{c}' at column {i + 1} ignored")
            i += 1
            continue
        warnings.append(f"unknown symbol '{c}' at column {i + 1} ignored")
        i += 1
    return notes, t


def parse(text: str, mode: str = "auto") -> ParsedPattern:
    """Parse a (possibly multi-line) pattern. Each non-empty line is a voice."""
    if mode == "auto":
        mode = detect_mode(text)
    if mode not in ("semitone", "compact", "index"):
        raise ValueError(f"unknown notation mode {mode!r}")
    warnings: list[str] = []
    notes: list[PNote] = []
    length = 0.0
    lines = [ln for ln in text.replace("\r", "").split("\n") if ln.strip()]
    for v, line in enumerate(lines):
        ln_notes, ln_len = _parse_line(line.strip(), mode, v, warnings)
        notes += ln_notes
        length = max(length, ln_len)
    if not notes:
        warnings.append("pattern has no notes")
    return ParsedPattern(notes, length, mode, max(1, len(lines)), warnings)


# ── Writing ──────────────────────────────────────────────────────────────────

#: How long notes are marked (16th steps → asterisks); other lengths add ties ("=": one 16th more each).
_MARKS = {1.0: "", 2.0: "*", 3.0: "**", 4.0: "***", 5.0: "****", 6.0: "*****", 8.0: "******", 10.0: "*******",
          12.0: "********", 16.0: "*********"}


def _length_mark(dur: float) -> tuple[str, str]:
    """A note's length as written after it: (its mark, its ties) — the longest mark it holds and a tie ("=")
    for each 16th more; a 32nd ("'") or a 64th ('"') then ties for the lengths that end between 16ths."""
    q = max(0.25, round(dur * 4) / 4)
    frac = q - int(q)
    if frac == 0.75:                       # (no mark ends there: the nearest 16th)
        q, frac = float(int(q) + 1), 0.0
    if frac == 0:
        base = max(k for k in _MARKS if k <= q)
        return _MARKS[base], "=" * int(q - base)
    return ("'" if frac == 0.5 else '"'), "=" * int(q)


def _rests(gap: float) -> str:
    g = round(gap * 4) / 4
    whole = int(g)
    rest = g - whole
    return "_" * whole + ("/" if rest >= 0.5 else "") + ("\\" if rest in (0.25, 0.75) else "")


def write(notes: list, mode: str = "semitone", length: float = 0.0) -> str:
    """Notes back as the wiki's notation — what :func:`parse` reads back as the same notes.  Each voice is a
    line (a chord's notes, or notes that sound together); ``length``: the steps every line runs to (rests at
    the end), so the pattern keeps its bars.  ``mode``: "semitone" (signed numbers, spaced) or "index" (a digit
    per slot)."""
    if mode not in ("semitone", "index"):
        raise ValueError("write semitone or index patterns")
    items = []
    for n in notes:
        d = n.to_dict() if isinstance(n, PNote) else dict(n)
        items.append(PNote(float(d["start"]), float(d["dur"]), int(d["value"]), int(d.get("voice", 0)),
                           int(d.get("sharp", 0))))
    lines: list[list[PNote]] = []
    for n in sorted(items, key=lambda n: (n.voice, n.start, n.value)):
        v = n.voice
        while v < len(lines) and lines[v] and lines[v][-1].start >= n.start - 1e-9:
            v += 1                        # two notes at once on a line: the next line takes one
        while len(lines) <= v:
            lines.append([])
        line = lines[v]
        if line and line[-1].start + line[-1].dur > n.start:
            line[-1].dur = n.start - line[-1].start           # a line plays one note at a time
        line.append(PNote(n.start, n.dur, n.value, v, n.sharp))
    out = []
    for line in lines or [[]]:
        t, tokens = 0.0, []
        for n in line:
            if n.start - t >= 0.25 - 1e-9:
                tokens.append(_rests(n.start - t))
            mark, ties = _length_mark(n.dur)
            if mode == "index":
                if not -9 <= n.value <= 9:
                    raise ValueError(f"slot {n.value} cannot be written (one digit each)")
                tokens.append(f"{n.value}{mark}{'#' * n.sharp}{ties}")       # (sharps before the ties)
            else:
                tokens.append(f"{n.value}{mark}{ties}")
            t = n.start + round(max(0.25, n.dur) * 4) / 4
        if length - t >= 0.25 - 1e-9:
            tokens.append(_rests(length - t))
        out.append(("" if mode == "index" else " ").join(tokens) or "_")
    return "\n".join(out)


# ── Progressions ─────────────────────────────────────────────────────────────


@dataclass
class Progression:
    """Chord roots (semitones from the key root), one per ``chord_steps``."""

    roots: list[list[int]]        # each chord slot may be split into equal parts
    chord_steps: float = 8.0      # half a bar per chord in the classic bases

    @property
    def cycle_steps(self) -> float:
        return self.chord_steps * len(self.roots)

    def root_at(self, step: float) -> int:
        if not self.roots:
            return 0
        pos = step % self.cycle_steps
        idx = int(pos // self.chord_steps)
        parts = self.roots[idx]
        within = pos - idx * self.chord_steps
        sub = min(len(parts) - 1, int(within // (self.chord_steps / len(parts))))
        return parts[sub]

    def slot_index(self, step: float) -> tuple[int, int]:
        pos = step % self.cycle_steps
        idx = int(pos // self.chord_steps)
        parts = self.roots[idx]
        within = pos - idx * self.chord_steps
        sub = min(len(parts) - 1, int(within // (self.chord_steps / len(parts))))
        return idx, sub

    def to_text(self) -> str:
        head = " ".join(str(p[0]) for p in self.roots)
        splits = [str(p[1]) for p in self.roots if len(p) > 1]
        return head + (" | " + " ".join(splits) if splits else "")


def parse_progression(text: str, chord_steps: float = 8.0) -> Progression:
    """'0 1 -2 1' or with a split: '0 1 2 1 | -1' (the last chord's second half)."""
    main, _, split = text.partition("|")
    roots = [[int(v)] for v in re.findall(r"[-+]?\d+", main)]
    if not roots:
        raise ValueError(f"empty progression {text!r}")
    extra = [int(v) for v in re.findall(r"[-+]?\d+", split)]
    if extra:
        roots[-1] = roots[-1] + extra
    return Progression(roots, chord_steps)


ORIGINAL_PROGRESSION = "0 1 -2 1"


def retarget(value: int, step: float, written_for: Progression, target: Progression) -> int:
    """Move a semitone note written over one progression onto another ("Progression Twist")."""
    a = written_for.root_at(step)
    b = target.root_at(step)
    return value + (b - a)
