"""Visual styles: presets, options chosen by hand, the effects themselves, a render in a style."""

import numpy as np
import pytest

from spartagen import render_video as RV
from spartagen.arrangement import NoteEvent


def _event(**kw) -> NoteEvent:
    d = dict(t=0.0, dur=0.2, track="0:pitch", track_id="pitch", stem="pitch", kind="pitch", sample="pitch1",
             semis=0.0, gain_db=0.0, pan=0.0, crisp=True, sustain=False, oneshot=False, pitched=True, choke=True,
             section=0, section_kind="chorus", visual="pitch_cycle", flip="alternate", index=1)
    d.update(kw)
    return NoteEvent(**d)


def test_styles_set_their_options_and_hand_picked_options_win():
    c = RV.VideoConfig.from_dict({"preset_name": "preview", "style": "retro"})
    assert (c.width, c.style, c.tint, c.scanlines) == (640, "retro", "warm", 0.35)
    c = RV.VideoConfig.from_dict({"style": "retro", "tint": "cold", "scanlines": 0.0})
    assert c.tint == "cold" and c.scanlines == 0.0 and c.grain == 0.35
    classic = RV.VideoConfig.from_dict({})
    assert classic.style == "classic" and classic.punch == 0.035 and classic.border == "none"
    assert RV.VideoConfig.from_dict({"zoom_punch": False}).punch == 0.0          # the old switch still works
    assert set(RV.STYLES) == set(RV.STYLE_NAMES)
    with pytest.raises(ValueError, match="visual style"):
        RV.VideoConfig.from_dict({"style": "vaporwave"})
    with pytest.raises(ValueError, match="tint"):
        RV.VideoConfig.from_dict({"tint": "purple"})


def test_flip_modes():
    e = _event(index=1, flip="alternate")
    assert RV.flip_for(e, "auto") == "h" and RV.flip_for(e, "none") == "none"
    assert RV.flip_for(_event(index=2), "rotate") == "hv"
    fr = np.arange(2 * 4 * 3, dtype=np.uint8).reshape(2, 4, 3)
    m = RV._apply_flip(fr, "mirror")
    assert (m[:, 3] == fr[:, 0]).all() and (m[:, 2] == fr[:, 1]).all() and (m[:, :2] == fr[:, :2]).all()


def test_colour_effects():
    fr = np.zeros((4, 4, 3), np.uint8)
    fr[..., 0] = 200
    cfg = RV.VideoConfig.from_dict({"color_fx": "hue_cycle"})
    out = RV.cell_fx(fr, _event(index=1), cfg, fresh=False)
    assert out[0, 0].tolist() == [0, 0, 200]                    # the red clip turned blue on this hit
    assert RV.cell_fx(fr, _event(visual="main", sample="chorus_a"), cfg, False) is fr   # the phrase keeps its colours
    cfg = RV.VideoConfig.from_dict({"color_fx": "mono"})
    g = RV.cell_fx(fr, _event(), cfg, False)
    assert g[0, 0, 0] == g[0, 0, 1] == g[0, 0, 2]
    cfg = RV.VideoConfig.from_dict({"color_fx": "invert_crash"})
    assert RV.cell_fx(fr, _event(visual="crash", sample="crash"), cfg, True)[0, 0, 0] == 55


def test_hit_animations_grow_or_slide_the_box_then_settle():
    cfg = RV.VideoConfig.from_dict({"hit_anim": "pop"})
    x, y, w, h = RV.anim_rect(100, 100, 200, 100, _event(), 0.0, cfg, 1280, 720)
    assert w > 200 and h > 100 and x < 100 and y < 100
    assert RV.anim_rect(100, 100, 200, 100, _event(), 0.2, cfg, 1280, 720) == (100, 100, 200, 100)
    cfg = RV.VideoConfig.from_dict({"hit_anim": "slide"})
    x, _, w, _ = RV.anim_rect(100, 100, 200, 100, _event(index=1), 0.0, cfg, 1280, 720)
    assert x != 100 and w == 200


