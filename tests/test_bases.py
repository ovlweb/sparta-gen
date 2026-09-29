"""Base templates: built-in and user templates, their patterns and keys, and templates on base files."""

import json
import os

import pytest

from spartagen import bases
from spartagen.arrangement import build_arrangement, build_from_base, compile_events
from spartagen.audio import base as B
from spartagen.audio import dsp
from spartagen.project import Session

from test_base import make_base


def _patterns(arr) -> set:
    return {t.pattern for s in arr.sections for t in s.tracks}


def test_every_template_builds_and_compiles(tmp_path):
    """The bases that come with SpartaGen: the Sparta Remix's own and the four MIDI bases (no copies of it)."""
    ts = bases.all_templates()
    assert len({t.id for t in ts}) == len(ts)
    assert [t.id for t in bases.builtin_templates()] == ["extended", "stroll", "nanairo", "blend_s", "decline_cte"]
    assert {t.group for t in ts} == {"Bases"}
    s = Session(workspace=str(tmp_path / "w"))
    for t in ts:
        bases.validate(t)
        arr = s.set_variant(t.id)
        assert arr.key == t.key and arr.bpm == pytest.approx(t.bpm, abs=0.01), t.id
        assert arr.total_bars == t.bars, t.id
        assert compile_events(arr), t.id


def test_a_midi_base_template_plays_its_notes_with_its_roles_and_parts(tmp_path):
    s = Session(workspace=str(tmp_path / "w"))
    arr = s.set_variant("decline_cte")
    m = s.project.midi
    assert s.project.variant == "midi" and m["template"] == "decline_cte"
    assert m["path"].startswith(str(tmp_path))                     # its MIDI, copied into the project
    roles = {pid: r["role"] for pid, r in m["mapping"].items()}
    assert roles["t15c14"] == "bass" and roles["t9c7"] == "pitch1" and roles["t12c11"] == "chords"
    assert roles["t14c13"] == "off"                                # the power-chord stabs stay out
    assert [x.kind for x in arr.sections][:3] == ["intro", "chorus", "dundundenden"]
    assert arr.key == "C" and s.project.samples["key"] == "C"      # not the key the notes alone suggest
    ev = compile_events(arr)
    assert any(e.sample == "bass" for e in ev) and any(e.stem == "chorus" for e in ev)
    assert sum(1 for e in ev if e.stem == "quotes" and e.t < 2 * 240.0 / arr.bpm) == 3   # a quote on each intro hit
    from spartagen.patterns import library as lib
    assert lib.get("chorus.nemesis").text                         # the wiki's patterns stay, to pick for a track


@pytest.mark.parametrize("tid", ["blend_s", "decline_cte"])
def test_blend_s_and_decline_cte_follow_their_parts(tmp_path, tid):
    """Both bases are laid out the Extended way — an Awesomeness before their first Epicness (Blend S after a
    one-bar pickup, Decline CTE with a bar more of ending) — so the main phrase, the Madness words and the drums
    come in where their parts do."""
    layout = [("chorus", 4), ("dundundenden", 6), ("chorus", 4), ("awesomeness", 4), ("epicness", 4), ("chorus", 8),
              ("madness", 8), ("chorus", 8), ("epicness", 12), ("awesomeness", 4), ("chorus", 8)]
    arr = Session(workspace=str(tmp_path / "w")).set_variant(tid)
    assert [(x.kind, x.bars) for x in arr.sections][1:-1] == layout
    awe = [x for x in arr.sections if x.kind == "awesomeness"]
    assert [x.name for x in awe] == ["Awesomeness 1", "Awesomeness 2"]
    assert all(any(t.stem == "chorus" for t in x.tracks) and any(t.id == "crash_auto" for t in x.tracks)
               for x in awe)


def test_parts_stay_near_their_samples_note_and_the_bass_in_its_register(tmp_path):
    """A part spread over three octaves (Decline's Layer #3) is not shifted +24 semitones at one end: every note
    stays within 15 of its sample's own (one further is played an octave nearer).  The bass keeps its register:
    its octave bounces go below the bass sample's note, never an octave up to a pitch's."""
    s = Session(workspace=str(tmp_path / "w"))
    ev = compile_events(s.set_variant("decline_cte"))
    assert max(abs(e.semis) for e in ev if e.pitched and e.sample != "bass") <= 15
    bass = [e.semis for e in compile_events(s.set_variant("nanairo")) if e.sample == "bass"]
    assert min(bass) <= -12 and max(bass) <= 0


def test_template_structure_replaces_the_detected_one_on_a_base():
    bm = B.analyze_base(make_base(), B.SR)                   # 19 bars
    tpl = bases.get_template("extended")
    arr = build_from_base(bm, extra=tpl.options, plan=tpl.plan)
    kinds = [s.kind for s in arr.sections]
    assert kinds[:4] == ["intro", "chorus", "dundundenden", "chorus"]
    assert arr.total_bars == bm.bars                           # cut where the base ends
    assert arr.bpm == pytest.approx(bm.bpm)


