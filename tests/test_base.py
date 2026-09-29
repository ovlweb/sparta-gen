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


def make_base(offset: float = 0.25, bpm: float = 140.0, root_midi: int = 62, third: int = 4) -> np.ndarray:
    """A toy base: 2 intro bars (three hits on -2), 8 loud bars of gated chords over the classic
    progression with a kick on every beat, 4 soft bars, 4 loud bars, one final hit on +1.
    ``third`` = 3 makes the chords minor."""
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
                for iv in (0, third, 7):
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
    assert toy_map.minor is False


def test_a_minor_base_is_read_as_minor_and_its_remix_plays_minor_chords():
    m = B.analyze_base(make_base(third=3), SR)
    assert m.key == "D" and m.progression == "0 1 -2 1" and m.minor is True
    arr = AR.build_from_base(m)
    ev = AR.compile_events(arr, {"pitch1", "pitch2", "pitch3", "pitch4", "chorus_a", "chorus_b"})
    third = {int(e.semis) for e in ev if e.section_kind == "chorus" and e.track_id == "pitch" and e.sample == "pitch2"}
    assert 3 in third and 4 not in third
    # The user can still ask for major chords on it.
    arr_major = AR.build_from_base(m, minor=False)
    ev = AR.compile_events(arr_major, {"pitch1", "pitch2", "pitch3", "pitch4", "chorus_a", "chorus_b"})
    third = {int(e.semis) for e in ev if e.section_kind == "chorus" and e.track_id == "pitch" and e.sample == "pitch2"}
    assert 4 in third and 3 not in third


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
    # A Chorus there instead (as one example remix on the extended base does) is one option away.
    alt = AR.build_from_base(bm, extra={"dundundenden_part": "chorus"})
    assert alt.sections[2].kind == "chorus" and alt.sections[2].bars == 6 and alt.sections[2].name == "Chorus 2"
    avail = {"pitch1", "pitch2", "pitch3", "pitch4", "chorus_a", "chorus_b", "kick", "clap", "snare", "hat_closed",
             "hat_open", "crash", "quote1", "quote2", "quote3", "phrase", "word_a", "word_b", "bass"}
    ev = AR.compile_events(arr, avail)
    # The chorus plays two layers: the main phrase — its two parts, as they are — on the index pattern,
    # and several pitches on the "1*, 12*, Chords" lines, one pitch sample per line.
    main = [e for e in ev if e.section_kind == "chorus" and e.track_id == "main"]
    assert {e.sample for e in main} == {"chorus_a", "chorus_b"}
    assert not any(e.pitched for e in main)
    pitch = [e for e in ev if e.section_kind == "chorus" and e.track_id == "pitch"]
    assert all(e.pitched for e in pitch)
    line = lambda smp, secs: {int(e.semis) for e in pitch if e.sample == smp and e.section in secs}  # noqa: E731
    choruses = sorted({e.section for e in pitch})
    assert line("pitch1", choruses) == {0, 12, 1, 13, -2, 10}          # roots: D, Eb, C (and octaves)
    assert line("pitch2", choruses) == {4, 16, 5, 17, 2, 14}           # major thirds
    assert line("pitch3", choruses) == {7, 19, 8, 20, 5, 17}           # fifths
    # No seventh line (a major seventh and a raised eleventh clash with the base's major chords): in the
    # final Chorus the fourth pitch doubles the roots an octave down instead, and nothing goes an octave up.
    assert line("pitch4", choruses) == set()
    low = [e for e in ev if e.section_kind == "chorus" and e.track_id == "pitch_low"]
    assert {e.section for e in low} == {choruses[-1]} and {e.sample for e in low} == {"pitch4"}
    assert {int(e.semis) for e in low} == {-12, 0, -11, 1, -14, -2}
    assert max(e.semis for e in ev if e.section_kind == "chorus" and e.pitched) <= 20
    # The voices play together: every root note has its third and fifth at the same time.
    for e in (e for e in pitch if e.sample == "pitch1"):
        assert {x.sample for x in pitch if abs(x.t - e.t) < 1e-9} >= {"pitch1", "pitch2", "pitch3"}
    # Epicness and Awesomeness hold the chords on the second to fourth pitch under their patterns.
    for kind in ("epicness", "awesomeness"):
        chords = [e for e in ev if e.section_kind == kind and e.track_id == "chords"]
        assert {e.sample for e in chords} == {"pitch2", "pitch3", "pitch4"}
    # Optionally the main phrase itself is tuned and follows the chord roots.
    ev_p = AR.compile_events(AR.build_from_base(bm, chorus_pitch=True), avail)
    main_p = [e for e in ev_p if e.section_kind == "chorus" and e.track_id == "main"]
    assert all(e.pitched for e in main_p) and {int(e.semis) for e in main_p} == {0, 1, -2}
    # Intro hits on the base's note, the last hit on the base's last chord.
    intro = [e for e in ev if e.section == 0 and e.track_id == "pitch"]
    assert [round(e.t / arr.step_s) for e in intro] == [0, 8, 16] and {e.semis for e in intro} == {-2.0}
    fin = [e for e in ev if e.section_kind == "ending" and e.track_id == "final"]
    assert fin and fin[0].semis == 1.0


