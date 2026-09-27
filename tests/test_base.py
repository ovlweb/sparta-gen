"""Base mapping (tempo, bar 1, chords, sections) and fitting a remix to a base."""

import math

import numpy as np
import pytest

from spartagen import arrangement as AR
from spartagen.audio import base as B
from spartagen.audio import dsp
from spartagen.patterns import library as lib
from spartagen.samples import split_point

SR = B.SR


def _tone(midi: float, dur: float, sr: int = SR, harmonics: int = 6, amp: float = 0.15) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    f = 440.0 * 2 ** ((midi - 69) / 12.0)
    x = sum(np.sin(2 * np.pi * f * k * t) / k for k in range(1, harmonics + 1) if f * k < sr / 2.2)
    env = np.minimum(1.0, np.minimum(t / 0.005, (dur - t) / 0.02).clip(0))
    return (amp * x * env).astype(np.float32)


def _kick(sr: int = SR) -> np.ndarray:
    t = np.arange(int(0.18 * sr)) / sr
    f = 50.0 + 120.0 * np.exp(-t / 0.02)
    return (0.8 * np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / 0.08)).astype(np.float32)


def make_base(offset: float = 0.25, bpm: float = 140.0, root_midi: int = 62) -> np.ndarray:
    """A toy base: 2 intro bars (three hits on -2), 8 loud bars of gated chords over the classic
    progression with a kick on every beat, 4 soft bars, 4 loud bars, one final hit on +1."""
    bar = 240.0 / bpm
    step = bar / 16
    prog = [0, 1, -2, 1]
    total = offset + 19 * bar + 2.0
    x = np.zeros(int(total * SR), np.float32)

    def put(sig, t):
        a = int(t * SR)
        b = min(x.shape[0], a + sig.shape[0])
        x[a:b] += sig[:b - a]

    for h in (0, 8, 16):                                   # intro hits
        t = offset + h * step
        put(_tone(root_midi - 2 - 12, 3 * step, amp=0.4), t)
        put(_kick(), t)
    for b in list(range(2, 10)) + list(range(14, 18)):    # loud "chorus" bars
        for s in range(16):
            t = offset + b * bar + s * step
            r = prog[(2 * (b - 2) + s // 8) % 4]
            if s % 4 != 3:
                for iv in (0, 4, 7):
                    put(_tone(root_midi + r + iv, 0.8 * step, amp=0.08), t)
                put(_tone(root_midi + r - 24, 0.8 * step, amp=0.12), t)
            if s % 4 == 0:
                put(_kick(), t)
    for b in range(10, 14):                                # soft breakdown
        for hb in range(2):
            r = prog[(2 * (b - 2) + hb) % 4]
            for iv in (0, 4, 7):
                put(_tone(root_midi + r + iv, bar / 2 - 0.02, amp=0.012), offset + b * bar + hb * bar / 2)
    put(_tone(root_midi + 1 - 12, 1.2, amp=0.4), offset + 18 * bar)   # the last hit, on +1
    return x


@pytest.fixture(scope="module")
def toy_map():
    return B.analyze_base(make_base(), SR)


def test_tempo_and_bar_one(toy_map):
    assert abs(toy_map.bpm - 140.0) < 0.05
    assert abs(toy_map.offset - 0.25) < 0.02
    assert toy_map.bars in (19, 20)          # 19 bars + the last hit's tail


def test_key_and_progression(toy_map):
    assert toy_map.key == "D"
    assert toy_map.progression == "0 1 -2 1"


def test_sections_cover_every_bar_in_order(toy_map):
    secs = toy_map.sections
    assert secs[0].kind == "intro" and secs[0].start_bar == 0 and secs[0].bars == 2
    pos = 0
    for s in secs:
        assert s.start_bar == pos and s.bars > 0
        pos += s.bars
    assert pos == toy_map.bars
    kinds = [s.kind for s in secs]
    assert "chorus" in kinds and "madness" in kinds
    mad = next(s for s in secs if s.kind == "madness")
    assert mad.start_bar == 10 and mad.bars == 4


def test_intro_hits_and_ending_note(toy_map):
    assert [h[0] for h in toy_map.intro_hits] == [0, 8, 16]
    assert all(h[1] == -2 for h in toy_map.intro_hits)
    assert toy_map.ending_root == 1


def test_map_roundtrip(toy_map):
    d = toy_map.to_dict()
    m = B.BaseMap.from_dict(d)
    assert m.bpm == toy_map.bpm and [s.kind for s in m.sections] == [s.kind for s in toy_map.sections]


def _classic_map() -> B.BaseMap:
    kinds = [("intro", 2), ("chorus", 4), ("dundundenden", 6), ("chorus", 4), ("epicness", 4), ("awesomeness1", 4),
             ("chorus", 8), ("madness", 8), ("chorus", 8), ("epicness", 12), ("awesomeness2", 4), ("chorus", 8),
             ("ending", 2)]
    secs, pos = [], 0
    for k, n in kinds:
        secs.append(B.BaseSection(k, pos, n))
        pos += n
    return B.BaseMap(duration=128.0, bpm=140.0, offset=0.139, bars=pos, key_pc=2, progression="0 1 -2 1",
                     sections=secs, intro_hits=[(0, -2), (8, -2), (16, -2)], ending_root=1)


def test_fit_to_base_follows_its_bars():
    bm = _classic_map()
    arr = AR.build_from_base(bm)
    assert arr.total_bars == bm.bars and arr.bpm == 140.0 and arr.progression == "0 1 -2 1"
    assert [s.kind for s in arr.sections] == ["intro", "chorus", "dundundenden", "chorus", "epicness", "awesomeness",
                                              "chorus", "madness", "chorus", "epicness", "awesomeness", "chorus",
                                              "ending"]
    avail = {"pitch1", "pitch2", "pitch3", "chorus_a", "chorus_b", "kick", "clap", "snare", "hat_closed",
             "hat_open", "crash", "quote1", "quote2", "quote3", "phrase", "word_a", "word_b", "bass"}
    ev = AR.compile_events(arr, avail)
    # The chorus plays two layers on the same pattern: the main phrase — its two parts, as they are —
    # and the pitch — main pitch on "1", second pitch on "2" — on the chord roots.
    main = [e for e in ev if e.section_kind == "chorus" and e.track_id == "main"]
    assert {e.sample for e in main} == {"chorus_a", "chorus_b"}
    assert not any(e.pitched for e in main)
    pitch = [e for e in ev if e.section_kind == "chorus" and e.track_id == "pitch"]
    assert {e.sample for e in pitch} == {"pitch1"} and all(e.pitched for e in pitch)
    assert {int(e.semis) % 12 for e in pitch} == {0, 1, 10}            # D, Eb, C (and their octaves)
    # First Chorus: the tutorial's basic pattern — quarter notes on the roots; later: "0*, 12*".
    first = [e for e in pitch if e.section == 1]
    assert {int(e.semis) for e in first} == {0, 1, -2} and all(abs(e.dur - 4 * arr.step_s) < 1e-9 for e in first)
    later = [e for e in pitch if e.section > 1]
    assert {int(e.semis) for e in later} == {0, 12, 1, 13, -2, 10}
    # Optionally the main phrase itself is tuned and follows the chord roots.
    ev_p = AR.compile_events(AR.build_from_base(bm, chorus_pitch=True), avail)
    main_p = [e for e in ev_p if e.section_kind == "chorus" and e.track_id == "main"]
    assert all(e.pitched for e in main_p) and {int(e.semis) for e in main_p} == {0, 1, -2}
    # Intro hits on the base's note, the last hit on the base's last chord.
    intro = [e for e in ev if e.section == 0 and e.track_id == "pitch"]
    assert [round(e.t / arr.step_s) for e in intro] == [0, 8, 16] and {e.semis for e in intro} == {-2.0}
    fin = [e for e in ev if e.section_kind == "ending" and e.track_id == "final"]
    assert fin and fin[0].semis == 1.0


def test_epicness_lead_in_lands_before_the_section():
    bm = _classic_map()
    arr = AR.build_from_base(bm)
    ev = AR.compile_events(arr, {"pitch1", "pitch2", "pitch3"})
    si = max((i for i, s in enumerate(arr.sections) if s.kind == "epicness"), key=lambda i: arr.sections[i].bars)
    t0 = arr.section_starts()[si]
    epic = sorted((e for e in ev if e.section == si and e.track_id.startswith("pitch")), key=lambda e: e.t)
    assert abs(epic[0].t - (t0 - 2 * arr.step_s)) < 1e-6        # the "1*" lead-in, two 16ths early
    # Consecutive 4-bar blocks never double a step: the next block's lead-in replaces the roll's last notes.
    step = lambda e: round((e.t - t0) / arr.step_s, 3)           # noqa: E731
    first_block = [step(e) for e in epic if e.track_id == "pitch"]
    second_block = [step(e) for e in epic if e.track_id == "pitch_1"]
    assert max(first_block) < 62 and min(second_block) == 62.0


def test_percussion_slots_parallel_the_kick():
    tr = AR._perc("perc.normal")
    sec = AR.SectionSpec("chorus", 2, [tr])
    arr = AR.Arrangement("t", "custom", sections=[sec])
    ev = AR.compile_events(arr, {"kick", "clap", "hat_closed"})
    snares = [e for e in ev if e.sample == "clap"]
    assert len(snares) == 4                                   # beats 2 and 4 of both bars
    for sn in snares:
        assert any(e.sample == "kick" and abs(e.t - sn.t) < 1e-9 for e in ev)
    assert len([e for e in ev if e.sample == "hat_closed"]) == 8


def test_library_epicness_edits_are_four_bars_after_the_lead_in():
    for d in lib.EPICNESS:
        if d.pickup:
            assert d.length == 64.0
            assert d.parsed().notes[0].start == 0.0
    orig = lib.get("epic.original").parsed()
    assert orig.voices == 2 and orig.length == 66.0


def test_split_point_finds_the_gap_between_syllables():
    sr = 44100
    a = _tone(62, 0.2, sr)
    gap = np.zeros(int(0.03 * sr), np.float32)
    b = _tone(66, 0.18, sr)
    x = np.concatenate([a, gap, b])
    cut, how = split_point(x, sr)
    assert how == "valley"
    assert a.shape[0] - int(0.005 * sr) <= cut <= a.shape[0] + gap.shape[0] + int(0.005 * sr)


def test_drum_track_switched_to_a_wiki_percussion_pattern_gets_its_slots():
    tr = AR.TrackSpec("kick", "drum", "hat.333", sample="kick", pitched=False)
    arr = AR.Arrangement("t", "custom", sections=[AR.SectionSpec("chorus", 1, [tr])])
    ev = AR.compile_events(arr, {"kick", "clap", "hat_closed"})
    assert ev and {e.sample for e in ev} == {"hat_closed"}


def test_a_looping_lead_in_replaces_the_end_of_the_previous_loop():
    tr = AR.TrackSpec("p", "pitch", "epic.original", mode="index", slots=dict(AR.SLOTS_12), follow="progression")
    arr = AR.Arrangement("t", "custom", sections=[AR.SectionSpec("epicness", 8, [tr])])
    ev = AR.compile_events(arr, {"pitch1", "pitch2", "pitch3"})
    steps = [round(e.t / arr.step_s, 3) for e in ev if e.sample != "pitch3"]
    assert steps.count(62.0) == 1 and 63.0 not in steps     # the "1*" lead-in, not the roll's last 16ths
    assert steps.count(126.0) == 1 and steps.count(127.0) == 1   # the final roll plays to the end
    assert min(steps) == 2.0     # a lead-in before the song starts is dropped; "__1*" follows it