def test_borders_and_glow_stay_on_the_canvas():
    c = np.zeros((50, 60, 3), np.uint8)
    RV.draw_border(c, 10, 10, 20, 20, (255, 0, 0), "line")
    assert c[10, 15, 0] == 255 and c[20, 20, 0] == 0
    c = np.zeros((50, 60, 3), np.uint8)
    RV.draw_border(c, 0, 0, 60, 50, (0, 255, 0), "glow")          # a box at the edges: glow clipped
    RV.draw_border(c, 20, 20, 10, 10, (0, 255, 0), "glow")
    assert c[15, 25, 1] > 0 and c[15, 25, 1] < c[19, 25, 1]       # fading away from the box


def test_whole_frame_effects():
    W, H = 64, 36
    grey = np.full((H, W, 3), 128, np.uint8)
    post = RV.PostFX(RV.VideoConfig.from_dict({"vignette": 0.8, "letterbox": 0.1, "scanlines": 0.5}), W, H)
    out = post.apply(grey.copy(), 0, 5.0, 1e9, 1e9, 1e9)
    assert out[:4].max() == 0 and out[-4:].max() == 0                 # letterbox
    assert out[5, 1, 0] < out[H // 2, W // 2, 0]                      # vignette: corners darker
    assert out[H // 2 + 1 - (H // 2 + 1) % 3 + 1, W // 2, 0] < out[H // 2 - (H // 2) % 3, W // 2, 0]
    fade = RV.PostFX(RV.VideoConfig.from_dict({"transition": "fade"}), W, H)
    assert fade.apply(grey.copy(), 0, 0.0, 1e9, 1e9, 0.0).max() == 0          # a part fades in
    flash = RV.PostFX(RV.VideoConfig.from_dict({"transition": "flash"}), W, H)
    assert flash.apply(grey.copy(), 0, 0.0, 1e9, 1e9, 0.0).min() > 128
    rgb = RV.PostFX(RV.VideoConfig.from_dict({"rgb_split": 1.0}), W, H)
    bar = np.zeros((H, W, 3), np.uint8)
    bar[:, 30:34] = 255
    split = rgb.apply(bar, 0, 0.0, 0.0, 1e9, 1e9)
    assert split[:, 30:34, 1].min() == 255 and (split[:, 34:, 0] > 0).any()   # red moved right
    sepia = RV.PostFX(RV.VideoConfig.from_dict({"tint": "sepia"}), W, H).apply(grey.copy(), 0, 5, 1e9, 1e9, 1e9)
    assert sepia[0, 0, 0] > sepia[0, 0, 2]


@pytest.mark.parametrize("style", ["xleth", "retro"])
def test_a_remix_renders_in_a_style(tmp_path, synthetic_source, style):
    from spartagen.project import Session
    s = Session(workspace=str(tmp_path / "w"))
    s.set_source(synthetic_source)
    s.set_variant("unextended")
    s.project.video = {"style": style, "width": 320, "height": 180}
    res = s.render("preview")
    from spartagen import ffmpeg as ff
    info = ff.probe(res["file"])
    assert info.has_video and (info.width, info.height) == (320, 180) and info.duration > 60


def test_a_chord_is_three_layers_in_one_box_from_normal_to_small():
    """A chord's voices are layers in its box — the whole box, then smaller, then smaller again — sat where
    the box sits: centred in a box in the middle of the frame, against the side of a box at a side."""
    W, H = 1280, 720
    mid = RV.layer_anchor(440, 260, 400, 200, W, H)
    assert mid == (0.5, 0.5)
    assert [RV.layer_rect(440, 260, 400, 200, k, mid) for k in range(3)] == \
        [(440, 260, 400, 200), (480, 280, 320, 160), (520, 300, 240, 120)]
    left = RV.layer_anchor(0, 0, 256, 144, W, H)                  # the top row's first box: left, top
    assert left == (0.0, 0.0) and RV.layer_rect(0, 0, 256, 144, 2, left) == (0, 0, 152, 86)
    right = RV.layer_anchor(1024, 0, 256, 144, W, H)              # its last: right, top
    x, y, w, h = RV.layer_rect(1024, 0, 256, 144, 2, right)
    assert right == (1.0, 0.0) and (x + w, y, w, h) == (1280, 0, 152, 86)
    cells = RV.LAYOUT_CELLS["main"]
    where = {c: RV.layer_anchor(*RV._px(cells[c], W, H, 4), W, H) for c in ("t0", "t1", "t2", "t3", "l", "main", "r", "b0")}
    assert where == {"t0": (0.0, 0.0), "t1": (0.0, 0.0), "t2": (0.5, 0.0), "t3": (1.0, 0.0), "l": (0.0, 0.5),
                     "main": (0.5, 0.5), "r": (1.0, 0.5), "b0": (0.0, 1.0)}
    for layout in ("main", "full", "grid3", "split2", "grid4"):
        assert RV.cell_for(_event(visual="layer", layer=1), layout) is None      # never a box of its own


def test_a_drums_box_never_shows_a_pitch():
    """Each box is one sound's: the 4x4 grid's pitch cycle goes past the boxes the part's drums and bass have
    (and through those of the drums it has not)."""
    from spartagen.arrangement import Arrangement, SectionSpec
    drums = ("kick", "snare", "hat", "crash", "bass")
    fixed = {RV.cell_for(_event(visual=v, sample=v), "grid4") for v in drums + ("hat2", "perc")}
    cycled = {RV.cell_for(_event(index=i), "grid4") for i in range(24)}
    assert None not in fixed and len(cycled) >= 5 and not cycled & fixed
    arr = Arrangement("t", "custom", sections=[SectionSpec("epicness", 4, [], layout="grid4")])
    some = [_event(visual=v, sample=v) for v in drums]
    cycle = RV.grid4_cycles(arr, some + [_event(index=i) for i in range(12)])[0]
    used = {RV.cell_for(e, "grid4") for e in some}
    assert len(cycle) == 7 and not set(cycle) & used
    assert {RV.cell_for(_event(index=i), "grid4", cycle) for i in range(24)} == set(cycle)


def test_the_4x4_grid_has_a_box_for_every_drum():
    """The second hi-hat, the other percussion and a part's opening crash have boxes in the 4x4 grid too."""
    boxes = [RV.cell_for(_event(visual=v, sample=v), "grid4") for v in ("kick", "snare", "hat", "hat2", "perc",
                                                                         "crash", "bass")]
    assert None not in boxes and len(set(boxes)) == len(boxes)
    assert RV.cell_for(_event(visual="hit", sample="crash"), "grid4") == RV.GRID4_FIXED["crash"]


def test_the_madness_words_keep_their_sides():
    """The call is on the left and the response on the right, even when the source has one word for both."""
    call, response = _event(visual="madness", sample="word_a"), _event(visual="madness", sample="word_b")
    stand_in = _event(visual="madness", sample="word_a", asked="word_b")
    assert [RV.cell_for(e, "split2") for e in (call, response, stand_in)] == ["left", "right", "right"]
    assert [RV.cell_for(e, "grid3") for e in (call, response, stand_in)] == ["ml", "mr", "mr"]


def test_the_madness_shows_its_words_split_and_every_part_in_a_grid(tmp_path, synthetic_source):
    """Split in two, the Madness is its call and response; in a grid its pitches, bass and drums have their
    boxes too.  One word found: the response shows it on the right; none: the main phrase's halves."""
    import copy
    from spartagen.arrangement import compile_events
    from spartagen.project import Session
    s = Session(workspace=str(tmp_path / "w"))
    s.set_source(synthetic_source)
    bank = s.bank()
    arr = s.arrangement()
    mi = next(i for i, sec in enumerate(arr.sections) if sec.kind == "madness")
    assert arr.sections[mi].layout == "split2"
    cfg = RV.VideoConfig.from_dict({"preset_name": "preview", "width": 320, "height": 180})

    def shown(layout: str, drop: tuple = ()) -> dict:
        a = copy.deepcopy(arr)
        a.sections[mi].layout = layout
        have = set(bank.samples) - set(drop)
        comp = RV.Compositor(s.project.source_path, a, compile_events(a, have), bank, cfg)
        out: dict = {}
        for v in comp.vis:
            if v[3].section == mi:
                out.setdefault(v[2], set()).add(v[3].visual)
        return out

    split = shown("split2")
    assert set(split) == {"left", "right"} and set().union(*split.values()) == {"madness"}
    for layout in ("grid3", "grid4", "main"):
        seen = set().union(*shown(layout).values())
        assert {"madness", "pitch_cycle", "bass", "kick", "snare", "hat"} <= seen, layout
    one = shown("split2", ("word_b",))
    assert set(one) == {"left", "right"}
    if "chorus_a" in bank.samples and "chorus_b" in bank.samples:
        assert set(shown("split2", ("word_a", "word_b"))) == {"left", "right"}


def test_a_madness_saved_with_hidden_parts_shows_them_again():
    from spartagen.arrangement import SectionSpec, sec_madness
    sec = sec_madness(8, {"base": True})
    assert {t.id: t.visual for t in sec.tracks if t.id in ("pitch", "pitch_gate", "bass")} == \
        {"pitch": "pitch_cycle", "pitch_gate": "pitch_cycle", "bass": "bass"}
    old = sec.to_dict()
    for t in old["tracks"]:
        if t["id"] in ("pitch", "pitch_gate", "bass"):
            t["visual"] = "none"
    back = SectionSpec.from_dict(old)
    assert {t.id: t.visual for t in back.tracks} == {t.id: t.visual for t in sec.tracks}


def test_a_clip_runs_as_fast_as_its_note():
    """A note shifted the way a sampler does (classic pitching, the bass) plays faster up and slower down: its
    clip too.  A formant-kept note keeps its length, and its clip its speed."""
    from spartagen.render_audio import clip_rate
    from spartagen.samples import Sample
    z = np.zeros(10, np.float32)
    pitch = Sample("pitch1", "pitch", "pitch1", 0, 1, z, 44100, 62.0, tuned=object())
    bass = Sample("bass", "bass", "bass", 0, 1, z, 44100, 50.0, video_rate=0.5)
    up = _event(semis=12.0)
    assert clip_rate(up, pitch, "normal") == 1.0 and clip_rate(up, pitch, "hard") == 1.0
    assert clip_rate(up, pitch, "classic") == 2.0
    assert clip_rate(_event(sample="bass", semis=-12.0), bass, "normal") == 0.25
    assert clip_rate(_event(pitched=False, semis=12.0), pitch, "classic") == 1.0      # a hit as it is


def test_a_still_is_the_frame_the_video_shows_with_the_chord_layers(tmp_path, synthetic_source):
    from spartagen.arrangement import compile_events
    from spartagen.project import Session
    s = Session(workspace=str(tmp_path / "w"))
    s.set_source(synthetic_source)
    s.set_variant("unextended")
    bank = s.bank()
    arr = s.arrangement()
    ev = compile_events(arr, set(bank.samples))
    cfg = RV.VideoConfig.from_dict({"preset_name": "preview", "width": 320, "height": 180})
    comp = RV.Compositor(s.project.source_path, arr, ev, bank, cfg)
    starts = arr.section_starts()               # (a part's opening hit covers every box for an 8th)
    chord = next(e for e in ev if e.visual == "layer" and e.t - starts[e.section] > 2.5 * arr.step_s)
    k0 = int(chord.t * cfg.fps) + 1
    shown = {}
    for k in range(k0 + 3):
        f = comp.next_frame(k)
        if k >= k0:
            shown[k] = f
    for k, f in shown.items():
        assert np.array_equal(comp.still(k / cfg.fps), f), k
    plain = RV.Compositor(s.project.source_path, arr, [e for e in ev if e.visual != "layer"], bank, cfg)
    assert not np.array_equal(plain.still(k0 / cfg.fps), shown[k0])       # the layers are drawn
    # No colours of their own: a style's border goes round the chord's box, never round its layers.
    base = next(a for a in comp.vis if (a[3].section, a[3].track_id, round(a[3].t, 6)) ==
                (chord.section, chord.track_id, round(chord.t, 6)))
    x0, y0, w, h = RV._px(RV.LAYOUT_CELLS[arr.sections[chord.section].layout][base[2]], cfg.width, cfg.height, cfg.gap)
    stills = [RV.Compositor(s.project.source_path, arr, ev, bank, RV.VideoConfig.from_dict(
        {"preset_name": "preview", "width": 320, "height": 180, "border": b, "border_color": "#00ff00",
         "punch": 0.0})).still(k0 / cfg.fps) for b in ("none", "line")]         # (no kick zoom moving the boxes)
    changed = (stills[0] != stills[1]).any(axis=2)
    assert changed[y0:y0 + h, x0:x0 + w].any()                             # the box has its border …
    assert not changed[y0 + 2:y0 + h - 2, x0 + 2:x0 + w - 2].any()          # … and nothing inside it


def _clip(path: str, *lavfi: str, extra: tuple = ()) -> str:
    from spartagen import ffmpeg as ff
    cmd = [ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y"]
    for src in lavfi:
        cmd += ["-f", "lavfi", "-i", src]
    ff.run(cmd + list(extra) + [path])
    return path


def test_the_background_loops_with_no_gap(tmp_path):
    """Issue 2: the background went black where the file has sound but no more picture, then came back from
    the start.  Now the picture's own end is the loop: after its last frame comes its first."""
    from spartagen import ffmpeg as ff
    src = _clip(str(tmp_path / "short.mp4"), "testsrc2=s=160x90:r=25:d=2", "sine=d=3.5",
                extra=("-pix_fmt", "yuv420p"))
    info = ff.probe(src)
    assert info.duration > 3.0
    bd = RV.Backdrop(src, 160, 90, 25.0, info.duration)
    frames = [bd.frame(k / 25.0) for k in range(int(5 * 25))]
    assert all(f is not None for f in frames)
    assert 1.9 <= bd.duration <= 2.1
    first = bd.frame(0.4)
    assert np.array_equal(bd.frame(0.4 + bd.duration), first) and np.array_equal(bd.frame(0.4 + 3 * bd.duration), first)
    assert not np.array_equal(bd.frame(0.8), first)


def test_the_background_is_soft_without_blocks(tmp_path):
    """Issue 2: the blurred background looked pixelated — the picture shrunk to a few pixels and blown up, whose
    blocks stay put while the picture moves under them.  Now it is blurred smoothly: moved, it only moves."""
    from spartagen import ffmpeg as ff
    big = _clip(str(tmp_path / "big.mp4"), "testsrc2=s=1344x720:r=25:d=0.2", extra=("-pix_fmt", "yuv420p", "-crf", "8"))
    a, b = (_clip(str(tmp_path / f"{dx}.mp4"), extra=("-i", big, "-vf", f"crop=1280:720:{dx}:0", "-pix_fmt", "yuv420p",
                                                      "-crf", "8")) for dx in (0, 16))
    soft = [ff.read_blurred(p, 0.0, 0.04, 25.0, 1280, 720)[0].astype(np.float32) for p in (a, b)]
    assert float(np.abs(soft[1][40:-40, 40:-56] - soft[0][40:-40, 56:-40]).mean()) < 1.0


@pytest.mark.parametrize("kind", ["picture", "gif"])
def test_a_picture_or_gif_of_your_own_behind_the_boxes(tmp_path, kind):
    from spartagen import ffmpeg as ff
    if kind == "picture":
        path = _clip(str(tmp_path / "bg.png"), "testsrc2=s=320x180:r=1:d=1", extra=("-frames:v", "1"))
    else:
        path = _clip(str(tmp_path / "bg.gif"), "testsrc2=s=160x90:r=10:d=1")
    cfg = RV.VideoConfig.from_dict({"preset_name": "preview", "width": 160, "height": 90, "background": "file",
                                    "background_file": path})
    bd = RV.backdrop_for(cfg, "", False, 0.0)
    assert bd is not None and bd.blur is False
    a, b = bd.frame(0.3), bd.frame(7.3)
    assert a is not None and b is not None and a.shape == (90, 160, 3)
    if kind == "picture":
        assert np.array_equal(a, bd.frame(12.0))       # a picture stays
    else:
        assert np.array_equal(a, b)                    # a GIF loops (1 s long)
    sharp = ff.read_blurred(path, 0.0, 0.1, 10.0, 160, 90, blur=False)[0].astype(np.float32)
    soft = ff.read_blurred(path, 0.0, 0.1, 10.0, 160, 90)[0].astype(np.float32)
    edges = lambda f: float((np.diff(f, axis=1) ** 2).mean())    # noqa: E731
    assert edges(soft) < 0.5 * edges(sharp)
    missing = RV.VideoConfig.from_dict({"background": "file", "background_file": str(tmp_path / "gone.gif")})
    assert RV.backdrop_for(missing, "", True, 1.0) is None


def test_a_grid_of_the_pitches_and_percussion_only(tmp_path, synthetic_source):
    """Issue 2's feature: a grid without the chorus — a box for each pitch line, the bass and each drum, the
    grid as big as the part needs; the chorus is heard, not seen."""
    import copy
    from spartagen.arrangement import compile_events
    from spartagen.project import Session
    s = Session(workspace=str(tmp_path / "w"))
    s.set_source(synthetic_source)
    bank = s.bank()
    arr = copy.deepcopy(s.arrangement())
    ci = next(i for i, sec in enumerate(arr.sections) if sec.kind == "chorus")
    arr.sections[ci].layout = "pitchperc"
    ev = compile_events(arr, set(bank.samples))
    cfg = RV.VideoConfig.from_dict({"preset_name": "preview", "width": 320, "height": 180})
    comp = RV.Compositor(s.project.source_path, arr, ev, bank, cfg)
    cells, where = comp.pp[ci]
    shown = [v for v in comp.vis if v[3].section == ci]
    assert shown and not any(v[3].visual in ("main", "center", "madness") for v in shown)
    assert {v[2] for v in shown} <= set(cells)
    parts = {RV.pp_part(v[3]) for v in shown}
    assert len(where) == len(cells) == len(parts) and {"kick", "snare"} <= parts
    assert any(p.startswith("line:") for p in parts)
    boxes = list(cells.values())                 # in the frame, none over another
    assert all(x >= 0 and y >= 0 and x + w <= 1 + 1e-9 and y + h <= 1 + 1e-9 for x, y, w, h in boxes)
    assert len({(x, y) for x, y, _w, _h in boxes}) == len(boxes)
    t = arr.section_starts()[ci] + 2.5 * arr.bar_s
    assert comp.still(t).shape == (180, 320, 3)


def test_a_background_of_unknown_length_plays_and_loops(tmp_path):
    from spartagen import ffmpeg as ff
    src = _clip(str(tmp_path / "short.mp4"), "testsrc2=s=160x90:r=25:d=2", extra=("-pix_fmt", "yuv420p"))
    bd = RV.Backdrop(src, 160, 90, 25.0, 0.0)                      # (a file that does not say how long it is)
    a, b = bd.frame(0.4), bd.frame(1.4)
    assert a is not None and b is not None and not np.array_equal(a, b)          # it plays …
    assert np.array_equal(bd.frame(2.0 + 1.4 + 0.01), bd.frame(1.4))              # … and loops at its end
    assert 1.9 <= bd.duration <= 2.1
