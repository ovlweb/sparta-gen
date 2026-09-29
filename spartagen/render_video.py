"""Sparta Remix visuals: every note shows its sample's video clip, in sync.

Layouts per section follow what remixers build in Vegas: fullscreen hits
(Intro, DunDunDenDen — black between the "DUN"s), a left/right split for the
Madness call & response, the Chorus with the main phrase big in the middle,
pitches along the top and drums along the bottom, and 3x3 / 4x4 grids for the
Epicness and Awesomeness.  Clips flip on every hit (alternate or
rotate), flash on the attack, and the frame punches with the kick.

A visual *style* (``VideoConfig.style``) sets the look — classic, clean, Xleth,
retro VHS, neon, cinematic, mirror — and every option it sets (flips, hit
animations, punch, shake, RGB split, borders, colour FX, tint, scanlines, grain,
vignette, letterbox, section transitions, background) can be changed on its own.
"""

from __future__ import annotations

import math
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from . import ffmpeg as ff
from .arrangement import Arrangement, NoteEvent
from .render_audio import audible_length
from .samples import SampleBank

Progress = Optional[Callable[[float, str], None]]


#: Visual styles: what each sets (anything chosen by hand wins).
STYLES: dict[str, dict] = {
    "classic": {},
    "clean": {"flip_mode": "none", "flash": False, "punch": 0.0, "background": "black", "border": "line",
              "hit_anim": "none", "gap": 6},
    "xleth": {"flip_mode": "rotate", "flash": True, "punch": 0.07, "rgb_split": 0.5, "shake": 0.35,
              "border": "glow", "hit_anim": "pop", "transition": "flash", "color_fx": "invert_crash"},
    "retro": {"scanlines": 0.35, "grain": 0.35, "rgb_split": 0.3, "tint": "warm", "vignette": 0.55,
              "hit_anim": "none", "punch": 0.03, "transition": "fade"},
    "neon": {"background": "dark", "border": "glow", "color_fx": "hue_cycle", "flash": True, "hit_anim": "pop",
             "vignette": 0.35, "tint": "vivid", "punch": 0.05},
    "cinematic": {"letterbox": 0.11, "vignette": 0.6, "flip_mode": "none", "punch": 0.015, "transition": "fade",
                  "tint": "cold", "hit_anim": "slide", "flash": False},
    "mirror": {"background": "mirror", "flip_mode": "mirror", "hit_anim": "pop", "transition": "zoom",
               "punch": 0.05},
}
STYLE_NAMES = {"classic": "Classic (Vegas grid)", "clean": "Clean", "xleth": "Xleth (hard)",
               "retro": "Retro VHS", "neon": "Neon", "cinematic": "Cinematic", "mirror": "Mirror"}
#: The options a style sets and their choices (for pickers).
STYLE_OPTIONS = {
    "flip_mode": ["auto", "none", "alternate", "rotate", "mirror"],
    "hit_anim": ["none", "pop", "slide"],
    "border": ["none", "line", "glow"],
    "color_fx": ["none", "hue_cycle", "invert_crash", "mono"],
    "tint": ["none", "warm", "cold", "sepia", "vivid"],
    "transition": ["cut", "flash", "fade", "zoom"],
    "background": ["blur", "black", "dark", "mirror", "gradient"],
}


@dataclass
class VideoConfig:
    width: int = 1280
    height: int = 720
    fps: float = 30.0
    crf: int = 20
    preset: str = "veryfast"
    background: str = "blur"          # blur (the source, blurred and dimmed) | black | dark
    background_dim: float = 0.42
    intro_title: bool = False         # the remix title over the first seconds
    flash: bool = True
    zoom_punch: bool = True
    gap: int = 4
    min_hold_s: float = 0.09          # drums/short hits stay visible at least this long
    hold_last: bool = True            # keep the last clip of a cell (dimmed) instead of blinking to black
    hold_dim: float = 0.3
    blink_sections: tuple = ("dundundenden", "intro_hits", "ending")  # these stay black between hits
    titles: bool = False              # the spinning "OMG TEH EPICNESS" over the Epicness (off; needs Pillow)
    memory_mb: int = 700
    # ── style (see STYLES) ──
    style: str = "classic"
    flip_mode: str = "auto"           # auto (each track's own) | none | alternate | rotate | mirror
    hit_anim: str = "none"            # none | pop (the box grows on the hit) | slide (it slides in)
    punch: float = 0.035              # zoom punch on every kick (0 = off)
    shake: float = 0.0                # 0-1: the frame shakes on kicks and crashes
    rgb_split: float = 0.0            # 0-1: red and blue split on kicks
    border: str = "none"              # none | line | glow (in the part's colour)
    border_color: str = "auto"        # auto (by part) or #rrggbb
    color_fx: str = "none"            # none | hue_cycle (every hit a new hue) | invert_crash | mono (all but the phrase)
    tint: str = "none"                # none | warm | cold | sepia | vivid
    scanlines: float = 0.0            # 0-1
    grain: float = 0.0                # 0-1
    vignette: float = 0.0             # 0-1
    letterbox: float = 0.0            # bar height as a fraction of the frame (cinematic ~0.1)
    transition: str = "cut"           # at each part: cut | flash | fade | zoom

    @staticmethod
    def preset_of(name: str) -> "VideoConfig":
        if name == "preview":
            return VideoConfig(640, 360, 24.0, 28, "ultrafast", memory_mb=400)
        if name == "1080p":
            return VideoConfig(1920, 1080, 30.0, 18, "veryfast", memory_mb=1200)
        return VideoConfig()

    @staticmethod
    def from_dict(d: dict) -> "VideoConfig":
        """A quality preset, then the style's settings, then the options chosen by hand."""
        d = d or {}
        c = VideoConfig.preset_of(d.get("preset_name", "720p")) if d else VideoConfig()
        style = d.get("style") or "classic"
        if style not in STYLES:
            raise ValueError(f"unknown visual style {style!r} (styles: {', '.join(STYLES)})")
        for k, v in STYLES[style].items():
            setattr(c, k, v)
        c.style = style
        for k, v in d.items():
            if hasattr(c, k) and k not in ("preset_name",):
                setattr(c, k, v)
        if d.get("zoom_punch") is False:
            c.punch = 0.0
        for k, choices in STYLE_OPTIONS.items():
            if getattr(c, k) not in choices:
                raise ValueError(f"{k} must be one of {', '.join(choices)}")
        return c


