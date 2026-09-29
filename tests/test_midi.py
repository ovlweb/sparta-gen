"""MIDI bases: reading MIDI files, parts and roles, the remix on their notes, exporting a remix as MIDI."""

import struct
from collections import Counter

import pytest

from spartagen import midi as M
from spartagen.arrangement import compile_events

PROG = [0, 1, -2, 1]


def classic_base(root: int = 62, bars: int = 8, drums: bool = True, intro_bars: int = 0) -> list[dict]:
    """A base in MIDI: a lead in 8ths, triads per half bar, the bass on the roots, a beat."""
    lead, chords, bass, beat = [], [], [], []
    for bar in range(intro_bars, bars):
        for half in range(2):
            r = PROG[((bar - intro_bars) * 2 + half) % 4]
            b0 = bar * 4 + half * 2
            for k, iv in enumerate((12, 19, 12, 24)):
                lead.append((b0 + k * 0.5, 0.45, root + r + iv - 12, 100))
            for iv in (0, 4, 7):
                chords.append((b0, 2.0, root + r + iv, 80))
            bass.append((b0, 1.9, root - 24 + r, 100))
        if drums:
            for b in range(4):
                beat.append((bar * 4 + b, 0.2, 36, 110))
                beat.append((bar * 4 + b + 0.5, 0.1, 42, 70))
                if b in (1, 3):
                    beat.append((bar * 4 + b, 0.2, 39, 100))
    tracks = [{"name": "Lead", "channel": 0, "program": 80, "notes": lead},
              {"name": "Strings", "channel": 1, "program": 48, "notes": chords},
              {"name": "Bass", "channel": 2, "program": 33, "notes": bass}]
    if drums:
        tracks.append({"name": "Drums", "channel": 9, "notes": beat})
    return tracks


@pytest.fixture
def base_mid(tmp_path):
    return M.write_midi(str(tmp_path / "base.mid"), classic_base(), bpm=150)


def test_read_back_what_was_written(base_mid):
    song = M.read_midi(base_mid)
    assert song.bpm == pytest.approx(150.0, abs=0.01)
    assert song.bars == 8 and song.ticks_per_beat == 480 and not song.warnings
    names = {p.name: p for p in song.parts}
    assert set(names) == {"Lead", "Strings", "Bass", "Drums"}
    assert names["Drums"].drums and names["Drums"].channel == 10
    assert names["Strings"].polyphony == 3 and names["Lead"].polyphony == 1
    assert names["Bass"].range_text == "C2–D#2"
    assert len(song.notes) == sum(len(t["notes"]) for t in classic_base())


def _track(events: bytes) -> bytes:
    return b"MTrk" + struct.pack(">I", len(events)) + events


def test_running_status_note_on_zero_and_format_0():
    # Format 0, one track: tempo, then note on C4 / (running status) note on with velocity 0 = off,
    # E4 on channel 2 opened and closed with a real note off.
    ev = (b"\x00\xFF\x51\x03\x07\xA1\x20"                     # 120 BPM
          b"\x00\x90\x3C\x64" b"\x83\x60\x3C\x00"               # C4 for 480 ticks (running status)
          b"\x00\x91\x40\x50" b"\x83\x60\x81\x40\x00"           # E4 on channel 2
          b"\x00\xFF\x2F\x00")
    data = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + _track(ev)
    song = M.parse_midi(data)
    assert song.bpm == pytest.approx(120.0)
    assert [(n.pitch, n.channel, n.dur) for n in song.notes] == [(60, 0, 1.0), (64, 1, 1.0)]
    assert [p.id for p in song.parts] == ["t0c0", "t0c1"]
    assert all("(ch " in p.name for p in song.parts)
    # The same inside a RIFF (.rmi) wrapper.
    riff = b"RIFF" + struct.pack("<I", len(data) + 12) + b"RMIDdata" + struct.pack("<I", len(data)) + data
    assert len(M.parse_midi(riff).notes) == 2


@pytest.mark.parametrize("data, msg", [
    (b"RIFFxxxx", "not a MIDI file"),
    (b"MThd" + struct.pack(">IHHH", 6, 1, 1, 0xE728) + _track(b"\x00\xFF\x2F\x00"), "SMPTE"),
    (b"MThd" + struct.pack(">IHHH", 6, 1, 1, 480) + _track(b"\x00\xFF\x2F\x00"), "no notes"),
])
def test_bad_files_are_refused(data, msg):
    with pytest.raises(M.MidiError, match=msg):
        M.parse_midi(data)


