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


def test_every_template_builds_and_compiles():
    ts = bases.all_templates()
    assert len({t.id for t in ts}) == len(ts)
    assert {"Standard bases", "Fast bases", "Wiki bases"} <= {t.group for t in ts}
    for t in ts:
        arr = build_arrangement(t.id)
        assert arr.bpm == t.bpm and arr.key == t.key, t.id
        assert arr.total_bars == t.bars, t.id
        assert compile_events(arr), t.id


def test_wiki_bases_play_their_own_patterns_in_their_key():
    arr = build_arrangement("nemesis")
    assert arr.key == "D#"
    assert {"chorus.nemesis", "dun.nemesis", "exec.nemesis", "awe.1_nemesis"} <= _patterns(arr)
    assert [s.kind for s in arr.sections].count("execution") == 1
    arr = build_arrangement("drlasp")
    assert arr.key == "C" and {"chorus.drlasp", "mad.drlasp", "perc.drlasp"} <= _patterns(arr)
    arr = build_arrangement("tungsten")
    assert arr.progression == "0 1 3 1 | -2" and "chords.tungsten" in _patterns(arr)
    # A standard base keeps the usual patterns.
    assert "chorus.nemesis" not in _patterns(build_arrangement("extended"))


def test_template_structure_replaces_the_detected_one_on_a_base():
    bm = B.analyze_base(make_base(), B.SR)                   # 19 bars
    tpl = bases.get_template("fast170")
    arr = build_from_base(bm, extra=tpl.options, plan=tpl.plan)
    kinds = [s.kind for s in arr.sections]
    assert kinds[:4] == ["intro", "chorus", "dundundenden", "chorus"]
    assert arr.total_bars == bm.bars                           # cut where the base ends
    assert arr.bpm == pytest.approx(bm.bpm)


def test_session_key_follows_templates_until_the_user_sets_one(tmp_path):
    s = Session(workspace=str(tmp_path / "w"))
    s.set_variant("nemesis")
    assert s.project.samples["key"] == "D#" and s.arrangement().key == "D#"
    s.set_key("E")
    s.set_variant("drlasp")
    assert s.project.samples["key"] == "E"                     # the user's key wins
    s.set_key("auto")
    s.set_variant("drlasp")
    assert s.project.samples["key"] == "C"


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
    s.set_base(path, template="drlasp")
    assert s.project.options["base_template"] == "drlasp"
    arr = s.arrangement()
    assert "mad.drlasp" in _patterns(arr) or "chorus.drlasp" in _patterns(arr)
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
