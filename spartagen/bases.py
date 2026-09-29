"""Base templates: the bases a remix can be built on.

Sparta bases share their parts — the Chorus, the DunDunDenDen, the Epicness, the Awesomeness, the
Madness and the percussion under them work the same way on every base — and differ in tempo, key,
the order and length of their parts, and what their instruments play.  A template holds exactly that:

* **Bases** — the ones that come with SpartaGen: the Sparta Remix's own Extended base (its parts,
  tempo and key; the Chorus, pitch and percussion patterns of the wiki on them), and MIDI bases — the
  Stroll, Nana-iro, Blend S and Decline CTE bases, each with its MIDI, which of its instruments the
  samples play (lead, arps, chords, bass) and its parts bar for bar.
* **My templates** — saved by the user (any base, public or not) as ``*.spartabase.json`` files
  that can be shared.

A template drives the remix without a base file, guides the base analyzer when the base's audio is
loaded (its tempo is the analyzer's first guess, its patterns go on the detected parts) and can
replace the detected structure altogether.  A MIDI base's template loads its MIDI: the remix plays its
notes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from .patterns import library as lib

#: Plan kinds a template may use (see ``arrangement.build_arrangement``).
PLAN_KINDS = ("intro", "intro_hits", "intro3", "chorus", "chorus_final", "dundundenden", "epicness", "chords",
              "awesomeness1", "awesomeness2", "madness", "execution", "ending")
#: The parts a MIDI base's plan may use (see ``midi.build_from_midi``).
MIDI_PLAN_KINDS = ("intro", "chorus", "dundundenden", "epicness", "awesomeness", "madness", "ending")

GROUPS = ("Bases", "My templates")

#: Where the bases that come with SpartaGen keep their MIDI files.
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


@dataclass
class BaseTemplate:
    id: str
    name: str
    group: str = "My templates"
    bpm: float = 140.0
    key: str = "D"
    minor: bool = False
    plan: list = field(default_factory=list)       # [[kind, bars], …]
    options: dict = field(default_factory=dict)    # pattern choices for the parts (see arrangement.sec_*)
    pitching: str = "normal"                       # classic | normal | hard
    polish: str = "normal"                         # light | normal | hard
    progression: str = ""                          # "" = the original D, Eb, C, Eb
    description: str = ""
    credit: str = ""
    bpm_known: bool = True                         # False: 140 is only the usual tempo
    user: bool = False
    path: str = ""
    midi: str = ""                                 # a MIDI base: its file (in TEMPLATE_DIR for the built-in ones)
    roles: dict = field(default_factory=dict)      # a MIDI base: what the samples play of each part ({part id: role})

    @property
    def bars(self) -> int:
        return sum(int(b) for _k, b in self.plan)

    def midi_path(self) -> str:
        """The MIDI file of a MIDI base ("" for a base without one)."""
        if not self.midi or os.path.isabs(self.midi):
            return self.midi
        return os.path.join(TEMPLATE_DIR, self.midi)

    def midi_mapping(self) -> dict:
        """The roles as a MIDI mapping (``{part id: {"role", "octave", "gain_db"}}``)."""
        out = {}
        for pid, r in self.roles.items():
            out[pid] = dict(r) if isinstance(r, dict) else {"role": str(r)}
        return out

    @property
    def duration(self) -> float:
        return self.bars * 240.0 / float(self.bpm or 140.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bars"] = self.bars
        d["duration"] = round(self.duration, 2)
        return d

    @staticmethod
    def from_dict(d: dict) -> "BaseTemplate":
        t = BaseTemplate(id=str(d.get("id") or "template"), name=str(d.get("name") or "My base"))
        for k, v in d.items():
            if k in ("bars", "duration"):
                continue
            if hasattr(t, k):
                setattr(t, k, v)
        t.plan = [[str(k), int(b)] for k, b in (t.plan or [])]
        t.bpm = float(t.bpm or 140.0)
        return t

    def variant_def(self) -> dict:
        """The template in the form ``arrangement.build_arrangement`` reads."""
        return {"title": self.name if "Remix" in self.name else f"Sparta {self.name} Remix",
                "description": self.description, "bpm": self.bpm, "pitching": self.pitching,
                "polish": self.polish, "minor": self.minor, "key": self.key, "plan": [tuple(p) for p in self.plan],
                "options": dict(self.options), "progression": self.progression or None,
                "wiki_perc": self.options.get("wiki_perc", True),
                "intro_pattern": self.options.get("intro_pattern")}


# ── built-in templates ───────────────────────────────────────────────────────


def _std(vid: str, name: str, group: str = "Bases", **kw) -> BaseTemplate:
    from .arrangement import VARIANTS
    v = VARIANTS[vid]
    opts = {k: v[k] for k in ("intro_pattern",) if v.get(k)}
    opts["wiki_perc"] = bool(v.get("wiki_perc", False))
    plan = []
    for kind, bars in v["plan"]:
        base, _, arg = kind.partition(":")
        if base == "execution" and arg:
            opts["execution_pattern"] = arg
        plan.append([base, int(bars)])
    kw.setdefault("description", v["description"])
    return BaseTemplate(id=vid, name=name, group=group, bpm=float(v["bpm"]), minor=bool(v.get("minor", False)),
                        plan=plan, options=opts, pitching=v["pitching"], polish=v["polish"], **kw)


def _midi(tid: str, name: str, midi: str, bpm: float, key: str, minor: bool, plan: list, roles: dict,
          description: str, credit: str = "", **kw) -> BaseTemplate:
    """A MIDI base: its file, what the samples play of each of its parts, its parts bar for bar."""
    return BaseTemplate(id=tid, name=name, group="Bases", bpm=bpm, key=key, minor=minor, plan=plan, roles=roles,
                        midi=midi, description=description, credit=credit, options={"wiki_perc": True}, **kw)


def builtin_templates() -> list[BaseTemplate]:
    return [
        _std("extended", "Sparta Remix (Extended base)", credit="keatonkeaton999",
             description="The Sparta Remix's own base, the one most remixes are made on: 2:07 at 140 BPM in D — "
                         "Intro, Chorus, DunDunDenDen, Epicness, Awesomeness, Madness and the Final Chorus, with "
                         "the wiki's patterns on them. Load its audio (Base audio file) to play the remix over it."),
        _midi("stroll", "Sparta Stroll Base", "stroll.mid", 127.0, "C#", True,
              [["intro", 1], ["chorus", 8], ["chorus", 8], ["dundundenden", 4], ["chorus", 4], ["ending", 1]],
              {"t6c4": "pitch1",        # Greasy: the lead
               "t8c6": "pitch2",        # Digi: the high arp
               "t12c11": "pitch3",      # Autogun: the second line (Chorus 2)
               "t14c13": "pitch3",      # Generic saw bass: the DunDunDenDen's pulse (up with the pitches)
               "t9c7": "pitch4",        # Bright: held chords, their top line
               "t7c5": "chords",        # Wood: the chords
               "t15c14": "bass",        # Zombitronic: the bass line
               "t11c10": "off",         # Distorto: Bright an octave up
               "t16c15": "off"},        # Chip 3: a held tone under the last bars
              "A short base (0:49 at 127 BPM, C# minor): a one-bar intro, two Choruses, a DunDunDenDen on its "
              "pulsing saw and the last Chorus."),
        _midi("nanairo", "Sparta Nana-iro Base", "nanairo.mid", 130.0, "F#", True,
              [["intro", 4], ["chorus", 8], ["dundundenden", 4], ["chorus", 8], ["chorus", 4], ["madness", 4],
               ["chorus", 8], ["epicness", 8], ["chorus", 8], ["dundundenden", 4], ["chorus", 8], ["epicness", 8],
               ["chorus", 8], ["chorus", 4], ["ending", 1]],
              {"t6c4": "pitch1",        # Acoustic Bass 2: the arp under everything
               "t10c8": "pitch2",       # Pluck - Lulls_b: the 16th runs
               "t7c5": "pitch3",        # Texture 2: the breaks' line
               "t11c10": "pitch3",      # Pluck - Lulls #2: the melody near the start and the end
               "t8c6": "pitch4",        # Tesla Pipe: the gated chords of the first Epicness
               "t3c1": "chords",        # Pluck Pop: the chord stabs
               "t2c0": "bass",          # Bass 6
               "t4c2": "off",           # Pluck Tiny: the same chords held
               "t5c3": "off",           # Morphine: a six-note pad
               "t9c7": "off"},          # Pulse-Saw Bass: a sub under the bass
              "2:44 at 130 BPM in F# minor on one chord loop (F#m, E, C#m, D): the parts come from which "
              "instruments play — breaks without the chord plucks, an Epicness on the gated chords."),
        # The Sparta Extended base's layout bar for bar, its intro one bar short (a pickup): Chorus on the octave
        # bass, DunDunDenDen from the "E E F F" stops, the Madness on the 3-3-2 arps, the long Epicness on the bells.
        _midi("blend_s", "Sparta Blend S Base", "blend_s.mid", 140.0, "E", True,
              [["intro", 1], ["chorus", 4], ["dundundenden", 6], ["chorus", 4], ["epicness", 4], ["awesomeness", 4],
               ["chorus", 8], ["madness", 8], ["chorus", 8], ["epicness", 12], ["awesomeness", 4], ["chorus", 8],
               ["ending", 2]],
              {"t8c6": "pitch1",        # Pluck: the melody
               "t6c4": "pitch2",        # Chords: the off-beat stabs, their top line
               "t9c7": "pitch3",        # Guitar: the riffs (the first Epicness)
               "t12c11": "pitch3",      # Chip: the second Awesomeness
               "t10c8": "pitch4",       # Bells: the long Epicness
               "t4c2": {"role": "chords", "gain_db": -3.0},   # Pad: the held chords, under the rest
               "t2c0": "bass",          # Bass
               "t3c1": "off",           # the same bass again
               "t5c3": "off",           # Pluck: the Pad's chords
               "t7c5": "off",           # Pluck: 16th chords
               "t11c10": "off"},        # Filter seq
              "2:05 at 140 BPM in E (Em7, Fmaj7, Dm7), laid out like the Sparta Extended base after a one-bar "
              "pickup: the melody on the main pitch, guitar riffs, bells and a chip line on the others.",
              credit="enforch sr"),
        # The Sparta Extended base's layout bar for bar: the three intro hits, Chorus on the running bass, the
        # DunDunDenDen from its stops, a Madness on the Rhodes, the ending the intro again.
        _midi("decline_cte", "Sparta Decline CTE Base", "decline_cte.mid", 140.0, "C", True,
              [["intro", 2], ["chorus", 4], ["dundundenden", 6], ["chorus", 4], ["epicness", 4], ["awesomeness", 4],
               ["chorus", 8], ["madness", 8], ["chorus", 8], ["epicness", 12], ["awesomeness", 4], ["chorus", 8],
               ["ending", 3]],
              {"t9c7": "pitch1",        # Wop: the melody
               "t13c12": "pitch2",      # Kirby Super Star #2: the arps
               "t5c3": "pitch3",        # Diddy Kong Racing: the intro's line and the second melody
               "t2c0": "pitch4",        # Lead Rhodes: the Madness lead
               "t4c2": "pitch4",        # CTK-230: the first Awesomeness
               "t6c4": "pitch4",        # Layer #3: the DunDunDenDen's riff
               "t12c11": "chords",      # ColomboGMGS2: the chords
               "t15c14": "bass",        # Kirby Super Star: the bass line (C, G, F, C#)
               "t14c13": "off",         # TX81z Synthbass: power-chord stabs
               "t16c15": "off"},        # TX Alpha: a low pad
              "2:09 at 140 BPM in C minor, laid out like the Sparta Extended base: the melody on the main pitch, "
              "arps on the second, a Rhodes lead under the Madness.",
              credit="Citrus"),
    ]


# ── my templates ─────────────────────────────────────────────────────────────

SUFFIX = ".spartabase.json"


def user_dir() -> str:
    from .project import default_workspace
    return os.path.join(default_workspace(), "templates")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s[:40] or "base"


def user_templates(folder: Optional[str] = None) -> list[BaseTemplate]:
    folder = folder or user_dir()
    out = []
    if not os.path.isdir(folder):
        return out
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(SUFFIX):
            continue
        p = os.path.join(folder, fn)
        try:
            with open(p, "r", encoding="utf-8") as fh:
                t = BaseTemplate.from_dict(json.load(fh))
        except (OSError, ValueError, TypeError):
            continue
        t.user, t.path, t.group = True, p, "My templates"
        t.id = "my." + fn[:-len(SUFFIX)]
        out.append(t)
    return out


def all_templates(folder: Optional[str] = None) -> list[BaseTemplate]:
    return builtin_templates() + user_templates(folder)


def get_template(tid: str, folder: Optional[str] = None) -> BaseTemplate:
    for t in all_templates(folder):
        if t.id == tid:
            return t
    raise KeyError(f"no base template {tid!r}")


def validate(t: BaseTemplate) -> None:
    if not t.plan:
        raise ValueError("a template needs at least one part")
    kinds = MIDI_PLAN_KINDS if t.midi else PLAN_KINDS
    if t.midi and not os.path.isfile(t.midi_path()):
        raise ValueError(f"the MIDI file of {t.name!r} is missing: {t.midi_path()}")
    for k, b in t.plan:
        if k not in kinds:
            raise ValueError(f"unknown part {k!r} (parts: {', '.join(kinds)})")
        if int(b) <= 0 or int(b) > 64:
            raise ValueError(f"{k}: bars must be between 1 and 64")
    if not 40.0 <= float(t.bpm) <= 300.0:
        raise ValueError("tempo must be between 40 and 300 BPM")
    from .audio.pitch import pitch_class
    pitch_class(t.key)
    for opt, pid in t.options.items():
        if opt.endswith("_pattern") and isinstance(pid, str) and pid and not pid.startswith("text:"):
            lib.get(pid)


def save_user_template(t: BaseTemplate, folder: Optional[str] = None) -> BaseTemplate:
    """Write a template to the templates folder (overwrites one of the same name)."""
    validate(t)
    folder = folder or user_dir()
    os.makedirs(folder, exist_ok=True)
    slug = _slug(t.name)
    path = os.path.join(folder, slug + SUFFIX)
    d = t.to_dict()
    for k in ("user", "path", "bars", "duration"):
        d.pop(k, None)
    d["group"] = "My templates"
    d["id"] = slug
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1)
    os.replace(tmp, path)
    saved = BaseTemplate.from_dict(d)
    saved.user, saved.path, saved.id, saved.group = True, path, "my." + slug, "My templates"
    return saved


def import_template(path: str, folder: Optional[str] = None) -> BaseTemplate:
    """Add a shared ``.spartabase.json`` (or any template JSON) to my templates."""
    with open(path, "r", encoding="utf-8") as fh:
        t = BaseTemplate.from_dict(json.load(fh))
    return save_user_template(t, folder)


def delete_user_template(tid: str, folder: Optional[str] = None) -> None:
    t = get_template(tid, folder)
    if not t.user:
        raise ValueError("built-in templates cannot be deleted")
    os.remove(t.path)


def plan_kind(kind: str, name: str = "") -> str:
    """The plan kind of an arrangement section (for saving a structure as a template)."""
    if kind == "awesomeness":
        return "awesomeness2" if name.strip().endswith("2") else "awesomeness1"
    if kind == "chorus" and name.lower().startswith("final"):
        return "chorus_final"
    return kind if kind in PLAN_KINDS else "chorus"


def template_from_arrangement(arr, name: str, description: str = "", key: Optional[str] = None,
                              options: Optional[dict] = None) -> BaseTemplate:
    """A template with an arrangement's parts, tempo and key (``arr`` is an ``Arrangement``)."""
    plan = [[plan_kind(s.kind, s.name), int(s.bars)] for s in arr.sections]
    return BaseTemplate(id=_slug(name), name=name, bpm=float(arr.bpm), key=key or arr.key, plan=plan,
                        options=dict(options or {}), pitching=arr.pitching, polish=arr.polish,
                        progression="" if arr.progression.strip() == "0 1 -2 1" else arr.progression,
                        description=description or f"Saved from “{arr.title}”.", user=True)


def catalog(folder: Optional[str] = None) -> dict:
    """Templates grouped for pickers."""
    groups: dict[str, list] = {g: [] for g in GROUPS}
    for t in all_templates(folder):
        groups.setdefault(t.group, []).append(t.to_dict())
    return {"groups": [{"name": g, "templates": groups[g]} for g in groups if groups[g] or g == "My templates"],
            "plan_kinds": list(PLAN_KINDS)}
