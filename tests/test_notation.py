import pytest

from spartagen.patterns import library as lib
from spartagen.patterns.notation import detect_mode, parse, parse_progression, retarget


def test_key_symbol_durations():
    p = parse("0 0* 0** 0*** 0' 0\" 0***** 0******", "semitone")
    assert [n.dur for n in p.notes] == [1, 2, 3, 4, 0.5, 0.25, 6, 8]
    rests = parse("0_0/0\\0", "semitone")
    assert [n.start for n in rests.notes] == [0, 2, 3.5, 4.75]


def test_signed_and_multidigit_semitones():
    p = parse("0* 12* -2* 10* +3", "semitone")
    assert [n.value for n in p.notes] == [0, 12, -2, 10, 3]


def test_standard_chorus_is_eight_bars_of_slots():
    d = lib.get("chorus.standard")
    p = d.parsed()
    assert p.mode == "index"
    assert p.length == 128
    assert set(p.values()) == {1, 2}


def test_madness_patterns_add_up():
    assert lib.get("madwords.original").parsed().length == 128      # 8 bars of call & response
    first = lib.get("mad.first").parsed()
    assert first.mode == "compact" and first.length == 32
    # Compact notation: every digit is a note, the sign binds to the next digit.
    assert first.values()[:8] == [0, 0, 0, 0, 0, 0, 1, 1]
    assert -2 in first.values()


def test_awesomeness_is_four_bars_each():
    for pid in ("awe.1_major", "awe.2_major", "awe.1_minor", "awe.2_minor"):
        assert lib.get(pid).parsed().length == 64, pid


def test_mode_detection():
    assert detect_mode("11_11_111_1_1_11222_2_222_222_2_") == "index"
    assert detect_mode("00_00_0011_11_11-2-2_-2-2_-2-211_11_11") == "compact"
    assert detect_mode("0* 12* 0* 12* 1* 13*") == "semitone"
    assert detect_mode("1***____________2***____________1* 1* 1 1") == "index"
    assert detect_mode("7* 5' 7' 5 4* 7* 8* 6'") == "semitone"


@pytest.mark.parametrize("pid", [p.id for p in lib.ALL if p.section in ("chorus", "dundundenden", "awesomeness",
                                                                        "madness", "chords", "execution")])
def test_library_patterns_loop_on_bar_lines(pid):
    d = lib.get(pid)
    p = d.parsed()
    assert p.notes, pid
    loop = d.length or p.loop_length()
    assert loop % 8 == 0, (pid, p.length)


def test_progression_split_and_retarget():
    orig = parse_progression("0 1 -2 1")
    twist = parse_progression("0 1 2 1 | -1")
    assert [orig.root_at(s) for s in (0, 8, 16, 24)] == [0, 1, -2, 1]
    assert twist.root_at(24) == 1 and twist.root_at(28) == -1
    # A note on C (-2) in the third chord moves to E (+2) under the "E Note" twist.
    assert retarget(-2, 17, orig, twist) == 2
    assert retarget(10, 17, orig, twist) == 14


def test_warnings_for_unknown_symbols():
    p = parse("0* x 1*", "semitone")
    assert p.warnings and len(p.notes) == 2


def test_b_plays_slots_one_and_two_together():
    p = parse("1*B*_B", "index")
    assert [(n.start, n.value) for n in p.notes] == [(0.0, 1), (2.0, 1), (2.0, 2), (5.0, 1), (5.0, 2)]
    assert p.length == 6.0


def test_double_apostrophe_is_a_64th():
    p = parse("1''1''2'", "index")
    assert [n.dur for n in p.notes] == [0.25, 0.25, 0.5]


# ── the block editor: notes written back as notation ─────────────────────────


@pytest.mark.parametrize("pid", [p.id for p in lib.ALL if p.section != "progression"])
def test_every_library_pattern_is_written_back_as_the_same_notes(pid):
    from collections import Counter
    from spartagen.patterns.notation import write
    p = lib.get(pid).parsed()
    mode = "index" if p.mode == "index" else "semitone"
    back = parse(write(p.notes, mode, p.length), mode)
    notes = lambda q: Counter((n.start, n.dur, n.value, n.sharp) for n in q.notes)    # noqa: E731
    assert notes(back) == notes(p) and back.length == p.length and not back.warnings


def test_written_notes_read_as_the_wiki_writes_them():
    from spartagen.patterns.notation import write
    assert write([{"start": 0, "dur": 2, "value": 0}, {"start": 2, "dur": 1, "value": 12},
                  {"start": 4, "dur": 7, "value": -5}], "semitone", 16) == "0* 12 _ -5*****= _____"
    # Notes that sound together go on lines of their own; a 32nd and a sharp slot are kept.
    assert write([{"start": 0, "dur": 1, "value": 1}, {"start": 0, "dur": 1, "value": 2},
                  {"start": 3, "dur": 0.5, "value": 3, "sharp": 1}, {"start": 4, "dur": 3, "value": 1, "sharp": 1}],
                 "index", 8) == "1__3'#/1**#_\n2_______"
    with pytest.raises(ValueError):
        write([{"start": 0, "dur": 1, "value": 12}], "index")


def test_a_pattern_through_the_block_editor_plays_the_same_notes():
    """Every track of every structure, opened in the block editor and saved unchanged: the same notes — the
    Epicness's lead-in, a pattern's own loop and a free melody (never moved with the chords) are kept."""
    import copy
    from spartagen import arrangement as AR
    from spartagen.patterns.notation import write
    from test_base import _classic_map
    have = {"pitch1", "pitch2", "pitch3", "pitch4", "chorus_a", "chorus_b", "chorus_c", "bass", "kick", "snare", "clap",
            "hat_closed", "hat_open", "hat2", "perc", "crash", "word_a", "word_b", "quote1", "quote2", "quote3", "syl1",
            "syl2", "phrase"}
    sets = [AR.build_arrangement(v) for v in AR.VARIANTS] + [AR.build_from_base(_classic_map())]
    lead_in = AR.build_arrangement("extended")            # an Epicness pattern with a lead-in ("1*" before bar 1)
    for i, sec in enumerate(lead_in.sections):
        if sec.kind == "epicness":
            pid = [p.id for p in lib.ALL if p.pickup][i % 3]
            for tr in sec.tracks:
                if tr.kind == "pitch" and tr.pattern and not tr.voice_samples:
                    tr.pattern, tr.mode = pid, "auto"
    sets.append(lead_in)
    key = lambda e: (round(e.t, 5), round(e.dur, 5), e.track, e.sample, e.semis, e.visual, round(e.max_len, 4))  # noqa
    seen = set()
    for arr in sets:
        after = copy.deepcopy(arr)
        for tr in (t for sec in after.sections for t in sec.tracks if t.pattern and not t.follow.startswith("@")):
            b = AR.pattern_blocks(tr)
            seen.add((b["mode"], b["pickup"] > 0, b["over"]))
            tr.pattern, tr.mode = "text:" + write(b["notes"], b["mode"], b["pickup"] + b["loop"]), b["mode"]
            tr.loop, tr.pickup, tr.over = b["loop"], b["pickup"], b["over"]
        assert [key(e) for e in AR.compile_events(after, have)] == [key(e) for e in AR.compile_events(arr, have)]
    assert {m for m, _p, _o in seen} == {"index", "semitone"} and {"", "none"} <= {o for _m, _p, o in seen}
    assert any(p for _m, p, _o in seen)          # (lead-ins among them)
