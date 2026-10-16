"""Short clips, and clips with music all through them, still make a remix (issue 6)."""

import numpy as np
import pytest

from spartagen import arrangement as AR
from spartagen import ffmpeg as ff
from spartagen.audio import dsp
from spartagen.audio.analysis import FALLBACK_GROUPS, analyze
from spartagen.project import Session

from tests.conftest import SR, noise_burst


def music(dur: float, seed: int = 0) -> np.ndarray:
    """A chord held all through, over a little hiss: no clean vowel, word or hit anywhere."""
    t = np.arange(int(dur * SR)) / SR
    x = sum(0.2 * np.sin(2 * np.pi * f * t) for f in (110.0, 220.0, 277.2, 329.6))
    return (x + 0.02 * np.random.RandomState(seed).randn(t.size)).astype(np.float32)


def video(tmp_path, name: str, x: np.ndarray) -> str:
    if not ff.available():
        pytest.skip("ffmpeg not available")
    wav, mp4 = str(tmp_path / f"{name}.wav"), str(tmp_path / f"{name}.mp4")
    dsp.write_wav(wav, x, SR)
    ff.make_test_card(mp4, len(x) / SR, wav, size="160x90", fps=25)
    return mp4


def short_remix() -> dict:
    opts = {"hard": True}
    return AR.Arrangement("Short", "custom", sections=[
        AR.make_section("intro_hits", 1, opts), AR.make_section("chorus", 2, opts),
        AR.make_section("ending", 1, opts)]).to_dict()


def test_music_all_through_gets_cuts_of_its_own():
    an = analyze(music(6.0), SR)
    for kind in ("pitch", "word", "quote", "kick", "snare", "hit", "hat", "crash"):
        assert an.candidates[kind], kind
        assert all(c.info.get("fallback") for c in an.candidates[kind]), kind
    for kind, cands in an.candidates.items():
        spans = sorted((c.start, c.end) for c in cands)
        assert all(0.0 <= a < b <= 6.05 for a, b in spans), kind
        assert all(s1[1] <= s2[0] + 1e-6 for s1, s2 in zip(spans, spans[1:])), kind      # none overlap
    assert len(an.candidates["pitch"]) >= 2 and len(an.candidates["word"]) >= 2
    assert an.fallbacks and an.to_dict()["fallbacks"] is True


def test_clips_with_their_own_cuts_get_none_added(synthetic_source, tmp_path):
    s = Session(workspace=str(tmp_path / "ws"))
    s.set_source(synthetic_source)
    an = s.analysis()
    assert not any(c.info.get("fallback") for cands in an.candidates.values() for c in cands)


def test_a_six_second_clip_of_music_makes_a_remix(tmp_path):
    s = Session(workspace=str(tmp_path / "ws"))
    s.set_source(video(tmp_path, "music", music(6.0)))
    bank = s.bank()
    assert {"pitch1", "bass", "kick", "snare", "hat_closed", "quote1", "chorus_a"} <= set(bank.samples)
    s.project.arrangement = short_remix()
    res = s.render("audio")
    assert res["events"] > 0
    mix, _ = dsp.read_wav(res["audio"])
    assert np.all(np.isfinite(mix)) and dsp.rms(mix) > 0.01


def test_an_rc3_analysis_with_nothing_to_cut_is_made_again(tmp_path):
    s = Session(workspace=str(tmp_path / "ws"))
    s.set_source(video(tmp_path, "music", music(4.0, seed=1)))
    made = s.analysis().to_dict()
    # Saved by 1.0.0 RC 3: no cuts at all, and no word of fallbacks.
    old = {k: v for k, v in made.items() if k != "fallbacks"}
    s.project.analysis = {**old, "candidates": {k: [] for k in made["candidates"]}}
    s._analysis = None
    an = s.analysis()
    assert an.fallbacks and an.candidates["pitch"] and s.project.analysis["fallbacks"] is True
    # One saved with its cuts is used as it was.
    s.project.analysis, s._analysis = old, None
    assert s.analysis().fallbacks is False


def test_only_an_empty_group_gets_cuts_added():
    # Clicks between silences: hits enough, but no voice — the hits stay as found, the voice gets cuts.
    gap = np.zeros(int(0.45 * SR), np.float32)
    beat = np.concatenate([part for i in range(8) for part in (noise_burst(0.05, decay_ms=10.0, seed=i), gap)])
    an = analyze(beat, SR)
    drums = [c for kind in FALLBACK_GROUPS[1] for c in an.candidates.get(kind, [])]
    assert drums and not any(c.info.get("fallback") for c in drums)
    assert an.candidates["pitch"] and all(c.info.get("fallback") for c in an.candidates["pitch"])


def test_a_silent_clip_says_so(tmp_path):
    s = Session(workspace=str(tmp_path / "ws"))
    s.set_source(video(tmp_path, "silence", np.zeros(3 * SR, np.float32)))
    s.project.arrangement = short_remix()
    with pytest.raises(ValueError, match="silent"):
        s.render("audio")