def test_epicness_starts_on_its_downbeat_in_every_block():
    """The Epicness as the tutorial plays it: 1_1_332_1_1_11__… — the first hit on the downbeat, the
    same four bars in every block, the second line's 3s before and over the closing roll."""
    bm = _classic_map()
    arr = AR.build_from_base(bm)
    ev = AR.compile_events(arr, AVAIL_ALL)
    si = max((i for i, s in enumerate(arr.sections) if s.kind == "epicness"), key=lambda i: arr.sections[i].bars)
    t0 = arr.section_starts()[si]
    step = lambda e: round((e.t - t0) / arr.step_s, 3)           # noqa: E731
    main = sorted((e for e in ev if e.section == si and e.track_id.startswith("main")), key=lambda e: e.t)
    assert step(main[0]) == 0.0
    want = [0, 2, 4, 5, 6, 8, 10, 12, 13, 16, 18, 20, 21, 22, 24, 26, 27, 28, 29, 30, 32, 34, 36, 37, 38, 39, 40,
            41, 42, 44, 45, 46] + list(range(48, 64))
    for blk in range(arr.sections[si].bars // 4):
        steps = sorted({step(e) - 64 * blk for e in main if 64 * blk <= step(e) < 64 * (blk + 1)})
        assert steps == want, blk
        threes = sorted(step(e) - 64 * blk for e in main if 64 * blk <= step(e) < 64 * (blk + 1)
                        and e.sample == "chorus_c")
        assert threes == [4, 5, 22, 24, 32, 36, 37, 39, 41, 52, 55, 57, 58, 59, 60, 62, 63]
    # An explicit edit still alternates, and a lead-in pattern still reaches back before its block.
    arr2 = AR.build_from_base(bm, extra={"epicness_pattern": "epic.original",
                                         "epicness_edit": "epic.catmanteam_late2015"})
    ev2 = AR.compile_events(arr2, AVAIL_ALL)
    epic = sorted((e for e in ev2 if e.section == si and e.track_id.startswith("pitch")), key=lambda e: e.t)
    assert abs(epic[0].t - (t0 - 2 * arr.step_s)) < 1e-6        # the "1*" lead-in, two 16ths early
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


def test_a_chord_is_three_layers_in_one_box_and_lines_never_share_a_box():
    """A chord's voices (0/3/7 lines, a pitch sample each) all sound and are seen together in its line's box:
    the root is the chord's picture, the third and fifth layers over it — not one box per voice, which
    covered the other lines' boxes."""
    from spartagen.render_video import cell_for, line_cells, line_of, LINE_VISUALS
    arr = AR.build_from_base(_classic_map())
    avail = {"pitch1", "pitch2", "pitch3", "pitch4", "chorus_a", "chorus_b", "bass", "kick", "clap", "hat_closed"}
    ev = AR.compile_events(arr, avail)
    lines = line_cells(arr, ev)
    si = next(i for i, s in enumerate(arr.sections) if s.kind == "chorus")
    chorus = [e for e in ev if e.section == si and e.track_id == "pitch"]
    by_onset: dict[float, list] = {}
    for e in chorus:
        by_onset.setdefault(round(e.t, 6), []).append(e)
    assert by_onset and all(len(v) == 3 for v in by_onset.values())           # root, third and fifth sound …
    for v in by_onset.values():
        shown = [e for e in v if e.visual not in ("none", "layer")]
        assert [e.sample for e in shown] == ["pitch1"]                          # … the root is the picture …
        layers = sorted((e.layer, e.sample) for e in v if e.visual == "layer")
        assert layers == [(1, "pitch2"), (2, "pitch3")]                         # … third and fifth over it
        assert len({e.index for e in v}) == 1                                   # (they flip together)
    assert lines[(si, "pitch")] == "t0"
    fc = max(i for i, s in enumerate(arr.sections) if s.kind == "chorus")
    assert lines[(fc, "pitch")] == "t0" and lines[(fc, "pitch_low")] == "t3"
    # Epicness: the melody (pitches 1-3) in pitch 1's box; the held chords are seen once per chord, through
    # the one pitch the melody does not show (their root is on pitch 4), in that pitch's box.
    ep = next(i for i, s in enumerate(arr.sections) if s.kind == "epicness")
    assert lines[(ep, "pitch")] == "t0" and lines[(ep, "chords")] == "t3"
    melody = {e.sample for e in ev if e.section == ep and e.track_id == "pitch"}
    chords = [e for e in ev if e.section == ep and e.track_id == "chords"]
    seen = [e for e in chords if e.visual not in ("none", "layer")]
    assert melody == {"pitch1", "pitch2", "pitch3"}
    assert {e.sample for e in chords} == {"pitch2", "pitch3", "pitch4"} and {e.sample for e in seen} == {"pitch4"}
    assert [e.index for e in seen[:4]] == [0, 1, 2, 3]                          # the box flips chord by chord
    assert cell_for(seen[0], "grid4") == "c21"
    # Where the melody shows only pitch 1 (the Awesomeness), the chords keep their own order.
    aw = next(i for i, s in enumerate(arr.sections) if s.kind == "awesomeness")
    assert {e.sample for e in ev if e.section == aw and e.track_id == "chords"
            and e.visual not in ("none", "layer")} == {"pitch2"}
    # No two lines share a box in any part.
    for s, sec in enumerate(arr.sections):
        mine = {v for k, v in lines.items() if k[0] == s}
        assert len(mine) == sum(1 for k in lines if k[0] == s), sec.name
        drums = {cell_for(e, sec.layout) for e in ev if e.section == s and e.visual not in LINE_VISUALS}
        assert not (mine - {"main"}) & drums, sec.name
    # A 12-bar Epicness plays its pattern in 4-bar blocks ("pitch", "pitch_1" …): one line, one box.
    long_ep = max((i for i, s in enumerate(arr.sections) if s.kind == "epicness"), key=lambda i: arr.sections[i].bars)
    blocks = {e.track_id for e in ev if e.section == long_ep and e.track_id.startswith("pitch")}
    assert blocks == {"pitch", "pitch_1", "pitch_2"} and {line_of(e) for e in ev if e.track_id in blocks
                                                             and e.section == long_ep} == {(long_ep, "pitch")}


def test_a_pitch_is_cut_where_the_video_cuts_away():
    from spartagen.audio.analysis import Candidate
    from spartagen.samples import trim_to_shot
    c = Candidate("pitch", 10.0, 10.4, 0.8, {"f0": 293.7})
    assert trim_to_shot(c, []) is c and trim_to_shot(c, [9.0, 11.0]) is c
    t = trim_to_shot(c, [10.3])                      # the longest part before the cut stays
    assert t is not None and t.start == 10.0 and abs(t.end - 10.26) < 1e-9
    assert t.info["f0"] == 293.7 and t.info["shot_trimmed"] == [10.0, 10.4]
    t = trim_to_shot(c, [10.07])                     # or after it
    assert abs(t.start - 10.11) < 1e-9 and t.end == 10.4
    assert trim_to_shot(c, [10.13, 10.26]) is None     # nothing long enough to hold a note


def test_shot_cuts_finds_a_camera_cut(tmp_path):
    from spartagen import ffmpeg as ff
    out = str(tmp_path / "cut.mp4")
    ff.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25:d=1",
            "-f", "lavfi", "-i", "color=c=0x2040ff:s=160x90:r=25:d=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", out])
    cuts = ff.shot_cuts(out, 0.5, 1.5)
    assert len(cuts) == 1 and abs(cuts[0] - 1.0) <= 0.041
    assert ff.shot_cuts(out, 0.1, 0.9) == []        # moving picture, no cut


