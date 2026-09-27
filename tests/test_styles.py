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
