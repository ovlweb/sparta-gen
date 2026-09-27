"""Base templates: the bases a remix can be built on.

Sparta bases share their parts — the Chorus, the DunDunDenDen, the Epicness, the Awesomeness, the
Madness and the percussion under them work the same way on every base — and differ in tempo, key,
the order and length of their parts, and the pitch patterns written for them.  A template holds
exactly that:

* **Standard bases** — keatonkeaton999's bases (Unextended, Extended …) and the classic variations.
* **Fast bases** — the same parts at 150, 160 or 170 BPM (about a quarter of all bases are faster
  than 140 BPM, Sparta Remix Wiki).
* **Wiki bases** — bases the Sparta Remix Wiki documents patterns for: their key and their own
  Chorus, DunDunDenDen, Execution, Madness, Awesomeness, percussion or progression.  Their layout is
  the extended-type one, and their tempo is 140 BPM until the base's audio (or MIDI) says otherwise.
* **My templates** — saved by the user (any base, public or not) as ``*.spartabase.json`` files
  that can be shared.

A template drives the remix without a base file, guides the base analyzer when the base's audio is
loaded (its tempo is the analyzer's first guess, its patterns go on the detected parts) and can
replace the detected structure altogether.
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

GROUPS = ("Standard bases", "Fast bases", "Wiki bases", "My templates")


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

    @property
    def bars(self) -> int:
        return sum(int(b) for _k, b in self.plan)

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

#: The extended-type layout (at least a minute and a half, with an Epicness, Sparta Remix Wiki):
#: two Epicness parts, Awesomeness 1 before the Madness and Awesomeness 2 opening the final Chorus.
EXTENDED_TYPE = [["intro", 4], ["intro_hits", 1], ["chorus", 8], ["dundundenden", 4], ["chorus", 8],
                 ["epicness", 8], ["awesomeness1", 4], ["madness", 8], ["chorus", 8], ["epicness", 8],
                 ["awesomeness2", 4], ["chorus_final", 8], ["ending", 2]]


def _with_execution(plan: list, bars: int = 4) -> list:
    """The layout with an Execution part after the DunDunDenDen (move it to where your base has it)."""
    out = []
    for k, b in plan:
        out.append([k, b])
        if k == "dundundenden":
            out.append(["execution", bars])
    return out


def _std(vid: str, name: str, group: str = "Standard bases", **kw) -> BaseTemplate:
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
    return BaseTemplate(id=vid, name=name, group=group, bpm=float(v["bpm"]), minor=bool(v.get("minor", False)),
                        plan=plan, options=opts, pitching=v["pitching"], polish=v["polish"],
                        description=v["description"], **kw)


def _wiki(tid: str, name: str, patterns: dict, key: str = "D", minor: bool = False, execution: bool = False,
          progression: str = "", note: str = "") -> BaseTemplate:
    plan = _with_execution(EXTENDED_TYPE) if execution else [list(p) for p in EXTENDED_TYPE]
    parts = []
    for opt, label in (("chorus_pitch_pattern", "Chorus"), ("dun_pitch_pattern", "DunDunDenDen"),
                       ("execution_pattern", "Execution"), ("madness_pattern", "Madness"),
                       ("awesomeness1_pattern", "Awesomeness 1"), ("awesomeness2_pattern", "Awesomeness 2"),
                       ("perc_pattern", "percussion"), ("chords_pattern", "chords"), ("intro_pattern", "Intro")):
        if opt in patterns:
            parts.append(f"{label}: {lib.get(patterns[opt]).name}")
    if progression:
        parts.append("progression " + progression)
    desc = (f"Patterns the Sparta Remix Wiki gives for this base ({'; '.join(parts)}), in {key}"
            f"{' minor' if minor else ''}.  Extended-type layout{' with an Execution after the DunDunDenDen' if execution else ''}; "
            "140 BPM unless your base file says otherwise.")
    if note:
        desc += " " + note
    return BaseTemplate(id=tid, name=name, group="Wiki bases", bpm=140.0, key=key, minor=minor, plan=plan,
                        options=dict(patterns, wiki_perc=True), progression=progression, description=desc,
                        credit="Sparta Remix Wiki (Pitch Patterns, Awesomeness, Madness, Percussion)",
                        bpm_known=False)


def _prog(pid: str) -> str:
    return lib.get(pid).text


def builtin_templates() -> list[BaseTemplate]:
    out = [
        _std("unextended", "Unextended (the original base)"),
        _std("extended", "Extended (2:08)"),
        _std("semi_extended", "Semi-Extended"),
        _std("minor", "Extended in minor"),
        _std("classic", "2010 style (Unextended, sampler pitches)"),
        _std("hyper", "Hyper / Vertex (160 BPM)", group="Fast bases"),
        BaseTemplate("fast150", "Fast base (150 BPM)", "Fast bases", 150.0, plan=[list(p) for p in EXTENDED_TYPE],
                     options={"wiki_perc": True}, pitching="hard", polish="normal",
                     description="The extended-type layout at 150 BPM."),
        BaseTemplate("fast170", "High-speed base (170 BPM)", "Fast bases", 170.0,
                     plan=[["intro", 4], ["intro_hits", 1], ["chorus", 8], ["dundundenden", 4], ["chorus", 8],
                           ["epicness", 8], ["madness", 8], ["chorus_final", 8], ["ending", 2]],
                     options={"wiki_perc": True, "perc_pattern": "perc.vitro"}, pitching="hard", polish="hard",
                     description="A short layout with an Epicness at 170 BPM, hard pitches and FX."),
        _wiki("nemesis", "Nemesis / Nemesis X",
              {"chorus_pitch_pattern": "chorus.nemesis", "dun_pitch_pattern": "dun.nemesis",
               "execution_pattern": "exec.nemesis", "awesomeness1_pattern": "awe.1_nemesis"},
              key="D#", execution=True),
        _wiki("kaosz", "Kaosz", {"dun_pitch_pattern": "dun.kaosz", "execution_pattern": "exec.kaosz"},
              key="D#", execution=True),
        _wiki("pulse", "Pulse", {"execution_pattern": "exec.pulse", "perc_pattern": "perc.pulse_v7"},
              execution=True, note="Its freestyle and 32nd-note pitches made them popular (2015)."),
        _wiki("latin", "Latin", {"chorus_pitch_pattern": "chorus.latin", "execution_pattern": "exec.latin"},
              execution=True),
        _wiki("drlasp", "DrLaSp / DrLaSp X", {"chorus_pitch_pattern": "chorus.drlasp", "madness_pattern": "mad.drlasp",
                                              "perc_pattern": "perc.drlasp"}, key="C"),
        _wiki("interpolation", "Interpolation", {"intro_pattern": "intro.interpolation",
                                                 "chorus_pitch_pattern": "chorus.interpolation"}, key="A"),
        _wiki("filthy", "Filthy", {"execution_pattern": "exec.filthy", "perc_pattern": "perc.filthy"}, key="A",
              execution=True),
        _wiki("madhouse", "Madhouse", {"dun_pitch_pattern": "dun.madhouse_xye", "execution_pattern": "exec.madhouse_otm"},
              execution=True),
        _wiki("fap", "FAP", {"execution_pattern": "exec.fap"}, execution=True),
        _wiki("tose_v7", "TOSE V7", {"execution_pattern": "exec.tose_v7"}, execution=True),
        _wiki("tungsten", "Tungsten", {"chords_pattern": "chords.tungsten", "awesomeness1_pattern": "awe.tungsten_1",
                                       "awesomeness2_pattern": "awe.tungsten_2"}, progression=_prog("prog.useful")),
        _wiki("elasticity", "Elasticity", {}, progression=_prog("prog.elasticity")),
        _wiki("lost", "Lost base", {"awesomeness1_pattern": "awe.lost_base_1", "awesomeness2_pattern": "awe.lost_base_2"}),
        _wiki("tgohs", "TGOHS Edition", {"awesomeness1_pattern": "awe.tgohs_1", "awesomeness2_pattern": "awe.tgohs_2"}),
        _wiki("upsilon", "Upsilon", {"awesomeness1_pattern": "awe.upsilon_1", "awesomeness2_pattern": "awe.upsilon_2"},
              minor=True),
        _wiki("celeste", "Celeste", {"awesomeness1_pattern": "awe.celeste_1", "awesomeness2_pattern": "awe.celeste_2"}),
        _wiki("valise", "Valise", {"awesomeness1_pattern": "awe.valise_1"}),
        _wiki("radical_je", "Radical JE", {"awesomeness1_pattern": "awe.radical_je"}, key="C#"),
    ]
    return out


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
    for k, b in t.plan:
        if k not in PLAN_KINDS:
            raise ValueError(f"unknown part {k!r} (parts: {', '.join(PLAN_KINDS)})")
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