AVAIL_ALL = {"pitch1", "pitch2", "pitch3", "pitch4", "chorus_a", "chorus_b", "chorus_c", "chorus_c_a",
             "chorus_c_b", "bass", "kick", "clap", "hat2", "perc",
             "snare", "hat_closed", "hat_open", "crash", "quote1", "quote2", "quote3", "phrase", "word_a", "word_b"}


def test_the_main_phrase_keeps_playing_through_the_epicness():
    """The Epicness is played with the Chorus's samples — 1 and 2 are its two parts, 3 a third word —
    and the main phrase stays big in the middle; the pitches play the same pattern on the chords."""
    from spartagen.render_video import cell_for
    arr = AR.build_from_base(_classic_map())
    ev = AR.compile_events(arr, AVAIL_ALL)
    for si, sec in enumerate(arr.sections):
        if sec.kind != "epicness":
            continue
        assert sec.layout == "main"
        main = [e for e in ev if e.section == si and e.track_id.startswith("main")]
        assert {e.sample for e in main} == {"chorus_a", "chorus_b", "chorus_c"}
        assert not any(e.pitched for e in main) and all(cell_for(e, sec.layout) == "main" for e in main)
        pitch = [e for e in ev if e.section == si and e.track_id.startswith("pitch")]
        # Same rhythm: every pitch note has the main phrase with it.
        starts = {round(e.t, 6) for e in main}
        assert pitch and all(round(e.t, 6) in starts for e in pitch)
        # The first hit on the section's downbeat.
        t0 = arr.section_starts()[si]
        assert abs(min(e.t for e in main) - t0) < 1e-6


