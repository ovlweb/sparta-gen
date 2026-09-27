"""End-to-end: analyse a synthetic source, build samples, arrange, render audio + video."""

import json
import os

import numpy as np
import pytest

from spartagen import arrangement as AR
from spartagen import ffmpeg as ff
from spartagen.audio import dsp
from spartagen.audio.pitch import yin_track, hz_to_midi
from spartagen.project import Session


@pytest.fixture(scope="module")
def session(synthetic_source, tmp_path_factory):
    s = Session(workspace=str(tmp_path_factory.mktemp("ws")))
    s.set_source(synthetic_source)
    return s


def test_analysis_finds_every_kind(session):
    an = session.analysis()
    for kind in ("pitch", "kick", "snare", "hat", "quote", "word"):
        assert an.candidates[kind], kind
    # The held "vowels" (first 2.8 s) must be the pitch candidates.
    assert an.candidates["pitch"][0].start < 3.0


def test_bank_tunes_pitches_to_d(session):
    bank = session.bank()
    for sid in ("pitch1", "pitch2", "bass", "kick", "snare", "hat_closed", "quote1"):
        assert bank.get(sid) is not None, sid
    p1 = bank.get("pitch1")
    assert int(round(p1.root_midi)) % 12 == 2          # D
    # The pitches play chord lines together, so they share the main pitch's octave.
    assert {int(round(bank.get(k).root_midi)) for k in ("pitch1", "pitch2", "pitch3", "pitch4") if bank.get(k)} \
        == {int(round(p1.root_midi))}
    tr = yin_track(p1.audio, p1.sr, hop=256)
    got = hz_to_midi(float(np.median(tr.f0[tr.voiced])))
    assert abs(got - p1.root_midi) < 0.15
    # The bass pitch: an octave below the pitches (D3), heard above a base's own sub-bass — and it is there.
    bass = bank.get("bass")
    assert int(round(bass.root_midi)) == 50
    tr = yin_track(bass.audio, bass.sr, fmin=60, fmax=400, hop=256)
    got = hz_to_midi(float(np.median(tr.f0[tr.voiced])))
    assert abs(((got - 50) + 6) % 12 - 6) < 0.5


def test_every_variant_compiles(session):
    bank = session.bank()
    for v in AR.VARIANTS:
        arr = AR.build_arrangement(v)
        ev = AR.compile_events(arr, set(bank.samples))
        assert ev, v
        assert max(e.t for e in ev) < arr.duration
        assert all(e.max_len > 0 for e in ev)


def test_progression_twist_moves_semitone_patterns():
    avail = {"pitch1", "pitch2", "bass", "kick", "snare", "clap", "hat_closed", "hat_open", "crash", "quote1", "phrase",
             "word_a", "word_b"}
    a = AR.build_arrangement("unextended")
    b = AR.build_arrangement("unextended", progression="0 1 2 1")
    ev_a = [e for e in AR.compile_events(a, avail) if e.track_id == "bass" and e.section_kind == "chorus"]
    ev_b = [e for e in AR.compile_events(b, avail) if e.track_id == "bass" and e.section_kind == "chorus"]
    assert {e.semis for e in ev_a} == {0, 1, -2}
    assert {e.semis for e in ev_b} == {0, 1, 2}


def test_render_audio_and_video(session, tmp_path):
    # A short custom arrangement keeps the test fast: intro hits + one chorus + ending.
    opts = {"hard": True}
    arr = AR.Arrangement("Test Remix", "custom", sections=[
        AR.make_section("intro_hits", 1, opts), AR.make_section("chorus", 2, opts),
        AR.make_section("madness", 2, opts), AR.make_section("ending", 1, opts)])
    session.project.arrangement = arr.to_dict()
    session.project.video = {"width": 320, "height": 180, "fps": 20}
    res = session.render("preview")
    info = ff.probe(res["file"])
    assert info.has_video and info.has_audio
    assert abs(info.duration - res["duration"]) < 0.6
    assert -14.0 < res["lufs"] < -6.0 and res["peak_db"] <= -0.9
    mix, sr = dsp.read_wav(res["audio"])
    assert np.all(np.isfinite(mix)) and dsp.rms(mix) > 0.01