# ── layouts ──────────────────────────────────────────────────────────────────

Rect = tuple[float, float, float, float]   # x, y, w, h in [0, 1]


def _grid(n: int, r: int, c: int, span: int = 1) -> Rect:
    return (c / n, r / n, span / n, span / n)


LAYOUT_CELLS: dict[str, dict[str, Rect]] = {
    "full": {"main": (0.0, 0.0, 1.0, 1.0)},
    "split2": {"left": (0.0, 0.0, 0.5, 1.0), "right": (0.5, 0.0, 0.5, 1.0)},
    "grid3": {
        "tl": _grid(3, 0, 0), "tc": _grid(3, 0, 1), "tr": _grid(3, 0, 2),
        "ml": _grid(3, 1, 0), "mc": _grid(3, 1, 1), "mr": _grid(3, 1, 2),
        "bl": _grid(3, 2, 0), "bc": _grid(3, 2, 1), "br": _grid(3, 2, 2),
    },
    "grid4": {f"c{r}{c}": _grid(4, r, c) for r in range(4) for c in range(4)},
}
LAYOUT_CELLS["grid4"]["center"] = (0.25, 0.25, 0.5, 0.5)
# The Chorus: the main phrase big in the middle (16:9), pitches along the top, drums along the bottom,
# pitch layers at the sides — the way remixers frame it.
LAYOUT_CELLS["main"] = {
    "main": (0.2, 0.2, 0.6, 0.6),
    **{f"t{i}": (0.2 * i, 0.0, 0.2, 0.2) for i in range(5)},
    **{f"b{i}": (0.2 * i, 0.8, 0.2, 0.2) for i in range(5)},
    "l": (0.0, 0.2, 0.2, 0.6), "r": (0.8, 0.2, 0.2, 0.6),
    "full": (0.0, 0.0, 1.0, 1.0),        # a section's opening hit, over everything, for an 8th
}
# Every pitch line has its own box along the top — the several pitches are seen playing together — with
# the bass at the end of the row; drums and quotes along the bottom.  A line is a track: a chord's voices
# (one pitch sample each) are one line, seen in one box.
MAIN_PITCH = {"pitch1": "t0", "pitch2": "t1", "pitch3": "t2", "pitch4": "t3"}
#: Where a line goes when its pitch's own box is another line's (main: the top row, then the sides).
MAIN_LINE_CELLS = ["t0", "t1", "t2", "t3", "r", "l"]
MAIN_FIXED = {"bass": "t4", "kick": "b0", "snare": "b1", "hat": "b2", "crash": "b3", "corner": "b3", "perc": "b3",
              "hat2": "b4", "quote": "b4", "side": "l"}

# Snake order around the 4x4 border then the centre, for cycling pitch clips.
GRID4_CYCLE = ["c00", "c01", "c02", "c03", "c13", "c23", "c33", "c32", "c31", "c30", "c20", "c10"]
GRID3_PITCH = {"pitch1": "mc", "pitch2": "ml", "pitch3": "mr", "pitch4": "tc"}
# Chord voices (one pitch sample per line) in the 4x4 grid's middle, one box each.
GRID4_VOICES = {"pitch2": "c11", "pitch3": "c12", "pitch4": "c21", "pitch1": "c22"}
GRID3_FIXED = {"kick": "bl", "snare": "br", "hat": "tl", "crash": "tr", "bass": "bc", "corner": "tr",
               "quote": "tc", "center": "mc", "hat2": "tl", "perc": "br"}
GRID3_LINE_CELLS = ["mc", "ml", "mr", "tc", "bc", "tl", "tr", "bl", "br"]
LINE_VISUALS = ("pitch_cycle", "voices")


def line_of(e: NoteEvent) -> tuple[int, str]:
    """The line an event belongs to: its track in its section (an Epicness's 4-bar blocks — "pitch",
    "pitch_1" … — are one line)."""
    return e.section, re.sub(r"_\d+$", "", e.track_id)


def line_cells(arr: Arrangement, events: list[NoteEvent]) -> dict[tuple[int, str], str]:
    """A box for each pitch line of each section (main and 3x3 layouts): the line's own pitch box when it
    is free, else the next free one — two lines never share a box, so none hides another."""
    firsts: dict[tuple[int, str], tuple] = {}
    used: dict[int, set] = {}
    for e in events:
        layout = arr.sections[e.section].layout
        if layout not in ("main", "grid3") or e.visual == "none":
            continue
        if e.visual in LINE_VISUALS:
            key = line_of(e)
            # Pitch lines take their boxes before held chords, then in the order they start.
            rank = (0 if e.visual == "pitch_cycle" else 1, e.t)
            if key not in firsts or rank < firsts[key][0]:
                firsts[key] = (rank, e.sample)
        else:
            c = cell_for(e, layout)
            if c is not None:
                used.setdefault(e.section, set()).add(c)
    out: dict[tuple[int, str], str] = {}
    for key, (_rank, sample) in sorted(firsts.items(), key=lambda kv: (kv[0][0], kv[1][0])):
        si = key[0]
        layout = arr.sections[si].layout
        taken = used.setdefault(si, set())
        if layout == "main" and sample.startswith("chorus"):
            out[key] = "main"                       # the main phrase's own clips stay in the middle
            continue
        own = (MAIN_PITCH if layout == "main" else GRID3_PITCH).get(sample)
        free = [c for c in (MAIN_LINE_CELLS if layout == "main" else GRID3_LINE_CELLS) if c not in taken]
        cell = own if own is not None and own not in taken else (free[0] if free else own)
        if cell is not None:
            out[key] = cell
            taken.add(cell)
    return out