@pytest.mark.parametrize("root, key", [(62, "D"), (63, "D#"), (60, "C"), (57, "A")])
def test_the_key_is_where_the_sparta_progression_starts(tmp_path, root, key):
    path = M.write_midi(str(tmp_path / "k.mid"), classic_base(root=root, drums=False, intro_bars=0), bpm=140)
    assert M.read_midi(path).key == key


def test_a_key_signature_names_the_key_when_no_progression_fits(tmp_path):
    melody = [(i * 0.5, 0.5, p, 90) for i, p in enumerate([67, 71, 74, 72, 71, 69, 67, 66, 67, 74, 79, 78])]
    path = M.write_midi(str(tmp_path / "g.mid"), [{"name": "Tune", "notes": melody}], key_sig=(1, 0))
    assert M.read_midi(path).key == "G"


def test_roles_are_suggested_and_a_remix_is_built(base_mid):
    song = M.read_midi(base_mid)
    roles = {song.part(pid).name: m["role"] for pid, m in M.suggest_roles(song).items()}
    assert roles == {"Lead": "pitch1", "Strings": "chords", "Bass": "bass", "Drums": "drums"}
    arr = M.build_from_midi(song)
    assert arr.bpm == pytest.approx(150.0) and arr.key == "D" and arr.total_bars == 8
    ev = compile_events(arr)
    c = Counter(e.sample for e in ev)
    assert c["pitch1"] == 64 and c["bass"] == 16 and c["kick"] == 32 and c["clap"] == 16
    assert c["pitch2"] == c["pitch3"] == c["pitch4"] == 16            # a voice per chord note
    assert c["chorus_a"] + c["chorus_b"] > 0                           # the main phrase on the Chorus pattern
    first = min((e for e in ev if e.sample == "pitch1"), key=lambda e: e.t)
    assert first.t == pytest.approx(0.0) and first.semis == 0.0       # D5 lead → the pitch sample's own D
    bass = min((e for e in ev if e.sample == "bass"), key=lambda e: e.t)
    assert bass.semis == 0.0


def test_parts_can_be_switched_off_moved_an_octave_and_the_drums_added(base_mid):
    song = M.read_midi(base_mid)
    ids = {p.name: p.id for p in song.parts}
    m = M.suggest_roles(song)
    m[ids["Drums"]] = {"role": "off"}
    m[ids["Strings"]] = {"role": "off"}
    m[ids["Lead"]] = {"role": "pitch1", "octave": 1}
    arr = M.build_from_midi(song, m, auto_percussion=False, auto_phrase=False)
    ev = compile_events(arr)
    assert not any(e.stem == "drums" for e in ev)
    assert not any(e.sample in ("pitch2", "pitch3", "pitch4", "chorus_a") for e in ev)
    lowest = min(e.semis for e in ev if e.sample == "pitch1")
    m[ids["Lead"]] = {"role": "pitch1", "octave": 0}
    plain = compile_events(M.build_from_midi(song, m, auto_percussion=False, auto_phrase=False))
    assert lowest == min(e.semis for e in plain if e.sample == "pitch1") + 12      # an octave up
    ev = compile_events(M.build_from_midi(song, m, auto_percussion=True, auto_phrase=False))
    assert Counter(e.sample for e in ev if e.stem == "drums")["kick"] > 0      # Sparta percussion added
    with pytest.raises(ValueError, match="unknown role"):
        M.clean_mapping(song, {ids["Lead"]: {"role": "trumpet"}})


def test_a_chorus_channel_plays_the_main_phrase(tmp_path):
    notes = [(b * 1.0, 0.5, 60 if b % 2 == 0 else 62, 100) for b in range(16)]
    path = M.write_midi(str(tmp_path / "c.mid"), [{"name": "Chorus", "notes": notes}] + classic_base(bars=4))
    song = M.read_midi(path)
    m = M.suggest_roles(song)
    assert m[song.parts[0].id]["role"] == "chorus"
    ev = compile_events(M.build_from_midi(song, m))
    main = sorted((e for e in ev if e.track_id.startswith("midi_t1")), key=lambda e: e.t)
    assert [e.sample for e in main[:4]] == ["chorus_a", "chorus_b", "chorus_a", "chorus_b"]
    assert not any(e.track_id == "main_auto" for e in ev)             # no Chorus pattern over it