def test_the_main_phrase_follows_the_awesomeness_rhythm():
    arr = AR.build_from_base(_classic_map())
    ev = AR.compile_events(arr, AVAIL_ALL)
    si = next(i for i, s in enumerate(arr.sections) if s.kind == "awesomeness")
    t0 = arr.section_starts()[si]
    main = [e for e in ev if e.section == si and e.track_id == "main"]
    melody = [e for e in ev if e.section == si and e.track_id == "pitch"]
    assert main and {round(e.t, 6) for e in main} <= {round(e.t, 6) for e in melody}
    for e in main:
        st = round((e.t - t0) / arr.step_s) % 16
        assert e.sample == ("chorus_a" if st < 8 else "chorus_b") and not e.pitched


def test_the_ending_hits_once_then_a_quote_plays():
    arr = AR.build_from_base(_classic_map())
    ev = AR.compile_events(arr, AVAIL_ALL)
    si = len(arr.sections) - 1
    assert arr.sections[si].kind == "ending"
    t0 = arr.section_starts()[si]
    end = [e for e in ev if e.section == si]
    by = {}
    for e in end:
        by.setdefault(e.track_id, []).append(round((e.t - t0) / arr.step_s, 3))
    # Nothing loops: one hit on the base's last chord …
    for tid in ("final", "bass", "kick", "snare", "crash"):
        assert by[tid] == [0.0], (tid, by[tid])
    assert sorted(e.sample for e in end if e.track_id == "final_chord") == ["pitch2", "pitch3"]
    assert {e.semis for e in end if e.track_id == "final"} == {1.0}              # the base's last chord (+1)
    assert {e.semis for e in end if e.track_id == "final_chord"} == {5.0, 8.0}   # its third and fifth
    # … then the quote, as it is, a quarter note later.
    q = [e for e in end if e.track_id == "quote"]
    assert [round((e.t - t0) / arr.step_s) for e in q] == [4] and q[0].sample == "quote1" and not q[0].pitched


