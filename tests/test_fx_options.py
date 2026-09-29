"""Sound FX options: presets, amounts chosen by hand, and what they do to the mix."""

import numpy as np
import pytest

from spartagen import render_audio as RA
from spartagen.arrangement import Arrangement, SectionSpec
from spartagen.audio import dsp

SR = 44100


def test_presets_set_amounts_and_hand_picked_ones_win():
    c = RA.MixConfig.from_dict({})
    assert c.fx_preset == "xleth" and c.reverb == 1.0 and c.lofi == 0.0 and not c.risers
    c = RA.MixConfig.from_dict({"fx_preset": "lofi"})
    assert c.lofi == 0.6 and c.tape_stop_end and c.width == 0.8
    c = RA.MixConfig.from_dict({"fx_preset": "lofi", "lofi": 0.1, "reverb": 9.0})
    assert c.lofi == 0.1 and c.reverb == 2.5                             # clamped to its range
    assert set(RA.FX_PRESETS) == set(RA.FX_PRESET_NAMES)
    with pytest.raises(ValueError, match="FX preset"):
        RA.MixConfig.from_dict({"fx_preset": "dubstep"})


def test_drive_and_ott_scale_the_stem_chains():
    chain = RA.stem_chain("pitch", "hard", SR)
    none = RA.scaled_chain(chain, RA.MixConfig.from_dict({"drive": 0.0, "ott": 0.0}))
    assert not any(s["fx"] in ("saturate", "ott") for s in none)
    more = RA.scaled_chain(chain, RA.MixConfig.from_dict({"drive": 2.0, "ott": 2.0}))
    sat = {s["fx"]: s for s in chain}["saturate"]
    assert {s["fx"]: s for s in more}["saturate"]["drive_db"] == pytest.approx(2 * sat["drive_db"])
    assert {s["fx"]: s for s in more}["ott"]["depth"] == pytest.approx(0.7)


def _music(seconds: float = 2.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    x = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.2 * np.sin(2 * np.pi * 3300 * t + 1.0)
    return np.stack([x, np.roll(x, 200)], axis=1).astype(np.float32)


def test_lofi_and_width_change_the_master():
    x = _music()
    clean = RA.master(x, SR, "normal", cfg=RA.MixConfig.from_dict({}))
    lofi = RA.master(x, SR, "normal", cfg=RA.MixConfig.from_dict({"lofi": 1.0}))
    assert np.abs(clean - lofi).mean() > 0.01
    wide = RA.master(x, SR, "normal", cfg=RA.MixConfig.from_dict({"width": 1.8}))
    side = lambda y: np.abs(y[:, 0] - y[:, 1]).mean() / max(np.abs(y).mean(), 1e-9)   # noqa: E731
    assert side(wide) > side(clean)


def test_risers_and_stutter_fills_land_before_the_parts():
    arr = Arrangement("t", "custom", bpm=120.0, sections=[SectionSpec("intro", 1, []), SectionSpec("madness", 1, []),
                                                           SectionSpec("chorus", 1, [])])
    bar = int(arr.bar_s * SR)
    t = np.arange(3 * bar) / SR
    low = (0.5 * np.sin(2 * np.pi * 70 * t)).astype(np.float32)
    mix = np.stack([low, low], axis=1)
    before = mix.copy()
    RA.transitions(mix, SR, arr, arr.section_starts(), risers=True)
    chorus = 2 * bar
    assert np.abs(mix[chorus - bar // 4:chorus]).mean() < 0.3 * np.abs(before[chorus - bar // 4:chorus]).mean()
    assert np.array_equal(mix[:bar], before[:bar])                       # no riser before the Madness
    ramp = np.linspace(0, 1, 3 * bar, dtype=np.float32)
    mix = np.stack([ramp, ramp], axis=1)
    RA.transitions(mix, SR, arr, arr.section_starts(), stutters=True)
    beat, step = bar // 4, int(arr.step_s * SR)
    a = 2 * bar - beat                                                    # the madness's last beat stutters
    assert mix[a + step + 10, 0] == pytest.approx(mix[a + 10, 0] * 0.9, rel=1e-3)
    assert mix[bar - 1, 0] == pytest.approx(ramp[bar - 1])               # not after the intro


def test_presets_render_differently(tmp_path, synthetic_source):
    from spartagen.project import Session
    s = Session(workspace=str(tmp_path / "w"))
    s.set_source(synthetic_source)
    s.set_variant("unextended")
    s.project.mix = {"fx_preset": "clean"}
    clean = s.render("audio")
    s.project.mix = {"fx_preset": "lofi", "risers": True, "stutter_fills": True}
    lofi = s.render("audio")
    assert clean["duration"] == pytest.approx(lofi["duration"], abs=0.05)
    assert abs(clean["lufs"] - lofi["lufs"]) < 3.0                      # both brought to loudness
    from spartagen import ffmpeg as ff
    x = ff.decode_audio(clean["file"], sr=SR, mono=True)
    y = ff.decode_audio(lofi["file"], sr=SR, mono=True)
    n = min(x.size, y.size)
    assert np.abs(x[:n] - y[:n]).mean() > 0.005


def test_volume_faders_move_their_stems_and_can_switch_a_part_off():
    from spartagen.render_audio import VOLUME_GROUPS, MixConfig, muted_stems
    c = MixConfig.from_dict({"volumes": {"pitches": -40, "bass": 5, "nonsense": 3, "drums": None},
                             "mute_groups": ["quotes", "nope"]})
    assert c.volumes == {"pitches": -24.0, "bass": 5.0}                     # clamped, unknown ones dropped
    assert c.stem_db("pitch") == c.stem_db("pitch_soft") == -24.0 and c.stem_db("bass") == 5.0
    assert c.stem_db("drums") == 0.0 and c.mute_groups == ["quotes"]
    assert set(VOLUME_GROUPS["quotes"][1]) <= muted_stems(c)                # out of the mix and the picture