def cell_for(e: NoteEvent, layout: str) -> Optional[str]:
    v = e.visual
    if v in ("none", "layer"):              # (a chord's voice is drawn over the chord, in its box)
        return None
    if layout == "full":
        if v in ("kick", "snare", "hat", "hat2", "perc", "crash", "bass", "corner", "side", "voices"):
            return None
        return "main"
    if v == "hit":
        return "full" if layout == "main" else GRID3_FIXED.get("crash") if layout == "grid3" else None
    if layout == "split2":
        if v == "main":
            return "left" if e.index % 2 == 0 else "right"
        if v == "madness":
            return "left" if e.sample.endswith("_a") or e.sample in ("pitch1", "word_a") else "right"
        if v in ("center", "center_late", "full_flash", "pitch_cycle"):
            return "left" if e.index % 2 == 0 else "right"
        return None
    if layout == "grid3":
        if v == "main":
            return "mc"
        if v in ("pitch_cycle", "voices"):
            return GRID3_PITCH.get(e.sample, "mc")
        if v in ("full_flash", "center_late"):
            return "mc"
        if v == "madness":
            return "ml" if e.sample in ("word_a",) else "mr"
        return GRID3_FIXED.get(v)
    if layout == "main":
        if v in ("main", "center", "center_late", "full_flash", "madness"):
            return "main"
        if v in ("pitch_cycle", "voices"):
            return MAIN_PITCH.get(e.sample, "main" if e.sample.startswith("chorus") else "t2")
        return MAIN_FIXED.get(v)
    if layout == "grid4":
        if v == "pitch_cycle":
            return GRID4_CYCLE[e.index % len(GRID4_CYCLE)]
        if v == "voices":
            return GRID4_VOICES.get(e.sample)
        if v in ("main", "center", "full_flash", "center_late", "madness"):
            return "center"
        return {"kick": "c30", "snare": "c33", "hat": "c00", "crash": "c03", "bass": "c31", "corner": "c03"}.get(v)
    return None


FLIP_CYCLE = ["none", "h", "hv", "v"]


def flip_state(e: NoteEvent) -> str:
    if e.flip == "alternate":
        return "h" if e.index % 2 else "none"
    if e.flip == "rotate":
        return FLIP_CYCLE[e.index % 4]
    return "none"


def flip_for(e: NoteEvent, mode: str) -> str:
    """The flip of a clip: each track's own (auto), or one rule for every clip."""
    if mode == "auto":
        return flip_state(e)
    if mode == "none":
        return "none"
    if mode == "mirror":
        return "mirror"
    if mode == "alternate":
        return "h" if e.index % 2 else "none"
    return FLIP_CYCLE[e.index % 4]