def test_a_crash_hits_once_on_its_downbeat():
    arr = AR.build_from_base(_classic_map())
    ev = AR.compile_events(arr, AVAIL_ALL)
    starts = arr.section_starts()
    for si, sec in enumerate(arr.sections):
        crashes = [e for e in ev if e.section == si and e.track_id == "crash"]
        steps = [round((e.t - starts[si]) / arr.step_s) for e in crashes]
        # Each crash lands on its bar's downbeat, once (no echo half a bar later).
        assert all(st % 16 == 0 for st in steps) and len(steps) == len(set(steps)), (sec.kind, steps)


def test_percussion_on_a_base_is_the_sparta_percussion_without_fills_or_doubles():
    """The kick line 1_332_331_332_33 (kick on 1 and 3, snare with the kick paralleled on 2 and 4, open
    hats between) and hi-hat 1 on every 8th, in every section with drums — no fills of our own over the
    base's, no double kicks."""
    arr = AR.build_from_base(_classic_map())
    ev = AR.compile_events(arr, AVAIL_ALL)
    starts = arr.section_starts()
    for si, sec in enumerate(arr.sections):
        if sec.kind not in ("chorus", "epicness", "awesomeness", "madness"):
            continue
        assert not any("fill" in tr.id for tr in sec.tracks), sec.kind
        drums = [e for e in ev if e.section == si and e.stem == "drums" and e.track_id == "perc"]
        for bar in range(sec.bars):
            hits = {}
            for e in drums:
                st = round((e.t - starts[si]) / arr.step_s - 16 * bar, 3)
                if 0 <= st < 16:
                    hits.setdefault(e.sample, []).append(st)
            assert sorted(hits["kick"]) == [0, 4, 8, 12], (sec.kind, bar, hits)
            # "Open hi-hats are mostly used for in-pattern hi-hats … the closed one mostly used a repetitive
            # pattern" (Percussion, Sparta Remix Wiki): the pattern's 3s are open hats, closed hats on every 8th.
            assert sorted(hits["clap"]) == [4, 12]
            assert sorted(hits["hat_open"]) == [2, 3, 6, 7, 10, 11, 14, 15]
            at = [round((e.t - starts[si]) / arr.step_s - 16 * bar, 3) for e in ev
                  if e.section == si and e.track_id == "chat"]
            closed = sorted(st for st in at if 0 <= st < 16)
            assert closed == [0, 2, 4, 6, 8, 10, 12, 14]


def test_chorus_frame_sections_open_with_a_fullscreen_hit():
    from spartagen.render_video import cell_for, LAYOUT_CELLS
    arr = AR.build_from_base(_classic_map())
    ev = AR.compile_events(arr, AVAIL_ALL)
    starts = arr.section_starts()
    for si, sec in enumerate(arr.sections):
        if sec.layout != "main" or sec.kind == "dundundenden":      # the DunDunDenDen opens on its own hit
            continue
        hit = [e for e in ev if e.section == si and e.track_id == "crash"]
        assert [round((e.t - starts[si]) / arr.step_s) for e in hit] == [0], sec.kind
        assert cell_for(hit[0], "main") == "full"
    # The hit's cell is drawn last (over the frame).
    assert list(LAYOUT_CELLS["main"])[-1] == "full" and LAYOUT_CELLS["main"]["full"] == (0.0, 0.0, 1.0, 1.0)