def test_session_key_follows_templates_until_the_user_sets_one(tmp_path):
    s = Session(workspace=str(tmp_path / "w"))
    s.set_variant("stroll")
    assert s.project.samples["key"] == "C#" and s.arrangement().key == "C#"
    s.set_key("E")
    s.set_variant("decline_cte")
    assert s.project.samples["key"] == "E"                     # the user's key wins
    s.set_key("auto")
    s.set_variant("decline_cte")
    assert s.project.samples["key"] == "C"
    s.set_variant("extended")
    assert s.project.samples["key"] == "D" and s.arrangement().key == "D"


def test_a_base_file_in_d_sharp_retunes_the_pitches(tmp_path):
    path = str(tmp_path / "base_d_sharp.wav")
    dsp.write_wav(path, make_base(root_midi=63), B.SR)
    s = Session(workspace=str(tmp_path / "w"))
    s.set_base(path, template="")
    assert s.project.base["key_pc"] == 3
    assert s.project.samples["key"] == "D#"
    assert s.arrangement().key == "D#"


def test_a_template_guides_a_base_file(tmp_path):
    path = str(tmp_path / "base.wav")
    dsp.write_wav(path, make_base(), B.SR)
    s = Session(workspace=str(tmp_path / "w"))
    s.set_base(path, template="extended")
    assert s.project.options["base_template"] == "extended"
    assert s.arrangement().bpm == pytest.approx(140.0, abs=1.0)
    s.project.options["base_structure"] = "template"
    s.project.arrangement = None
    arr = s.arrangement()
    assert [x.kind for x in arr.sections][:2] == ["intro", "chorus"]


def test_my_templates_save_share_import_and_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARTAGEN_HOME", str(tmp_path / "home"))
    arr = build_arrangement("unextended", bpm=150)
    t = bases.template_from_arrangement(arr, "My Secret Base", options={"perc_pattern": "perc.vitro"})
    saved = bases.save_user_template(t)
    assert saved.id == "my.my_secret_base" and os.path.isfile(saved.path)
    got = bases.get_template("my.my_secret_base")
    assert got.bpm == 150 and got.group == "My templates" and got.plan == [list(p) for p in t.plan]
    built = build_arrangement("my.my_secret_base")
    assert built.bpm == 150 and "perc.vitro" in _patterns(build_arrangement("my.my_secret_base"))
    # Shared as a file, imported by someone else.
    shared = tmp_path / "friend.spartabase.json"
    d = json.load(open(saved.path))
    d["name"] = "Friend's Base"
    shared.write_text(json.dumps(d))
    imp = bases.import_template(str(shared))
    assert imp.id == "my.friend_s_base"
    assert {x.id for x in bases.user_templates()} == {"my.my_secret_base", "my.friend_s_base"}
    bases.delete_user_template("my.friend_s_base")
    assert [x.id for x in bases.user_templates()] == ["my.my_secret_base"]
    with pytest.raises(ValueError):
        bases.delete_user_template("extended")
    assert any(g["name"] == "My templates" and g["templates"] for g in bases.catalog()["groups"])


@pytest.mark.parametrize("change, msg", [
    ({"plan": [["dance", 4]]}, "unknown part"),
    ({"plan": [["chorus", 0]]}, "bars"),
    ({"bpm": 500}, "tempo"),
    ({"key": "H"}, "note"),
    ({"options": {"chorus_pitch_pattern": "chorus.nope"}}, "chorus.nope"),
])
def test_bad_templates_are_refused(change, msg, tmp_path):
    t = bases.BaseTemplate.from_dict(dict({"id": "x", "name": "X", "plan": [["chorus", 8]]}, **change))
    with pytest.raises((ValueError, KeyError), match=msg):
        bases.save_user_template(t, str(tmp_path))


def test_a_loaded_base_file_plays_only_under_a_remix_built_on_it(tmp_path):
    """Picking a template with a base file loaded must not play that base under another structure/tempo."""
    from spartagen.project import Session
    s = Session(workspace=str(tmp_path / "ws"))
    s.project.mix["base_path"] = str(tmp_path / "base.mp3")
    s.project.variant = "extended"
    assert "base_path" not in s.mix_settings()               # a template: the base waits, silent
    s.project.variant = "base"
    assert s.mix_settings()["base_path"].endswith("base.mp3")   # built on the base: it plays
    s.project.variant = "midi"
    assert "base_path" in s.mix_settings()                   # a MIDI base's backing audio
    assert s.project.mix["base_path"]                        # never forgotten, only silent
