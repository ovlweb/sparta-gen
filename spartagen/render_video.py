"""Sparta Remix visuals: every note shows its sample's video clip, in sync.

Layouts per section follow what remixers build in Vegas: fullscreen hits
(Intro, DunDunDenDen — black between the "DUN"s), a left/right split for the
Madness call & response, the Chorus with the main phrase big in the middle,
pitches along the top and drums along the bottom, and 3x3 / 4x4 grids for the
Epicness and Awesomeness.  Clips flip on every hit (alternate or
rotate), flash on the attack, and the frame punches with the kick.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from . import ffmpeg as ff
from .arrangement import Arrangement, NoteEvent
from .render_audio import audible_length
from .samples import SampleBank

Progress = Optional[Callable[[float, str], None]]


@dataclass
class VideoConfig:
    width: int = 1280
    height: int = 720
    fps: float = 30.0
    crf: int = 20
    preset: str = "veryfast"
    background: str = "dark"          # black | dark
    flash: bool = True
    zoom_punch: bool = True
    gap: int = 4
    min_hold_s: float = 0.09          # drums/short hits stay visible at least this long
    hold_last: bool = True            # keep the last clip of a cell (dimmed) instead of blinking to black
    hold_dim: float = 0.3
    blink_sections: tuple = ("dundundenden", "intro_hits", "ending")  # these stay black between hits
    titles: bool = True               # spinning "OMG TEH EPICNESS" etc. (needs Pillow)
    memory_mb: int = 700

    @staticmethod
    def preset_of(name: str) -> "VideoConfig":
        if name == "preview":
            return VideoConfig(640, 360, 24.0, 28, "ultrafast", memory_mb=400)
        if name == "1080p":
            return VideoConfig(1920, 1080, 30.0, 18, "veryfast", memory_mb=1200)
        return VideoConfig()

    @staticmethod
    def from_dict(d: dict) -> "VideoConfig":
        c = VideoConfig.preset_of(d.get("preset_name", "720p")) if d else VideoConfig()
        for k, v in (d or {}).items():
            if hasattr(c, k):
                setattr(c, k, v)
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
}
# Every pitch has its own box along the top — the several pitches are seen playing together — with the
# bass at the end of the row; drums and quotes along the bottom.
MAIN_PITCH = {"pitch1": "t0", "pitch2": "t1", "pitch3": "t2", "pitch4": "t3"}
MAIN_FIXED = {"bass": "t4", "kick": "b0", "snare": "b1", "hat": "b2", "crash": "b3", "corner": "b3", "quote": "b4",
              "side": "l"}

# Snake order around the 4x4 border then the centre, for cycling pitch clips.
GRID4_CYCLE = ["c00", "c01", "c02", "c03", "c13", "c23", "c33", "c32", "c31", "c30", "c20", "c10"]
GRID3_PITCH = {"pitch1": "mc", "pitch2": "ml", "pitch3": "mr", "pitch4": "tc"}
# Chord voices (one pitch sample per line) in the 4x4 grid's middle, one box each.
GRID4_VOICES = {"pitch2": "c11", "pitch3": "c12", "pitch4": "c21", "pitch1": "c22"}
GRID3_FIXED = {"kick": "bl", "snare": "br", "hat": "tl", "crash": "tr", "bass": "bc", "corner": "tr",
               "quote": "tc", "center": "mc"}


def cell_for(e: NoteEvent, layout: str) -> Optional[str]:
    v = e.visual
    if v == "none":
        return None
    if layout == "full":
        if v in ("kick", "snare", "hat", "crash", "bass", "corner", "side", "voices"):
            return None
        return "main"
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


def _apply_flip(frame: np.ndarray, state: str) -> np.ndarray:
    if state == "h":
        return frame[:, ::-1]
    if state == "v":
        return frame[::-1]
    if state == "hv":
        return frame[::-1, ::-1]
    return frame


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


# ── compositor ───────────────────────────────────────────────────────────────


def _px(rect: Rect, W: int, H: int, gap: int) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    x0 = int(round(x * W)) + (gap // 2 if x > 0 else 0)
    y0 = int(round(y * H)) + (gap // 2 if y > 0 else 0)
    x1 = int(round((x + w) * W)) - (gap // 2 if x + w < 1 else 0)
    y1 = int(round((y + h) * H)) - (gap // 2 if y + h < 1 else 0)
    return x0, y0, max(2, (x1 - x0) // 2 * 2), max(2, (y1 - y0) // 2 * 2)


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
    cfg = cfg or VideoConfig()
    W, H, fps = cfg.width, cfg.height, cfg.fps
    info = ff.probe(source)
    cache = ClipCache(source, bank, fps, cfg.memory_mb, info.has_video)
    starts = arr.section_starts()
    total = duration if duration is not None else arr.duration + 0.5
    n_frames = int(math.ceil(total * fps))
    titles = Titles(W, H) if cfg.titles else None

    # Visible events with their cell, sorted by start.
    vis = []
    for e in events:
        sec = arr.sections[e.section]
        cell = cell_for(e, sec.layout)
        if cell is None:
            continue
        s = bank.get(e.sample)
        if s is None:
            continue
        length = max(audible_length(e, s), cfg.min_hold_s)
        if e.choke:
            length = min(length, max(e.max_len, 1.0 / fps))
        vis.append((e.t, e.t + length, cell, e, s.video_rate))
    vis.sort(key=lambda z: z[0])
    kicks = [e.t for e in events if e.sample == "kick"]
    kicks.sort()

    bg_val = 0 if cfg.background == "black" else 14
    ptr = 0
    active: list[tuple] = []
    last_in_cell: dict[tuple[int, str], tuple] = {}
    kick_ptr = 0
    with ff.VideoWriter(out_path, W, H, fps, audio_path=audio_wav, crf=cfg.crf, preset=cfg.preset) as vw:
        for k in range(n_frames):
            t = k / fps
            si = max(0, np.searchsorted(starts, t, side="right") - 1)
            sec = arr.sections[min(si, len(arr.sections) - 1)]
            layout = sec.layout
            cells = LAYOUT_CELLS[layout]
            canvas = np.full((H, W, 3), bg_val, dtype=np.uint8)
            if layout == "full" or bg_val == 0:
                canvas[:] = 0
            while ptr < len(vis) and vis[ptr][0] <= t:
                active.append(vis[ptr])
                ptr += 1
            active = [a for a in active if a[1] > t - 2.0 / fps]
            # Latest event per cell wins.
            current: dict[str, tuple] = {}
            for a in active:
                if a[0] <= t < a[1] and arr.sections[a[3].section].layout == layout:
                    prev = current.get(a[2])
                    if prev is None or a[0] >= prev[0]:
                        current[a[2]] = a
            for cell_name in cells:
                a = current.get(cell_name)
                dim = 1.0
                if a is None:
                    if not cfg.hold_last or sec.kind in cfg.blink_sections:
                        continue
                    a = last_in_cell.get((si, cell_name))
                    if a is None:
                        continue
                    dim = cfg.hold_dim if layout != "full" else 0.55
                else:
                    last_in_cell[(si, cell_name)] = a
                x0, y0, cw, ch = _px(cells[cell_name], W, H, cfg.gap if layout != "full" else 0)
                e = a[3]
                t_src = (t - a[0]) * a[4] if dim == 1.0 else (a[1] - a[0]) * a[4]
                fr = cache.frame(e.sample, cw, ch, t_src)
                if fr is None:
                    continue
                fr = _apply_flip(fr, flip_state(e))
                if cfg.flash and dim == 1.0 and t - a[0] < 1.6 / fps:
                    fr = np.minimum(fr.astype(np.uint16) * 3 // 2 + 20, 255).astype(np.uint8)
                elif dim != 1.0:
                    fr = (fr.astype(np.uint16) * int(dim * 256) >> 8).astype(np.uint8)
                canvas[y0:y0 + ch, x0:x0 + cw] = fr[:ch, :cw]
            # Kick punch: a short zoom bounce on every kick.
            if cfg.zoom_punch and kicks:
                while kick_ptr + 1 < len(kicks) and kicks[kick_ptr + 1] <= t:
                    kick_ptr += 1
                dt = t - kicks[kick_ptr]
                if 0 <= dt < 0.12 and layout != "full":
                    z = 1.0 + 0.035 * (1.0 - dt / 0.12)
                    canvas = _zoom(canvas, z)
            if titles is not None and titles.ok:
                _draw_titles(canvas, titles, arr, si, t - starts[si], W, H)
            vw.write(canvas)
            if progress and k % 48 == 0:
                progress(k / n_frames, "rendering video")
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


def _draw_titles(canvas: np.ndarray, titles: Titles, arr: Arrangement, si: int, t_in: float, W: int, H: int) -> None:
    sec = arr.sections[si]
    if sec.kind == "epicness" and t_in < arr.bar_s * min(sec.bars, 8) / 3.0:
        # "OMG TEH EPICNESS" spinning text over the first third of the Epicness (Sparta Remix Wiki).
        angle = (t_in * 360.0) % 360.0
        spr = titles.render("OMG TEH EPICNESS", max(24, H // 10), angle)
        if spr is not None:
            _blit_rgba(canvas, spr, W // 2, H // 2)
    elif sec.kind == "intro" and si == 0 and t_in < 2.5:
        spr = titles.render(arr.title, max(18, H // 16), 0.0, (255, 255, 255))
        if spr is not None:
            _blit_rgba(canvas, spr, W // 2, int(H * 0.88))