def test_timbre_tells_voices_apart_whatever_the_note():
    from spartagen.samples import Sample, sample_timbre, timbre_distance
    from tests.conftest import harmonic_tone
    sr = 44100
    def smp(f0, formant):
        return Sample("t", "pitch", "t", 0.0, 0.3, harmonic_tone(f0, 0.3, sr, formant=formant), sr, 62.0)
    a, a2 = sample_timbre(smp(293.7, 700.0)), sample_timbre(smp(293.7 * 1.02, 700.0))
    b = sample_timbre(smp(293.7, 2200.0))
    scale = np.ones_like(a)
    assert timbre_distance(a, b, scale) > 3 * timbre_distance(a, a2, scale)


def test_dundundenden_steps_through_the_main_phrase_with_the_pitches():
    """The wiki's Original Pattern 1___2___3A___3B___: the main phrase's parts and the third word's halves
    on the quarter notes, as they are, with a pitch sample on each hit on the chord root; percussion
    joins a third of the way in, the held chords and the bass two thirds in (0:10 / 0:13 / 0:17 on the
    extended base)."""
    arr = AR.build_from_base(_classic_map())
    ev = AR.compile_events(arr, AVAIL_ALL)
    si = next(i for i, s in enumerate(arr.sections) if s.kind == "dundundenden")
    sec, t0 = arr.sections[si], arr.section_starts()[si]
    assert sec.bars == 6 and sec.layout == "main"
    at = lambda e: round((e.t - t0) / arr.step_s, 3)            # noqa: E731
    main = sorted((e for e in ev if e.section == si and e.track_id == "main"), key=lambda e: e.t)
    assert [at(e) for e in main] == [4.0 * k for k in range(24)]
    assert [e.sample for e in main[:4]] == ["chorus_a", "chorus_b", "chorus_c_a", "chorus_c_b"]
    assert not any(e.pitched for e in main)
    pitch = sorted((e for e in ev if e.section == si and e.track_id == "pitch"), key=lambda e: e.t)
    assert [at(e) for e in pitch] == [at(e) for e in main]
    assert [e.sample for e in pitch[:4]] == ["pitch1", "pitch2", "pitch3", "pitch4"]
    assert [int(e.semis) for e in pitch[:8]] == [0, 0, 1, 1, -2, -2, 1, 1]
    drums = [at(e) for e in ev if e.section == si and e.stem == "drums" and not e.track_id.startswith("crash")]
    assert drums and min(drums) == 32.0                          # bar 3 of 6 (0:13.7 on the extended base)
    first = lambda tid: min(at(e) for e in ev if e.section == si and e.track_id == tid)   # noqa: E731
    assert first("chords") == 64.0 and first("bass") == 66.0      # bar 5 (0:17.1); the bass on the off-beat


def test_the_epicness_is_the_block_that_ends_on_the_roll():
    """The Epicness ends on a roll of 16ths; when the labels put it one block early (the extended base:
    its roll is in bar 24), the rolling block becomes the Epicness and the earlier one joins the Chorus."""
    S = B.BaseSection
    secs = [S("intro", 0, 2), S("chorus", 2, 4), S("dundundenden", 6, 6), S("chorus", 12, 4), S("epicness", 16, 4),
            S("awesomeness1", 20, 4), S("chorus", 24, 8)]
    out = B.epicness_by_roll(secs, {23})
    assert [(s.kind, s.start_bar, s.bars) for s in out] == [
        ("intro", 0, 2), ("chorus", 2, 4), ("dundundenden", 6, 6), ("chorus", 12, 8), ("epicness", 20, 4),
        ("chorus", 24, 8)]
    # An Epicness that ends on its own roll stays where it is.
    secs = [S("chorus", 0, 4), S("epicness", 4, 4), S("awesomeness1", 8, 4)]
    assert [s.kind for s in B.epicness_by_roll(secs, {7, 11})] == ["chorus", "epicness", "awesomeness1"]