def _with_intro(intro_bars: int, bars: int = 12) -> list[dict]:
    """The classic base with an intro: only the chords and the bass play before the lead and the beat."""
    tracks = classic_base(bars=bars)
    for tr in tracks:
        if tr["name"] in ("Lead", "Drums"):
            tr["notes"] = [n for n in tr["notes"] if n[0] >= 4 * intro_bars]
    return tracks


@pytest.mark.parametrize("intro_bars", [1, 4])
def test_the_chorus_comes_in_where_the_base_s_chorus_does(tmp_path, intro_bars):
    path = M.write_midi(str(tmp_path / "intro.mid"), _with_intro(intro_bars), bpm=150)
    song = M.read_midi(path)
    parts = [(s.kind, s.start, s.bars) for s in M.song_structure(song)]
    assert parts[0] == ("intro", 0, intro_bars) and parts[1][:2] == ("chorus", intro_bars)
    arr = M.build_from_midi(song)
    assert [s.kind for s in arr.sections][:2] == ["intro", "chorus"]
    ev = compile_events(arr)
    bar = 4 * 60.0 / 150
    phrase = [e.t for e in ev if e.sample in ("chorus_a", "chorus_b")]
    assert min(phrase) == pytest.approx(intro_bars * bar)              # not from 0:00
    lead = min(e.t for e in ev if e.sample == "pitch1")
    assert lead == pytest.approx(intro_bars * bar)                     # the base's own parts where it has them


def test_a_doubled_channel_starts_off(tmp_path):
    tracks = classic_base(bars=4, drums=False)
    lead = tracks[0]["notes"]
    tracks.append({"name": "Lead copy", "channel": 3, "program": 81,
                   "notes": [(t, d, p + 12, v) for t, d, p, v in lead]})       # the same line an octave up
    song = M.read_midi(M.write_midi(str(tmp_path / "dbl.mid"), tracks))
    names = {p.name: p for p in song.parts}
    assert names["Lead copy"].double_of == names["Lead"].id and not names["Lead"].double_of
    roles = {song.part(pid).name: m["role"] for pid, m in M.suggest_roles(song).items()}
    assert roles["Lead"] == "pitch1" and roles["Lead copy"] == "off"


def test_a_bass_is_found_by_what_it_plays_not_by_its_name(tmp_path):
    """Stroll's "Generic saw bass" plays thirds up in the 4th octave: a pitch like the others.  The bass is the
    part playing the chords' roots — even written an octave up."""
    roots = [61, 62, 59, 62]                                   # C#, D, B, D: a chord every two beats
    pad, root_line, thirds, lead = [], [], [], []
    for bar in range(8):
        for half in range(2):
            r, t = roots[(bar * 2 + half) % 4], bar * 4 + half * 2
            pad += [(t, 2.0, r + iv, 70) for iv in (0, 3, 7, 10)]
            root_line.append((t, 2.0, r, 90))
            thirds += [(t + k * 0.5, 0.25, r + 7 + iv, 90) for k in range(4) for iv in (0, 3)]
            lead += [(t + k * 0.25, 0.25, r + 12 + (k % 3) * 2, 90) for k in range(8)]
    path = M.write_midi(str(tmp_path / "stroll.mid"), [
        {"name": "Lead", "channel": 0, "notes": lead}, {"name": "Pad", "channel": 1, "notes": pad},
        {"name": "Generic saw bass", "channel": 2, "notes": thirds},
        {"name": "Zombitronic", "channel": 3, "notes": root_line}])
    song = M.read_midi(path)
    roles = {song.part(pid).name: m["role"] for pid, m in M.suggest_roles(song).items()}
    assert roles["Zombitronic"] == "bass" and roles["Generic saw bass"].startswith("pitch")
    assert roles["Pad"] == "chords" and roles["Lead"] == "pitch1"