def test_sample_pack_export(session, tmp_path):
    res = session.export_pack(str(tmp_path / "pack"), video=True)
    names = {os.path.basename(f) for f in res["files"]}
    assert {"pitch1.wav", "pitch1.mp4", "kick.wav", "samples.json"} <= names
    meta = json.load(open(os.path.join(res["folder"], "samples.json")))
    assert meta["samples"]["pitch1"]["root_note"].startswith("D")


def test_project_roundtrip(session, tmp_path):
    path = session.project.save(str(tmp_path / "p.json"))
    from spartagen.project import Project
    p = Project.load(path)
    assert p.source_path == session.project.source_path
    assert p.analysis is not None


def test_session_on_a_base(session, tmp_path):
    from tests.test_base import make_base, SR
    base = tmp_path / "base.wav"
    dsp.write_wav(str(base), make_base(), SR)
    bm = session.set_base(str(base))
    assert session.project.variant == "base" and session.project.mix["base_mode"] == "remix"
    arr = session.arrangement()
    assert arr.total_bars == bm["bars"] and arr.variant == "base"
    bank = session.bank()
    assert {"chorus_a", "chorus_b"} <= set(bank.samples)
    ev = AR.compile_events(arr, set(bank.samples))
    assert ev and all(e.t >= 0 for e in ev)
    session.clear_base()
    assert session.project.variant != "base" and session.project.base is None


def test_chorus_parts_play_the_main_phrase_as_is(session):
    bank = session.bank()
    a, b = bank.get("chorus_a"), bank.get("chorus_b")
    ph = bank.get("phrase")
    assert a is not None and b is not None and ph is not None
    assert a.role == "chorus" and a.meta["plays"] == "as is"
    # The two parts are consecutive pieces of one clip — the main phrase, which the DunDunDenDen chops too.
    assert abs(a.src_end - b.src_start) < 1e-6 and a.src_start < b.src_start
    assert ph.src_start <= a.src_start + 0.05 and ph.src_end >= b.src_end - 0.05
    raw = session.audio()[int(a.src_start * a.sr):int(a.src_end * a.sr)]
    # "As is": the part is the source audio (level aside), not a re-pitched copy.
    n = min(raw.shape[0], a.audio.shape[0]) - 200
    r = np.corrcoef(raw[100:n], a.audio[100:n])[0, 1]
    assert r > 0.9


def test_the_epicness_third_word_is_another_moment_of_the_voice(session):
    bank = session.bank()
    a, b, c = bank.get("chorus_a"), bank.get("chorus_b"), bank.get("chorus_c")
    assert c is not None and c.role == "chorus" and c.meta["plays"] == "as is"
    # Not a piece of the main phrase: another word, clear of it.
    assert c.src_end + 0.3 <= a.src_start or c.src_start >= b.src_end + 0.3


def test_stale_stems_do_not_linger(session, tmp_path):
    from spartagen.render_audio import render_mix, MixConfig
    bank = session.bank()
    arr = AR.Arrangement("t", "custom", sections=[AR.SectionSpec("chorus", 1, [
        AR.TrackSpec("p", "pitch", "chorus.0_12", sample="pitch1")])])
    d = tmp_path / "stems"
    d.mkdir()
    (d / "chop.wav").write_bytes(b"old")          # a stem from an earlier render
    (d / "mine.wav").write_bytes(b"keep")         # not ours: left alone
    render_mix(arr, AR.compile_events(arr, set(bank.samples)), bank, MixConfig(tail_s=0.2), stems_dir=str(d))
    assert (d / "pitch.wav").is_file() and not (d / "chop.wav").exists() and (d / "mine.wav").exists()


def test_extra_percussion_comes_from_other_moments(session):
    bank = session.bank()
    def clear(a, b):
        return a.src_end + 0.5 <= b.src_start or a.src_start >= b.src_end + 0.5
    if bank.get("hat2") is not None:
        assert all(clear(bank.get("hat2"), bank.get(k)) for k in ("hat_closed", "hat_open") if bank.get(k))
    if bank.get("perc") is not None:
        assert all(clear(bank.get("perc"), bank.get(k)) for k in ("kick", "snare") if bank.get(k))
    print("hat2" in bank.samples, "perc" in bank.samples)