def test_roll_bars_finds_a_roll_of_16ths():
    sr = SR
    bar = 240.0 / 140.0
    x = np.zeros(int(4 * bar * sr), np.float32)
    rng = np.random.default_rng(1)
    def hit(t):
        a = int(t * sr)
        n = int(0.03 * sr)
        x[a:a + n] += (0.5 * rng.standard_normal(n) * np.exp(-np.arange(n) / (0.006 * sr))).astype(np.float32)
    for b in range(4):
        for st in (0, 4, 8, 12):
            hit(b * bar + st * bar / 16)
    for st in range(8, 16):                                  # bar 3's second half: a 16th roll
        hit(2 * bar + st * bar / 16)
    assert B.roll_bars(x, sr, 0.0, bar, 4) == {2}


def test_the_background_is_the_source_blurred(tmp_path):
    from spartagen import ffmpeg as ff
    src = str(tmp_path / "src.mp4")
    ff.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", "testsrc2=s=320x180:r=25:d=2", "-pix_fmt", "yuv420p", src])
    sharp = ff.read_frames(src, 0.5, 0.2, 25.0, 320, 180).astype(np.float32)
    soft = ff.read_blurred(src, 0.5, 0.2, 25.0, 320, 180).astype(np.float32)
    assert soft.shape == sharp.shape
    edges = lambda f: float((np.diff(f, axis=2) ** 2).mean())    # noqa: E731  (edge energy)
    assert edges(soft) < 0.25 * edges(sharp)
    assert abs(float(soft.mean()) - float(sharp.mean())) < 25       # the same picture, just soft


def test_no_text_over_the_video_by_default():
    from spartagen.render_video import VideoConfig
    for name in ("preview", "720p", "1080p"):
        cfg = VideoConfig.preset_of(name)
        assert cfg.titles is False and cfg.intro_title is False
    assert VideoConfig.from_dict({"titles": True}).titles is True      # still there for whoever wants it


def test_sparta_percussion_layers_hats_and_snare_line():
    """Under the kick line: hi-hat 2 on every 16th, the snare line on dotted 8ths for a bar and a half
    (snare and a second hit taking turns, 1__2__1__2__…), and an extra hit on the "and"s of beats 3 and 4."""
    from spartagen.render_video import cell_for
    arr = AR.build_from_base(_classic_map())
    ev = AR.compile_events(arr, AVAIL_ALL)
    si = next(i for i, s in enumerate(arr.sections) if s.kind == "chorus")
    t0 = arr.section_starts()[si]
    at = lambda tid: sorted(round((e.t - t0) / arr.step_s) for e in ev if e.section == si and e.track_id == tid)  # noqa: E731
    assert at("hat2")[:32] == list(range(32))
    assert at("snl")[:9] == [0, 3, 6, 9, 12, 15, 18, 21, 32]           # then half a bar of rest, and again
    assert at("xperc")[:4] == [10, 14, 26, 30]
    snl = sorted((e for e in ev if e.section == si and e.track_id == "snl"), key=lambda e: e.t)
    assert [e.sample for e in snl[:4]] == ["snare", "perc", "snare", "perc"]
    h2 = next(e for e in ev if e.section == si and e.track_id == "hat2")
    xp = next(e for e in ev if e.section == si and e.track_id == "xperc")
    assert h2.sample == "hat2" and xp.sample == "perc"
    assert cell_for(h2, "main") == "b4" and cell_for(xp, "main") == "b3" and cell_for(h2, "full") is None
    assert cell_for(snl[0], "main") == "b1"