def test_channels_that_never_play_together_share_a_pitch(tmp_path):
    def line(first_bar, bars, note):
        return [(b * 4 + k, 0.5, note + k, 90) for b in range(first_bar, first_bar + bars) for k in range(4)]
    tracks = [{"name": f"Lead {i}", "channel": i, "notes": line(0, 8, 60 + i)} for i in range(3)]
    tracks += [{"name": "Early", "channel": 4, "notes": line(0, 4, 72)},
               {"name": "Late", "channel": 5, "notes": line(4, 4, 74)},
               {"name": "Again", "channel": 6, "notes": line(2, 4, 76)}]
    song = M.read_midi(M.write_midi(str(tmp_path / "six.mid"), tracks))
    roles = {song.part(pid).name: m["role"] for pid, m in M.suggest_roles(song).items()}
    assert sorted(roles[f"Lead {i}"] for i in range(3)) == ["pitch1", "pitch2", "pitch3"]
    assert roles["Early"] == roles["Late"] == "pitch4"         # one after the other: one pitch, heard both times
    assert roles["Again"] == "off"                             # it plays with every one of them


def test_a_midi_chord_is_layers_in_one_box_and_every_line_has_its_own_box(base_mid):
    from spartagen.render_video import line_cells
    song = M.read_midi(base_mid)
    arr = M.build_from_midi(song)
    ev = compile_events(arr)
    chords = [e for e in ev if e.track_id.startswith("midi_") and e.sample in ("pitch2", "pitch3", "pitch4")]
    by_onset: dict[float, list] = {}
    for e in chords:
        by_onset.setdefault(round(e.t, 6), []).append(e)
    assert by_onset and all(len(v) == 3 for v in by_onset.values())
    assert all(sum(e.visual not in ("none", "layer") for e in v) == 1 for v in by_onset.values())
    assert all(sorted(e.layer for e in v) == [0, 1, 2] for v in by_onset.values())       # one picture, two layers
    lines = line_cells(arr, ev)
    for si in range(len(arr.sections)):
        boxes = [c for (s, _line), c in lines.items() if s == si]
        assert len(boxes) == len(set(boxes))
    assert all(s.layout == "main" for s in arr.sections if s.kind in ("intro", "chorus", "ending"))


def test_auto_percussion_is_the_sparta_percussion(tmp_path):
    path = M.write_midi(str(tmp_path / "nodrums.mid"), classic_base(bars=8, drums=False), bpm=150)
    arr = M.build_from_midi(M.read_midi(path))
    ids = {t.id for s in arr.sections for t in s.tracks}
    assert {"perc_auto", "chat_auto", "hat2_auto", "snl_auto"} <= ids
    perc = next(t for s in arr.sections for t in s.tracks if t.id == "perc_auto")
    assert perc.pattern == "perc.sparta"


def test_session_follows_a_midi_base(tmp_path, base_mid):
    from spartagen.project import Session
    s = Session(workspace=str(tmp_path / "w"))
    m = s.set_midi(base_mid)
    assert s.project.variant == "midi" and m["path"].startswith(str(tmp_path / "w"))
    assert s.project.samples["key"] == "D" and m["summary"]["bars"] == 8
    arr = s.arrangement()
    assert arr.variant == "midi" and arr.bpm == pytest.approx(150.0)
    drums = next(p["id"] for p in m["summary"]["parts"] if p["drums"])
    s.set_midi_mapping({drums: {"role": "off"}}, auto_percussion=False)
    assert not any(e.stem == "drums" for e in compile_events(s.arrangement()))
    s.clear_midi()
    assert s.project.variant == "unextended" and s.project.midi is None


def test_a_midi_remix_renders(tmp_path, synthetic_source):
    from spartagen.project import Session
    path = M.write_midi(str(tmp_path / "short.mid"), classic_base(bars=2), bpm=150)
    s = Session(workspace=str(tmp_path / "w"))
    s.set_source(synthetic_source)
    s.set_midi(path)
    res = s.render("audio")
    assert res["duration"] == pytest.approx(2 * 1.6, abs=3.0) and res["events"] > 50


def test_a_remix_exports_as_midi(tmp_path, base_mid):
    arr = M.build_from_midi(M.read_midi(base_mid))
    ev = compile_events(arr)
    out = M.arrangement_to_midi(arr, ev, str(tmp_path / "remix.mid"))
    back = M.read_midi(out)
    assert back.bpm == pytest.approx(150.0, abs=0.01)
    drums = [p for p in back.parts if p.drums]
    assert drums and drums[0].name == "drums"
    assert len(back.notes) == len(ev)