def _apply_flip(frame: np.ndarray, state: str) -> np.ndarray:
    if state == "mirror":                       # the left half mirrored onto the right
        out = frame.copy()
        w = frame.shape[1]
        out[:, w - w // 2:] = frame[:, :w // 2][:, ::-1]
        return out
    if state == "h":
        return frame[:, ::-1]
    if state == "v":
        return frame[::-1]
    if state == "hv":
        return frame[::-1, ::-1]
    return frame


# ── background ───────────────────────────────────────────────────────────────


class BlurredSource:
    """The source video, blurred, playing behind the remix (read a second at a time)."""

    CHUNK_S = 1.0

    def __init__(self, source: str, w: int, h: int, fps: float, duration: float):
        self.source, self.w, self.h, self.fps = source, w, h, fps
        self.duration = max(duration, 1.0)
        self._chunk: Optional[int] = None
        self._frames: Optional[np.ndarray] = None

    def frame(self, t: float) -> Optional[np.ndarray]:
        ts = t % self.duration
        c = int(ts // self.CHUNK_S)
        if c != self._chunk:
            self._chunk = c
            self._frames = ff.read_blurred(self.source, c * self.CHUNK_S, self.CHUNK_S + 1.0 / self.fps, self.fps,
                                           self.w, self.h)
        if self._frames is None or self._frames.shape[0] == 0:
            return None
        i = min(int((ts - c * self.CHUNK_S) * self.fps), self._frames.shape[0] - 1)
        return self._frames[i]


# ── clip cache ───────────────────────────────────────────────────────────────


class ClipCache:
    """Decoded frames per (sample, size, 1-second chunk), LRU-bounded in memory."""

    CHUNK_S = 1.0

    def __init__(self, source: str, bank: SampleBank, fps: float, memory_mb: int, has_video: bool):
        self.source = source
        self.bank = bank
        self.fps = fps
        self.limit = memory_mb * 1024 * 1024
        self.used = 0
        self.has_video = has_video
        self._lru: "OrderedDict[tuple, np.ndarray]" = OrderedDict()

    def _load(self, sid: str, w: int, h: int, chunk: int) -> np.ndarray:
        s = self.bank.get(sid)
        if s is None:
            return np.zeros((1, h, w, 3), dtype=np.uint8)
        if not self.has_video:
            return _audio_only_card(sid, s.label, w, h)
        src_len = max(1.0 / self.fps, s.src_end - s.src_start)
        a = s.src_start + chunk * self.CHUNK_S
        dur = min(self.CHUNK_S, src_len - chunk * self.CHUNK_S)
        if dur <= 0:
            return np.zeros((0, h, w, 3), dtype=np.uint8)
        return ff.read_frames(self.source, a, dur + 0.5 / self.fps, self.fps, w, h, "cover")

    def frame(self, sid: str, w: int, h: int, t_src: float) -> Optional[np.ndarray]:
        """Frame at t_src seconds into the sample's source clip (held on the last frame)."""
        s = self.bank.get(sid)
        if s is None:
            return None
        src_len = max(1.0 / self.fps, s.src_end - s.src_start)
        t_src = min(max(t_src, 0.0), max(src_len - 1.0 / self.fps, 0.0))
        chunk = int(t_src // self.CHUNK_S)
        key = (sid, w, h, chunk)
        frames = self._lru.get(key)
        if frames is None:
            frames = self._load(sid, w, h, chunk)
            if frames.shape[0] == 0 and chunk > 0:
                return self.frame(sid, w, h, chunk * self.CHUNK_S - 1.0 / self.fps)
            self._lru[key] = frames
            self.used += frames.nbytes
            while self.used > self.limit and len(self._lru) > 1:
                _, old = self._lru.popitem(last=False)
                self.used -= old.nbytes
        else:
            self._lru.move_to_end(key)
        if frames.shape[0] == 0:
            return None
        idx = int((t_src - chunk * self.CHUNK_S) * self.fps)
        return frames[min(idx, frames.shape[0] - 1)]


_CARD_COLORS = {
    "pitch": (200, 16, 46), "bass": (120, 30, 160), "kick": (231, 182, 44), "snare": (40, 170, 110),
    "clap": (40, 170, 110), "hat": (60, 140, 230), "crash": (230, 110, 30), "quote": (90, 90, 110),
    "phrase": (140, 60, 60), "word": (30, 120, 150), "syl": (170, 90, 40),
}


def _audio_only_card(sid: str, label: str, w: int, h: int) -> np.ndarray:
    """Audio-only sources have no clips: show a coloured card per sample instead."""
    key = next((k for k in _CARD_COLORS if sid.startswith(k)), "quote")
    base = np.array(_CARD_COLORS[key], dtype=np.float32)
    yy = np.linspace(0.55, 1.0, h, dtype=np.float32)[:, None, None]
    card = np.broadcast_to(base * yy, (h, w, 3)).astype(np.uint8).copy()
    t = Titles(w, h)
    if t.ok:
        spr = t.render(label.upper(), max(10, h // 7), 0.0, (255, 255, 255))
        if spr is not None:
            _blit_rgba(card, spr, w // 2, h // 2)
    return card[None]


# ── titles (optional, Pillow) ────────────────────────────────────────────────


class Titles:
    def __init__(self, width: int, height: int):
        self.ok = False
        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore
            self.Image, self.ImageDraw, self.ImageFont = Image, ImageDraw, ImageFont
            self.ok = True
        except Exception:
            return
        self.w, self.h = width, height
        self._cache: dict[tuple, np.ndarray] = {}

    def _font(self, size: int):
        for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Impact.ttf", "LiberationSans-Bold.ttf"):
            try:
                return self.ImageFont.truetype(name, size)
            except Exception:
                continue
        return self.ImageFont.load_default()

    def render(self, text: str, size: int, angle: float, color=(255, 230, 40)) -> Optional[np.ndarray]:
        """RGBA sprite of rotated text."""
        if not self.ok:
            return None
        key = (text, size, int(angle) % 360, color)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        font = self._font(size)
        img = self.Image.new("RGBA", (size * len(text), size * 2), (0, 0, 0, 0))
        d = self.ImageDraw.Draw(img)
        d.text((size // 2, size // 3), text, font=font, fill=color + (255,), stroke_width=max(2, size // 12),
               stroke_fill=(0, 0, 0, 255))
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        img = img.rotate(angle, expand=True, resample=self.Image.BICUBIC)
        arr = np.asarray(img, dtype=np.uint8)
        if len(self._cache) > 400:
            self._cache.clear()
        self._cache[key] = arr
        return arr


def _blit_rgba(canvas: np.ndarray, sprite: np.ndarray, cx: int, cy: int) -> None:
    h, w = sprite.shape[:2]
    x0, y0 = cx - w // 2, cy - h // 2
    H, W = canvas.shape[:2]
    ax0, ay0 = max(0, x0), max(0, y0)
    ax1, ay1 = min(W, x0 + w), min(H, y0 + h)
    if ax1 <= ax0 or ay1 <= ay0:
        return
    sp = sprite[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0]
    alpha = sp[..., 3:4].astype(np.float32) / 255.0
    region = canvas[ay0:ay1, ax0:ax1].astype(np.float32)
    canvas[ay0:ay1, ax0:ax1] = (region * (1 - alpha) + sp[..., :3].astype(np.float32) * alpha).astype(np.uint8)


# ── style effects ────────────────────────────────────────────────────────────

#: Border colours by part: the phrase gold, pitches red, bass purple, drums cyan, quotes white.
PART_COLORS = {"phrase": (231, 182, 44), "pitch": (235, 45, 75), "bass": (150, 70, 215), "drums": (40, 195, 235),
               "quote": (240, 240, 240)}


def part_of(e: NoteEvent) -> str:
    v = e.visual
    if v in ("main", "madness") or e.sample.startswith(("chorus", "word", "phrase", "syl")):
        return "phrase"
    if v in ("kick", "snare", "hat", "hat2", "perc", "crash", "corner", "hit"):
        return "drums"
    if v == "bass" or e.sample == "bass":
        return "bass"
    if v in ("center", "center_late") or e.sample.startswith("quote"):
        return "quote"
    return "pitch"


def _hex_rgb(text: str) -> Optional[tuple[int, int, int]]:
    t = text.strip().lstrip("#")
    if len(t) != 6:
        return None
    try:
        return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
    except ValueError:
        return None


def _resize_nn(fr: np.ndarray, w: int, h: int) -> np.ndarray:
    ys = np.minimum((np.arange(h) * fr.shape[0]) // max(h, 1), fr.shape[0] - 1)
    xs = np.minimum((np.arange(w) * fr.shape[1]) // max(w, 1), fr.shape[1] - 1)
    return fr[ys][:, xs]


def _hue_matrix(deg: float) -> np.ndarray:
    """RGB hue rotation (luma kept)."""
    a = math.radians(deg)
    c, s_ = math.cos(a), math.sin(a)
    return np.array([
        [0.213 + c * 0.787 - s_ * 0.213, 0.715 - c * 0.715 - s_ * 0.715, 0.072 - c * 0.072 + s_ * 0.928],
        [0.213 - c * 0.213 + s_ * 0.143, 0.715 + c * 0.285 + s_ * 0.140, 0.072 - c * 0.072 - s_ * 0.283],
        [0.213 - c * 0.213 - s_ * 0.787, 0.715 - c * 0.715 + s_ * 0.715, 0.072 + c * 0.928 + s_ * 0.072],
    ], dtype=np.float32)


#: Colour swaps for the hue cycle: every hit of a clip gets the next one (cheap: channels only).
HUE_ORDERS = ([0, 1, 2], [1, 2, 0], [2, 0, 1], [0, 2, 1], [2, 1, 0], [1, 0, 2])


def cell_fx(fr: np.ndarray, e: NoteEvent, cfg: "VideoConfig", fresh: bool) -> np.ndarray:
    """A clip's colour effect."""
    if cfg.color_fx == "hue_cycle" and part_of(e) != "phrase":
        order = HUE_ORDERS[e.index % len(HUE_ORDERS)]
        if order != [0, 1, 2]:
            fr = fr[..., order]
    elif cfg.color_fx == "invert_crash" and fresh and e.visual in ("crash", "hit"):
        fr = 255 - fr
    elif cfg.color_fx == "mono" and part_of(e) != "phrase":
        g = (fr[..., 0].astype(np.uint16) * 77 + fr[..., 1].astype(np.uint16) * 150 + fr[..., 2] * 29) >> 8
        fr = np.repeat(g.astype(np.uint8)[..., None], 3, axis=2)
    return fr


def anim_rect(x0: int, y0: int, cw: int, ch: int, e: NoteEvent, age: float, cfg: "VideoConfig",
              W: int, H: int) -> tuple[int, int, int, int]:
    """Where a clip is drawn while its hit animation plays (pop: it grows, slide: it slides in)."""
    if cfg.hit_anim == "pop" and age < 0.12:
        k = 1.0 + 0.16 * (1.0 - age / 0.12) ** 2
        nw, nh = int(cw * k) // 2 * 2, int(ch * k) // 2 * 2
        return x0 - (nw - cw) // 2, y0 - (nh - ch) // 2, nw, nh
    if cfg.hit_anim == "slide" and age < 0.1:
        d = int((1.0 - age / 0.1) ** 2 * 0.35 * cw) * (1 if e.index % 2 else -1)
        return x0 + d, y0, cw, ch
    return x0, y0, cw, ch


def blit(canvas: np.ndarray, fr: np.ndarray, x0: int, y0: int) -> None:
    """Paste a frame, clipped to the canvas."""
    H, W = canvas.shape[:2]
    h, w = fr.shape[:2]
    ax0, ay0, ax1, ay1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if ax1 > ax0 and ay1 > ay0:
        canvas[ay0:ay1, ax0:ax1] = fr[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0]


_GLOW = 10
#: Glow strength from the box edge outwards (px 0 … 9).
_GLOW_ALPHA = np.array([0.9, 0.75, 0.6, 0.47, 0.36, 0.27, 0.19, 0.13, 0.08, 0.04], dtype=np.float32)


def draw_border(canvas: np.ndarray, x0: int, y0: int, w: int, h: int, color: tuple, kind: str,
                bright: float = 1.0) -> None:
    """A 2 px line around a box, or (glow) a line fading out over 10 px — four strips per box."""
    H, W = canvas.shape[:2]
    col = np.array(color, dtype=np.float32) * bright
    if kind == "glow":
        g = _GLOW
        strips = (  # (y slice, x slice, alpha along y or x)
            (slice(y0 - g, y0), slice(x0 - g, x0 + w + g), _GLOW_ALPHA[::-1][:, None, None]),
            (slice(y0 + h, y0 + h + g), slice(x0 - g, x0 + w + g), _GLOW_ALPHA[:, None, None]),
            (slice(y0, y0 + h), slice(x0 - g, x0), _GLOW_ALPHA[::-1][None, :, None]),
            (slice(y0, y0 + h), slice(x0 + w, x0 + w + g), _GLOW_ALPHA[None, :, None]),
        )
        for ys, xs, alpha in strips:
            a0, a1 = max(0, ys.start), min(H, ys.stop)
            b0, b1 = max(0, xs.start), min(W, xs.stop)
            if a1 <= a0 or b1 <= b0:
                continue
            al = alpha
            if al.shape[0] > 1:
                al = al[a0 - ys.start:a1 - ys.start]
            if al.shape[1] > 1:
                al = al[:, b0 - xs.start:b1 - xs.start]
            region = canvas[a0:a1, b0:b1].astype(np.float32)
            canvas[a0:a1, b0:b1] = (region + (col - region) * al * bright).astype(np.uint8)
    c = col.astype(np.uint8)
    for ys, xs in ((slice(y0, y0 + 2), slice(x0, x0 + w)), (slice(y0 + h - 2, y0 + h), slice(x0, x0 + w)),
                   (slice(y0, y0 + h), slice(x0, x0 + 2)), (slice(y0, y0 + h), slice(x0 + w - 2, x0 + w))):
        a0, a1, b0, b1 = max(0, ys.start), min(H, ys.stop), max(0, xs.start), min(W, xs.stop)
        if a1 > a0 and b1 > b0:
            canvas[a0:a1, b0:b1] = c


class PostFX:
    """Whole-frame effects, precomputed once: tint, vignette and scanlines are one multiply; grain comes
    from a few noise tiles; punch, shake, RGB split and part transitions follow the music."""

    def __init__(self, cfg: "VideoConfig", W: int, H: int):
        self.cfg, self.W, self.H = cfg, W, H
        mul = np.ones((H, W, 3), dtype=np.float32)
        if cfg.vignette > 0:
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
            mul *= (1.0 - cfg.vignette * np.clip(r, 0, 1) ** 2 * 1.3).clip(0.15, 1.0)[..., None]
        if cfg.scanlines > 0:
            rows = np.ones(H, dtype=np.float32)
            rows[1::3] = 1.0 - 0.6 * cfg.scanlines
            mul *= rows[:, None, None]
        tints = {"warm": (1.08, 1.0, 0.86), "cold": (0.88, 0.98, 1.1), "vivid": (1.0, 1.0, 1.0)}
        if cfg.tint in tints:
            mul *= np.array(tints[cfg.tint], dtype=np.float32)
        self.mul = None if np.allclose(mul, 1.0) else (mul * 256).astype(np.uint16)
        self.noise = None
        if cfg.grain > 0:
            rng = np.random.RandomState(7)
            amp = 40 * cfg.grain
            self.noise = [(rng.randn(H, W, 1) * amp).astype(np.int16) for _ in range(4)]
        self.lb = int(round(cfg.letterbox * H)) if cfg.letterbox > 0 else 0

    def apply(self, canvas: np.ndarray, k: int, t: float, kick_dt: float, crash_dt: float,
              section_dt: float) -> np.ndarray:
        cfg = self.cfg
        if cfg.transition == "zoom" and 0 <= section_dt < 0.22:
            canvas = _zoom(canvas, 1.0 + 0.12 * (1.0 - section_dt / 0.22))
        if cfg.shake > 0:
            dt = min(kick_dt, crash_dt * 0.6)
            if 0 <= dt < 0.14:
                amp = cfg.shake * 0.018 * self.W * (1.0 - dt / 0.14)
                rng = np.random.RandomState(int(t * 1000) % 100000)
                dx, dy = (int(v) for v in rng.uniform(-amp, amp, 2))
                canvas = np.roll(canvas, (dy, dx), axis=(0, 1))
        if cfg.rgb_split > 0 and 0 <= kick_dt < 0.1:
            d = max(1, int(cfg.rgb_split * 0.012 * self.W * (1.0 - kick_dt / 0.1)))
            out = canvas.copy()
            out[:, d:, 0] = canvas[:, :-d, 0]
            out[:, :-d, 2] = canvas[:, d:, 2]
            canvas = out
        if cfg.tint == "sepia":
            g = (canvas[..., 0].astype(np.uint16) * 77 + canvas[..., 1].astype(np.uint16) * 150
                 + canvas[..., 2] * 29) >> 8
            canvas = np.stack([np.minimum(g * 275 >> 8, 255), np.minimum(g * 225 >> 8, 255), g * 170 >> 8],
                              axis=2).astype(np.uint8)
        elif cfg.tint == "vivid":
            c16 = canvas.astype(np.int16)
            g = c16.mean(axis=2, keepdims=True).astype(np.int16)
            canvas = np.clip(g + (c16 - g) * 3 // 2, 0, 255).astype(np.uint8)
        if self.mul is not None:
            canvas = np.minimum((canvas.astype(np.uint16) * self.mul) >> 8, 255).astype(np.uint8)
        if self.noise is not None:
            canvas = np.clip(canvas.astype(np.int16) + self.noise[k % len(self.noise)], 0, 255).astype(np.uint8)
        if cfg.transition == "flash" and 0 <= section_dt < 0.18:
            a = int(140 * (1.0 - section_dt / 0.18))
            canvas = (canvas.astype(np.uint16) + ((255 - canvas.astype(np.uint16)) * a >> 8)).astype(np.uint8)
        elif cfg.transition == "fade" and 0 <= section_dt < 0.2:
            canvas = (canvas.astype(np.uint16) * int(256 * section_dt / 0.2) >> 8).astype(np.uint8)
        if self.lb:
            canvas[:self.lb] = 0
            canvas[-self.lb:] = 0
        return canvas


def _gradient(W: int, H: int) -> np.ndarray:
    """A dark red-to-black backdrop."""
    yy = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    top = np.array((70, 8, 18), dtype=np.float32)
    return np.broadcast_to(top * (1.0 - yy) + 8 * yy, (H, W, 3)).astype(np.uint8).copy()


def _mirror_bg(bg: np.ndarray) -> np.ndarray:
    """Kaleidoscope: the frame's left half mirrored, then the top half mirrored down."""
    out = bg.copy()
    h, w = out.shape[:2]
    out[:, w - w // 2:] = out[:, :w // 2][:, ::-1]
    out[h - h // 2:] = out[:h // 2][::-1]
    return out


# ── compositor ───────────────────────────────────────────────────────────────


def _px(rect: Rect, W: int, H: int, gap: int) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    x0 = int(round(x * W)) + (gap // 2 if x > 0 else 0)
    y0 = int(round(y * H)) + (gap // 2 if y > 0 else 0)
    x1 = int(round((x + w) * W)) - (gap // 2 if x + w < 1 else 0)
    y1 = int(round((y + h) * H)) - (gap // 2 if y + h < 1 else 0)
    return x0, y0, max(2, (x1 - x0) // 2 * 2), max(2, (y1 - y0) // 2 * 2)


#: A chord's voices are drawn as layers in the chord's box, each this much smaller than the one under it,
#: all from the box's top-left corner — the root the full box, the third over it, the fifth over that.
LAYER_STEP = 0.05


def layer_rect(x0: int, y0: int, w: int, h: int, layer: int) -> tuple[int, int, int, int]:
    """Where a chord's nth voice (0 = the chord's own picture) is drawn inside its box (x0, y0, w, h)."""
    k = max(0.5, 1.0 - LAYER_STEP * layer)
    return x0, y0, max(2, int(w * k) // 2 * 2), max(2, int(h * k) // 2 * 2)


def _layer_shadow(canvas: np.ndarray, x0: int, y0: int, w: int, h: int, depth: int = 3) -> None:
    """A thin shadow along a layer's right and bottom edges, so the stacked layers read as cards."""
    H, W = canvas.shape[:2]
    for ys, xs in ((slice(y0 + 2, y0 + h + depth), slice(x0 + w, x0 + w + depth)),
                   (slice(y0 + h, y0 + h + depth), slice(x0 + 2, x0 + w))):
        a0, a1, b0, b1 = max(0, ys.start), min(H, ys.stop), max(0, xs.start), min(W, xs.stop)
        if a1 > a0 and b1 > b0:
            canvas[a0:a1, b0:b1] = (canvas[a0:a1, b0:b1].astype(np.uint16) * 90 >> 8).astype(np.uint8)


def encode_png(rgb: np.ndarray) -> bytes:
    """An RGB frame as PNG bytes (zlib only: no ffmpeg or Pillow needed, so phones can show previews too)."""
    import struct
    import zlib
    h, w = rgb.shape[:2]
    rows = np.ascontiguousarray(rgb, dtype=np.uint8).reshape(h, w * 3)
    raw = np.concatenate([np.zeros((h, 1), dtype=np.uint8), rows], axis=1).tobytes()     # filter 0 per row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


class Compositor:
    """The remix's picture: every part's boxes with the clips playing in them.  :meth:`next_frame` draws the
    frames in order (the video); :meth:`still` draws any one moment (a preview of the look)."""

    def __init__(self, source: str, arr: Arrangement, events: list[NoteEvent], bank: SampleBank,
                 cfg: Optional[VideoConfig] = None, duration: Optional[float] = None,
                 cache: Optional["ClipCache"] = None, backdrop: Optional["BlurredSource"] = None):
        cfg = cfg or VideoConfig()
        self.cfg, self.arr, self.bank = cfg, arr, bank
        self.W, self.H, self.fps = W, H, fps = cfg.width, cfg.height, cfg.fps
        info = ff.probe(source)
        memory_mb = cfg.memory_mb
        if os.environ.get("SPARTAGEN_MEMORY_MB", "").isdigit():      # a cap for small devices (the Android app)
            memory_mb = min(memory_mb, int(os.environ["SPARTAGEN_MEMORY_MB"]))
        self.cache = cache if cache is not None else ClipCache(source, bank, fps, memory_mb, info.has_video)
        self.starts = arr.section_starts()
        self.total = duration if duration is not None else arr.duration + 0.5
        self.titles = Titles(W, H) if cfg.titles else None

        # Visible events with their cell, sorted by start.  Each pitch line has a box of its own; a chord's
        # other voices are layers over the chord's picture, in its box.
        lines = line_cells(arr, events)
        self.vis: list[tuple] = []
        self.layers: dict[tuple, list[tuple]] = {}
        for e in events:
            s = bank.get(e.sample)
            if s is None:
                continue
            length = max(audible_length(e, s), cfg.min_hold_s)
            if e.choke:
                length = min(length, max(e.max_len, 1.0 / fps))
            if e.visual == "layer":
                self.layers.setdefault((e.section, e.track_id, round(e.t, 6)), []).append(
                    (e.t, e.t + length, e, s.video_rate))
                continue
            sec = arr.sections[e.section]
            cell = (lines.get(line_of(e)) if e.visual in LINE_VISUALS else None) or cell_for(e, sec.layout)
            if cell is None:
                continue
            if cell == "full":
                length = min(length, 2 * arr.step_s)      # the opening hit: an 8th, then the section's frame
            self.vis.append((e.t, e.t + length, cell, e, s.video_rate))
        self.vis.sort(key=lambda z: z[0])
        for lst in self.layers.values():
            lst.sort(key=lambda z: z[2].layer)
        self._vis_starts = [a[0] for a in self.vis]
        self.kicks = sorted(e.t for e in events if e.sample == "kick")
        self.crashes = sorted(e.t for e in events if e.sample == "crash")

        self.bg_val = 0 if cfg.background == "black" else 14
        self.blur_bg = (backdrop or BlurredSource(source, W, H, fps, info.duration)) \
            if (cfg.background in ("blur", "mirror") and info.has_video) else None
        self.gradient = _gradient(W, H) if cfg.background == "gradient" or (
            cfg.background == "mirror" and self.blur_bg is None) else None
        self.post = PostFX(cfg, W, H)
        self.user_color = _hex_rgb(cfg.border_color) if cfg.border_color != "auto" else None
        # (drawing in order)
        self._ptr = 0
        self._active: list[tuple] = []
        self._last: dict[tuple[int, str], tuple] = {}

    @property
    def n_frames(self) -> int:
        return int(math.ceil(self.total * self.fps))

    def section_at(self, t: float) -> int:
        return min(max(0, int(np.searchsorted(self.starts, t, side="right")) - 1), len(self.arr.sections) - 1)

    def next_frame(self, k: int) -> np.ndarray:
        """Frame k of the video (call in order: 0, 1, 2 …)."""
        t = k / self.fps
        while self._ptr < len(self.vis) and self.vis[self._ptr][0] <= t:
            self._active.append(self.vis[self._ptr])
            self._ptr += 1
        self._active = [a for a in self._active if a[1] > t - 2.0 / self.fps]
        return self._draw(t, k, self._active, self._last, remember=True)

    def still(self, t: float) -> np.ndarray:
        """The picture at t seconds, drawn on its own (what the video shows then)."""
        t = min(max(0.0, t), max(0.0, self.total - 1.0 / self.fps))
        si = self.section_at(t)
        upto = int(np.searchsorted(self._vis_starts, t, side="right"))
        started = self.vis[:upto]
        active = [a for a in started if a[1] > t - 2.0 / self.fps]
        last: dict[tuple[int, str], tuple] = {}
        for a in started:                      # what each box showed last in this part (held, dimmed)
            if a[3].section == si:
                prev = last.get((si, a[2]))
                if prev is None or a[0] >= prev[0]:
                    last[(si, a[2])] = a
        return self._draw(t, int(round(t * self.fps)), active, last, remember=False)

    def _since(self, times: list, t: float) -> float:
        i = int(np.searchsorted(times, t, side="right")) - 1
        return t - times[i] if i >= 0 else 1e9

    def _clip(self, e: NoteEvent, t0: float, t1: float, rate: float, w: int, h: int, t: float,
              dim: float) -> Optional[np.ndarray]:
        """The clip of a visible event (shown t0 … t1) at time t, flipped and coloured, sized w×h."""
        cfg = self.cfg
        age = t - t0
        t_src = age * rate if dim == 1.0 else (t1 - t0) * rate
        fr = self.cache.frame(e.sample, w, h, t_src)
        if fr is None:
            return None
        fr = _apply_flip(fr, flip_for(e, cfg.flip_mode))
        fresh = dim == 1.0 and age < 1.6 / self.fps
        if cfg.color_fx != "none":
            fr = cell_fx(fr, e, cfg, fresh)
        if cfg.flash and fresh:
            fr = np.minimum(fr.astype(np.uint16) * 3 // 2 + 20, 255).astype(np.uint8)
        elif dim != 1.0:
            fr = (fr.astype(np.uint16) * int(dim * 256) >> 8).astype(np.uint8)
        return fr[:h, :w]

    def _draw(self, t: float, k: int, active: list[tuple], last_in_cell: dict, remember: bool) -> np.ndarray:
        cfg, arr, W, H = self.cfg, self.arr, self.W, self.H
        si = self.section_at(t)
        sec = arr.sections[si]
        layout = sec.layout
        cells = LAYOUT_CELLS[layout]
        canvas = np.full((H, W, 3), self.bg_val, dtype=np.uint8)
        if self.blur_bg is not None and sec.kind not in cfg.blink_sections:
            # Our source, blurred and dimmed, behind the boxes (the blink sections stay black
            # between their hits — silence in between).
            bg = self.blur_bg.frame(t)
            if bg is not None:
                if cfg.background == "mirror":
                    bg = _mirror_bg(bg)
                canvas = (bg.astype(np.uint16) * int(cfg.background_dim * 256) >> 8).astype(np.uint8)
        elif self.gradient is not None and sec.kind not in cfg.blink_sections:
            canvas = self.gradient.copy()
        elif layout == "full" or self.bg_val == 0:
            canvas[:] = 0
        # Latest event per cell wins.
        current: dict[str, tuple] = {}
        for a in active:
            if a[0] <= t < a[1] and arr.sections[a[3].section].layout == layout:
                prev = current.get(a[2])
                if prev is None or a[0] >= prev[0]:
                    current[a[2]] = a
        on_top: list[tuple] = []            # popping clips go over their neighbours
        borders: list[tuple] = []
        shadows: list[tuple] = []
        for cell_name in cells:
            a = current.get(cell_name)
            dim = 1.0
            if a is None:
                if not cfg.hold_last or sec.kind in cfg.blink_sections or cell_name == "full":
                    continue
                a = last_in_cell.get((si, cell_name))
                if a is None:
                    continue
                dim = cfg.hold_dim if layout != "full" else 0.55
            elif remember:
                last_in_cell[(si, cell_name)] = a
            x0, y0, cw, ch = _px(cells[cell_name], W, H, cfg.gap if layout != "full" else 0)
            e = a[3]
            fr = self._clip(e, a[0], a[1], a[4], cw, ch, t, dim)
            if fr is None:
                continue
            ax, ay, aw, ah = (x0, y0, cw, ch)
            if dim == 1.0 and cfg.hit_anim != "none" and layout != "full":
                ax, ay, aw, ah = anim_rect(x0, y0, cw, ch, e, t - a[0], cfg, W, H)
                if (aw, ah) != (cw, ch):
                    fr = _resize_nn(fr, aw, ah)
            moved = (ax, ay, aw, ah) != (x0, y0, cw, ch)
            if moved:
                on_top.append((fr, ax, ay))
            else:
                canvas[y0:y0 + ch, x0:x0 + cw] = fr
            color = self.user_color or PART_COLORS[part_of(e)]
            if cfg.border != "none" and layout != "full":
                borders.append((ax, ay, aw, ah, color, 1.0 if dim == 1.0 else 0.45))
            # A chord: its other voices, each a layer over the one under it (while it sounds).
            for lay in self.layers.get((e.section, e.track_id, round(e.t, 6)), ()):
                if dim == 1.0 and not (lay[0] <= t < lay[1]):
                    continue
                lx, ly, lw, lh = layer_rect(ax, ay, aw, ah, lay[2].layer)
                lfr = self._clip(lay[2], lay[0], lay[1], lay[3], lw, lh, t, dim)
                if lfr is None:
                    continue
                if moved:
                    on_top.append((lfr, lx, ly))
                    shadows.append((lx, ly, lw, lh))
                else:
                    blit(canvas, lfr, lx, ly)
                    _layer_shadow(canvas, lx, ly, lw, lh)
                if cfg.border != "none" and layout != "full":
                    borders.append((lx, ly, lw, lh, color, 1.0 if dim == 1.0 else 0.45))
        for fr, ax, ay in on_top:
            blit(canvas, fr, ax, ay)
        for sx, sy, sw, sh in shadows:
            _layer_shadow(canvas, sx, sy, sw, sh)
        for bx, by, bw, bh, color, bright in borders:
            draw_border(canvas, bx, by, bw, bh, color, cfg.border, bright)
        # Kick punch: a short zoom bounce on every kick.
        kick_dt = self._since(self.kicks, t)
        if cfg.punch > 0 and 0 <= kick_dt < 0.12 and layout != "full":
            canvas = _zoom(canvas, 1.0 + cfg.punch * (1.0 - kick_dt / 0.12))
        canvas = self.post.apply(canvas, k, t, kick_dt, self._since(self.crashes, t), t - self.starts[si])
        if self.titles is not None and self.titles.ok:
            _draw_titles(canvas, self.titles, arr, si, t - self.starts[si], W, H, cfg.intro_title)
        return canvas


def render_video(
    out_path: str,
    source: str,
    arr: Arrangement,
    events: list[NoteEvent],
    bank: SampleBank,
    audio_wav: str,
    cfg: Optional[VideoConfig] = None,
    progress: Progress = None,
    duration: Optional[float] = None,
) -> str:
    comp = Compositor(source, arr, events, bank, cfg, duration)
    n = comp.n_frames
    with ff.VideoWriter(out_path, comp.W, comp.H, comp.fps, audio_path=audio_wav, crf=comp.cfg.crf,
                        preset=comp.cfg.preset) as vw:
        for k in range(n):
            vw.write(comp.next_frame(k))
            if progress and k % 48 == 0:
                progress(k / n, "rendering video")
    if progress:
        progress(1.0, "video done")
    return out_path


def _zoom(canvas: np.ndarray, z: float) -> np.ndarray:
    H, W = canvas.shape[:2]
    ch, cw = int(H / z), int(W / z)
    y0, x0 = (H - ch) // 2, (W - cw) // 2
    ys = (np.arange(H) * ch // H + y0)
    xs = (np.arange(W) * cw // W + x0)
    return canvas[ys][:, xs]


def _draw_titles(canvas: np.ndarray, titles: Titles, arr: Arrangement, si: int, t_in: float, W: int, H: int,
                 intro_title: bool = False) -> None:
    sec = arr.sections[si]
    if sec.kind == "epicness" and t_in < arr.bar_s * min(sec.bars, 2):
        # "OMG TEH EPICNESS" spinning text (Sparta Remix Wiki) over the Epicness's first two bars, in
        # time with the base: one turn per bar, a little bigger on every beat.
        angle = (t_in / arr.bar_s * 360.0) % 360.0
        beat = (t_in / (arr.bar_s / 4)) % 1.0
        size = int(max(24, H // 10) * (1.0 + 0.12 * max(0.0, 1.0 - beat * 4.0)))
        spr = titles.render("OMG TEH EPICNESS", size, angle)
        if spr is not None:
            _blit_rgba(canvas, spr, W // 2, H // 2)
    elif intro_title and sec.kind == "intro" and si == 0 and t_in < 2.5:
        spr = titles.render(arr.title, max(18, H // 16), 0.0, (255, 255, 255))
        if spr is not None:
            _blit_rgba(canvas, spr, W // 2, int(H * 0.88))
