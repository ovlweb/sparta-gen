"""Several videos in one project: each sample cut from the video the user picks for it."""

import os

import numpy as np
import pytest

from conftest import SR, harmonic_tone, noise_burst
from spartagen.project import Project, Session
from spartagen.render_video import ClipCache
from spartagen.samples import SOURCE_SLOTS


def _second_video(folder, name="other.mp4", video=True) -> str:
    """Another test video: other notes (higher), other hits — its samples must not be the first one's."""
    from spartagen import ffmpeg as ff
    from spartagen.audio import dsp
    rest = np.zeros(int(0.3 * SR), dtype=np.float32)
    parts = []
    for f in (311.1, 349.2, 392.0):
        parts += [harmonic_tone(f, 0.5, vibrato_cents=10.0, formant=900.0), rest]
    for i in range(6):
        parts += [harmonic_tone(180.0 + 10 * i, 0.2, formant=600 + 80 * i), np.zeros(int(0.05 * SR), np.float32)]
    for i in range(3):
        parts += [noise_burst(0.25, decay_ms=60, seed=40 + i, lowpass=150.0) * 3.0, rest]
        parts += [noise_burst(0.2, decay_ms=70, seed=50 + i), rest]
    audio = np.concatenate(parts)
    wav = os.path.join(folder, os.path.splitext(name)[0] + ".wav")
    dsp.write_wav(wav, audio, SR)
    if not video:
        return wav
    out = os.path.join(folder, name)
    ff.make_test_card(out, len(audio) / SR, wav, size="320x180", fps=25)
    return out


@pytest.fixture(scope="module")
def two(synthetic_source, tmp_path_factory):
    d = tmp_path_factory.mktemp("two")
    s = Session(workspace=str(d / "ws"))
    s.set_source(synthetic_source)
    other = _second_video(str(d))
    return s, other, str(d)


def test_videos_are_added_once_and_named(two, tmp_path):
    s, other, d = two
    v = s.add_source(other)
    assert v["id"] == "v2" and [x["id"] for x in s.source_list()] == ["main", "v2"]
    with pytest.raises(ValueError, match="already"):
        s.add_source(other)
    with pytest.raises(ValueError, match="already"):
        s.add_source(s.project.source_path)
    with pytest.raises(KeyError):
        s.set_sample_source("pitch2", "v9")
    with pytest.raises(ValueError):
        s.set_sample_source("drums", "v2")
    # Saved with the project, and read back.
    path = s.project.save(str(tmp_path / "p.json"))
    assert [x["id"] for x in Session(Project.load(path)).source_list()] == ["main", "v2"]


def test_each_pick_comes_from_its_own_video(two):
    s, other, d = two
    if not any(x["id"] == "v2" for x in s.source_list()):
        s.add_source(other)
    main_bank = s.bank()
    assert all(smp.source == "" for smp in main_bank.samples.values())
    s.set_sample_source("pitch2", "v2")
    s.set_sample_source("snare", "v2")
    b = s.bank()
    p2, p1 = b.samples["pitch2"], b.samples["pitch1"]
    assert p2.source == other and p2.source_id == "v2" and p2.to_dict()["source"] == "v2"
    assert p1.source == "" and p1.to_dict()["source"] == "main"
    assert int(round(p2.root_midi)) // 12 == int(round(p1.root_midi)) // 12      # one octave for every pitch
    other_len = s.analysis(sid="v2").duration
    assert 0 <= p2.src_start < p2.src_end <= other_len + 1e-6
    assert b.samples["snare"].source == other and b.samples["clap"].source == other   # the clap goes with the snare
    assert b.samples["kick"].source == ""
    # The Chorus from the other video takes its main phrase, chops and third word along; the response follows its call.
    s.set_sample_source("chorus", "v2")
    s.set_sample_source("word_a", "v2")
    b = s.bank()
    frm = s.sample_sources()
    assert frm["chorus"] == frm["phrase"] == frm["chorus_c"] == "v2" and frm["word_b"] == "v2"
    for sid in ("chorus_a", "chorus_b", "phrase", "word_a"):
        assert b.samples[sid].source_id == "v2", sid
    assert all(x.source_id == "v2" for x in b.samples.values() if x.role == "syllable")
    s.set_sample_source("phrase", "main")                     # its own choice wins over following
    b = s.bank()
    assert b.samples["phrase"].source_id == "" and b.samples["chorus_a"].source_id == "v2"
    assert all(x.source_id == "" for x in b.samples.values() if x.role == "syllable")


def test_a_pick_in_another_video_uses_that_video_s_candidates(two):
    s, other, d = two
    if not any(x["id"] == "v2" for x in s.source_list()):
        s.add_source(other)
    s.set_sample_source("pitch3", "v2")
    s.project.samples.setdefault("selections", {})["pitch3"] = {"start": 0.05, "end": 0.45}
    b = s.bank()
    assert b.samples["pitch3"].source_id == "v2" and b.samples["pitch3"].src_start < 0.5
    s.set_sample_source("pitch3", "main")                     # moved back: the pick in v2 means nothing here
    assert "pitch3" not in s.project.samples["selections"]


def test_clips_and_cards_come_from_each_sample_s_video(two):
    s, other, d = two
    if not any(x["id"] == "v2" for x in s.source_list()):
        s.add_source(other)
    s.set_sample_source("pitch2", "v2")
    b = s.bank()
    cache = ClipCache(s.project.source_path, b, 25.0, 64, True)
    fr = cache.frame("pitch2", 64, 36, 0.0)
    assert fr is not None and fr.shape == (36, 64, 3)
    # An audio-only video: its samples show as cards.
    wav = _second_video(d, "voice.wav", video=False)
    v3 = s.add_source(wav)
    s.set_sample_source("pitch4", v3["id"])
    b = s.bank()
    assert b.samples["pitch4"].source == wav
    card = ClipCache(s.project.source_path, b, 25.0, 64, True)._load("pitch4", 64, 36, 0)
    assert card.shape == (1, 36, 64, 3)
    assert s.still(0.5, 160, 90).shape == (90, 160, 3)        # the picture draws with clips of three videos


def test_taking_a_video_out_cuts_its_samples_from_the_main_one_again(two):
    s, other, d = two
    if not any(x["id"] == "v2" for x in s.source_list()):
        s.add_source(other)
    s.set_sample_source("kick", "v2")
    s.project.samples.setdefault("selections", {})["kick"] = 0
    assert s.bank().samples["kick"].source_id == "v2"
    s.remove_source("v2")
    assert "v2" not in [x["id"] for x in s.source_list()] and "kick" not in s.project.samples["selections"]
    assert all(v != "v2" for v in (s.project.samples.get("from") or {}).values())
    assert s.bank().samples["kick"].source_id == ""
    assert set(s.sample_sources()) == set(SOURCE_SLOTS)
