"""Draw SpartaGen's icon — the blue and white Spartan helmet — for every platform.

    pip install cairosvg pillow
    python scripts/make_icons.py

The helmet is drawn here, in a 256×256 box; everything else is made from it:

    packaging/icon.svg, spartagen/gui/static/icon.svg   the icon (and the classic web page's)
    packaging/icon.png, icon.ico, icon.icns             the engine's icons
    app/assets/icon.png                                  the app's logo (splash, About, Linux window and menu)
    app/macos/Runner/Assets.xcassets/AppIcon.appiconset  macOS
    app/ios/Runner/Assets.xcassets/AppIcon.appiconset    iOS (square and opaque: iOS rounds the corners)
    app/windows/runner/resources/app_icon.ico            Windows
    app/android/app/src/main/res/                        Android: the adaptive icon (vectors), the themed
                                                         (monochrome) icon, the notification icon, and PNGs
                                                         for launchers without adaptive icons
"""

from __future__ import annotations

import io
import json
import math
import os
import sys

try:
    import cairosvg
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:  # pragma: no cover - a developer tool
    sys.exit("pip install cairosvg pillow")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLUE = "#34589f"
WHITE = "#ffffff"
GLOW = "#9fb8ec"          # the light blue of the crest's shading
SHADE = "#dbe5fa"         # the shadow side of the helmet
PLATE_TOP, PLATE_BOTTOM = "#ffffff", "#dfe8f8"

# ── the helmet (256×256 box, facing right) ──

CENTRE = (166.0, 152.0)   # the crest's arcs share this centre
R_CREST, R_DOME, R_RIDGE = 80, 71, 61
A_FRONT, A_BACK = 96, 184  # where the crest's holder runs: from the front, over the top, to the back (degrees)


def _pt(r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return CENTRE[0] + r * math.cos(a), CENTRE[1] - r * math.sin(a)


def _f(p: tuple[float, float]) -> str:
    return f"{p[0]:.1f},{p[1]:.1f}"


def _arc(r: float, d0: float, d1: float) -> str:
    return f"A{r:.1f},{r:.1f} 0 0,{0 if d1 > d0 else 1} {_f(_pt(r, d1))}"


SILHOUETTE = ("M184,12 C140,8 92,26 72,58 C56,84 54,122 66,146 L74,158 L60,192 L92,180 L96,190 L150,246 "
              "L194,226 L193,132 C193,100 182,80 160,71 Z")
CREST = (f"M172,21 C136,19 98,34 80,62 C68,84 66,114 74,140 L{_f(_pt(R_CREST, A_BACK))} "
         f"{_arc(R_CREST, A_BACK, 102)} Z")
HELMET = (f"M{_f(_pt(R_DOME, A_BACK))} {_arc(R_DOME, A_BACK, A_FRONT)} C176,86 185,104 185,134 "
          "L180,154 L174,180 L162,172 L148,236 L106,192 L102,178 L90,174 Z")
NECK = "M76,166 L88,164 L86,172 L70,181 Z"
EYE = "M118,133 L165,133 L165,150 L118,150 Q111,141.5 118,133 Z"
MOUTH = "M147,148 L164,148 L164,170 L150,240 L147,238 Z"
FACE = "M118,133 L165,133 L165,150 L164,150 L164,170 L150,238 L147,236 L147,150 L118,150 Q111,141.5 118,133 Z"
RIDGE = f"M{_f(_pt(R_RIDGE, A_FRONT + 12))} {_arc(R_RIDGE, A_FRONT + 12, 190)} L98,176"     # a stroke, 7 wide
GLEAM = "M170,96 C177,105 180,116 180,128"                                                   # a stroke, 3 wide


def _bristles() -> str:
    """The crest's bristles: spikes on its holder, swept back."""
    out = []
    for deg, length, lean in [(106, 11, 8), (119, 15, 10), (132, 12, 10), (145, 16, 12), (158, 12, 10), (171, 14, 10)]:
        b0, b1 = _pt(R_CREST - 2, deg - 3), _pt(R_CREST - 2, deg + 3)
        out.append(f"M{_f(b0)} L{_f(_pt(R_CREST + length, deg + lean / 2))} L{_f(b1)} Z")
    return " ".join(out)


def _crest_reach(deg: float) -> float:
    """How far the crest's white reaches from the arcs' centre at an angle (so the streaks stay inside it)."""
    mask = _mask(CREST, 1024)
    px, r = mask.load(), R_CREST + 2.0
    while True:
        x, y = _pt(r + 0.25, deg)
        if not (0 <= x < 256 and 0 <= y < 256) or px[int(x * 4), int(y * 4)] < 128:
            return r
        r += 0.25


def _mask(d: str, size: int):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><path fill="#000" d="{d}"/></svg>'
    data = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
    return Image.open(io.BytesIO(data)).getchannel("A")


def _streaks() -> str:
    """Light streaks through the crest's shading, like hair: from its holder most of the way out."""
    out = []
    for deg, r0, reach in [(112, 86, 0.8), (126, 88, 0.75), (140, 86, 0.7), (154, 88, 0.72), (167, 86, 0.7)]:
        r1 = r0 + (_crest_reach(deg + 5) - r0) * reach
        out.append(f"M{_f(_pt(r0, deg - 2.2))} L{_f(_pt(r1, deg + 5))} L{_f(_pt(r0, deg + 2.2))} Z")
    return " ".join(out)


BRISTLES, STREAKS = _bristles(), _streaks()


def helmet_svg(detail: bool = True) -> str:
    """The helmet's SVG elements (256 box). Without detail (tiny icons): no shading, streaks or gleam."""
    crest_fill = "url(#sg-glow)" if detail else WHITE
    helmet_fill = "url(#sg-shade)" if detail else WHITE
    parts = [
        f'<path fill="{BLUE}" d="{SILHOUETTE}"/>',
        f'<path fill="{crest_fill}" d="{CREST}"/>',
        f'<path fill="{WHITE}" d="{STREAKS}"/>' if detail else "",
        f'<path fill="{BLUE}" d="{BRISTLES}"/>',
        f'<path fill="{helmet_fill}" d="{HELMET}"/>',
        f'<path fill="none" stroke="{BLUE}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" d="{RIDGE}"/>',
        f'<path fill="none" stroke="{BLUE}" stroke-width="3" stroke-linecap="round" d="{GLEAM}"/>' if detail else "",
        f'<path fill="{BLUE}" d="{EYE}"/>',
        f'<path fill="{BLUE}" d="{MOUTH}"/>',
        f'<path fill="{WHITE}" d="{NECK}"/>',
    ]
    return "\n    ".join(p for p in parts if p)


HELMET_DEFS = f"""<radialGradient id="sg-glow" gradientUnits="userSpaceOnUse" cx="{CENTRE[0]}" cy="{CENTRE[1]}" r="140">
      <stop offset="0.55" stop-color="{GLOW}"/>
      <stop offset="0.85" stop-color="{WHITE}"/>
    </radialGradient>
    <linearGradient id="sg-shade" gradientUnits="userSpaceOnUse" x1="96" y1="0" x2="176" y2="0">
      <stop offset="0" stop-color="{SHADE}"/>
      <stop offset="0.6" stop-color="{WHITE}"/>
    </linearGradient>"""

# Where the helmet sits on the icon's plate (the plate is the 256 box): 84% of its height, centred.
HELMET_BOX = (54, 8, 194, 246)
PLATE_SCALE = 0.84


def _placement(box: float, scale: float) -> str:
    x0, y0, x1, y1 = HELMET_BOX
    s = box / 256 * scale
    tx = box / 2 - (x0 + x1) / 2 * s
    ty = box / 2 - (y0 + y1) / 2 * s
    return f"translate({tx:.2f} {ty:.2f}) scale({s:.4f})"


PLATES = {
    "rounded": '<rect x="4" y="4" width="248" height="248" rx="56" fill="url(#sg-plate)" stroke="#c9d6ef" stroke-width="1.5"/>',
    "square": '<rect width="256" height="256" fill="url(#sg-plate)"/>',
    "none": "",
}


def _svg(body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="sg-plate" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{PLATE_TOP}"/>
      <stop offset="1" stop-color="{PLATE_BOTTOM}"/>
    </linearGradient>
    <filter id="sg-blur" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="7"/></filter>
    {HELMET_DEFS}
  </defs>
  {body}
</svg>
"""


def icon_svg(plate: str = "rounded", detail: bool = True, glow: bool = True, helmet: bool = True) -> str:
    """The icon, 256 box. plate: "rounded" (desktop, web, older Android launchers), "square" (iOS: opaque, the
    system rounds it) or "none" (the helmet alone, as big as the box)."""
    g = _placement(256, PLATE_SCALE if plate != "none" else 1.0)
    glow_el = (f'<g transform="{g}" opacity="0.45" filter="url(#sg-blur)"><path fill="{BLUE}" '
               f'transform="translate(3 4)" d="{SILHOUETTE}"/></g>') if glow and helmet else ""
    helmet_el = f'<g transform="{g}">\n    {helmet_svg(detail)}\n  </g>' if helmet else ""
    return _svg(f"{PLATES[plate]}\n  {glow_el}\n  {helmet_el}")


# ── rendering ──

def _png(svg: str, size: int) -> Image.Image:
    data = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
    return Image.open(io.BytesIO(data)).convert("RGBA")


def render(size: int, plate: str = "rounded") -> Image.Image:
    """The icon as an image. cairosvg cannot blur, so the helmet's glow is made here."""
    detail = size >= 48
    out = _png(icon_svg(plate, detail, glow=False, helmet=False), size)
    helmet = _png(_svg(f'<g transform="{_placement(256, PLATE_SCALE if plate != "none" else 1.0)}">'
                       f'{helmet_svg(detail)}</g>'), size)
    shadow = Image.new("RGBA", (size, size), BLUE)            # the glow: the helmet blurred, a little lower
    shadow.putalpha(helmet.getchannel("A").point(lambda a: int(a * 0.45)))
    shadow = shadow.transform((size, size), Image.AFFINE, (1, 0, -size * 0.012, 0, 1, -size * 0.016))
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.028))
    if plate != "none":                                        # only on the plate
        inside = out.getchannel("A")
        shadow.putalpha(Image.composite(shadow.getchannel("A"), Image.new("L", (size, size), 0), inside))
    out.alpha_composite(shadow)
    out.alpha_composite(helmet)
    return out


def save_png(img: Image.Image, *path: str) -> None:
    full = os.path.join(ROOT, *path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    img.save(full, optimize=True)
    print("wrote", os.path.relpath(full, ROOT))


def write(text: str, *path: str) -> None:
    full = os.path.join(ROOT, *path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote", os.path.relpath(full, ROOT))


def macos_icon(size: int) -> Image.Image:
    """macOS: the plate at 824/1024 of the canvas with a soft shadow, as Apple's icon grid has it."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = round(size * 824 / 1024)
    icon = render(inner)
    off = (size - inner) // 2
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sil = Image.new("RGBA", icon.size, (20, 30, 60, 255))
    sil.putalpha(icon.getchannel("A").point(lambda a: int(a * 0.35)))
    shadow.alpha_composite(sil, (off, off + round(size * 0.012)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * 0.012)))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(icon, (off, off))
    return canvas


def appiconset(folder: str, maker) -> None:
    """Fill an Xcode AppIcon set: every image its Contents.json lists, at its pixel size."""
    contents = os.path.join(ROOT, folder, "Contents.json")
    if not os.path.isfile(contents):
        print("skipped", folder, "(no such platform yet)")
        return
    with open(contents, encoding="utf-8") as fh:
        images = json.load(fh)["images"]
    done = set()
    for im in images:
        name = im.get("filename")
        if not name or name in done:
            continue
        pts = float(im["size"].split("x")[0])
        px = round(pts * float(im.get("scale", "1x").rstrip("x")))
        save_png(maker(px), folder, name)
        done.add(name)


# ── Android ──

ANDROID_RES = ("app", "android", "app", "src", "main", "res")


def _vector(width_dp: int, viewport: float, body: str, comment: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!-- {comment} Made by scripts/make_icons.py. -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:aapt="http://schemas.android.com/aapt"
    android:width="{width_dp}dp"
    android:height="{width_dp}dp"
    android:viewportWidth="{viewport:g}"
    android:viewportHeight="{viewport:g}">
{body}
</vector>
"""


def _android_group(scale: float, tx: float, ty: float, inner: str) -> str:
    return (f'    <group android:translateX="{tx:.3f}" android:translateY="{ty:.3f}" '
            f'android:scaleX="{scale:.5f}" android:scaleY="{scale:.5f}">\n{inner}\n    </group>')


def _ap(d: str, fill: str | None = None, stroke: str | None = None, width: float = 0, extra: str = "") -> str:
    attrs = [f'android:pathData="{d}"']
    if fill:
        attrs.append(f'android:fillColor="{fill}"')
    if stroke:
        attrs += [f'android:strokeColor="{stroke}"', f'android:strokeWidth="{width:g}"',
                  'android:strokeLineCap="round"', 'android:strokeLineJoin="round"']
    return "        <path " + " ".join(attrs) + extra + " />"


def _ap_gradient(d: str, gradient: str) -> str:
    return (f'        <path android:pathData="{d}">\n'
            f'            <aapt:attr name="android:fillColor">\n{gradient}\n            </aapt:attr>\n'
            f'        </path>')


def android_helmet_paths(mono: str | None = None) -> str:
    """The helmet as vector drawable paths (256 box). mono: one colour for the themed icon and the
    notification icon — the blue parts only (the white parts are holes)."""
    if mono:            # a solid helmet: the face opening and a gap under the crest cut out of it
        gap = (f"M{_f(_pt(R_CREST - 1, A_BACK + 2))} {_arc(R_CREST - 1, A_BACK + 2, A_FRONT + 1)} "
               f"L{_f(_pt(R_DOME - 1, A_FRONT + 1))} {_arc(R_DOME - 1, A_FRONT + 1, A_BACK + 2)} Z")
        return _ap(f"{SILHOUETTE} {FACE} {gap}", mono, extra=' android:fillType="evenOdd"')
    crest_gradient = (f'                <gradient android:type="radial" android:centerX="{CENTRE[0]}" '
                      f'android:centerY="{CENTRE[1]}" android:gradientRadius="140">\n'
                      f'                    <item android:offset="0.55" android:color="{GLOW}" />\n'
                      f'                    <item android:offset="0.85" android:color="{WHITE}" />\n'
                      f'                </gradient>')
    shade_gradient = (f'                <gradient android:type="linear" android:startX="96" android:startY="0" '
                      f'android:endX="176" android:endY="0">\n'
                      f'                    <item android:offset="0" android:color="{SHADE}" />\n'
                      f'                    <item android:offset="0.6" android:color="{WHITE}" />\n'
                      f'                </gradient>')
    return "\n".join([
        _ap(SILHOUETTE, BLUE),
        _ap_gradient(CREST, crest_gradient),
        _ap(STREAKS, WHITE),
        _ap(BRISTLES, BLUE),
        _ap_gradient(HELMET, shade_gradient),
        _ap(RIDGE, stroke=BLUE, width=7),
        _ap(GLEAM, stroke=BLUE, width=3),
        _ap(EYE, BLUE),
        _ap(MOUTH, BLUE),
        _ap(NECK, WHITE),
    ])


def _fit(viewport: float, radius: float) -> tuple[float, float, float]:
    """Scale and offset that put the helmet inside a circle of ``radius`` around the viewport's centre."""
    a = _png(_svg(helmet_svg(False)), 512).getchannel("A")    # the helmet's own coordinates, ×2
    x0, y0, x1, y1 = a.getbbox()
    cx, cy = (x0 + x1) / 4, (y0 + y1) / 4
    px = a.load()
    far = max(math.hypot(x / 2 - cx, y / 2 - cy) for y in range(0, 512, 2) for x in range(0, 512, 2) if px[x, y] > 64)
    scale = radius / far
    return scale, viewport / 2 - cx * scale, viewport / 2 - cy * scale


def android() -> None:
    res = ANDROID_RES
    scale, tx, ty = _fit(108, 32)
    write(_vector(108, 108, _android_group(scale, tx, ty, android_helmet_paths()),
                  "The adaptive icon's front: the helmet, inside the safe zone."),
          *res, "drawable", "ic_launcher_foreground.xml")
    write(_vector(108, 108, _android_group(scale, tx, ty, android_helmet_paths(mono="#ffffff")),
                  "The themed icon (Android 13+): the helmet in the system's colour."),
          *res, "drawable", "ic_launcher_monochrome.xml")
    plate = (f'    <path android:pathData="M0,0h108v108h-108z">\n'
             f'        <aapt:attr name="android:fillColor">\n'
             f'            <gradient android:type="linear" android:startX="54" android:startY="0" '
             f'android:endX="54" android:endY="108">\n'
             f'                <item android:offset="0" android:color="{PLATE_TOP}" />\n'
             f'                <item android:offset="1" android:color="{PLATE_BOTTOM}" />\n'
             f'            </gradient>\n'
             f'        </aapt:attr>\n'
             f'    </path>')
    write(_vector(108, 108, plate, "The adaptive icon's back: the plate's light blue-white."),
          *res, "drawable", "ic_launcher_background.xml")
    ns, ntx, nty = _fit(24, 11.5)
    write(_vector(24, 24, _android_group(ns, ntx, nty, android_helmet_paths(mono="#ffffff")),
                  "Notification icon: the helmet in white."),
          *res, "drawable", "ic_stat_engine.xml")
    write("""<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@drawable/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground" />
    <monochrome android:drawable="@drawable/ic_launcher_monochrome" />
</adaptive-icon>
""", *res, "mipmap-anydpi-v26", "ic_launcher.xml")
    for folder, px in [("mipmap-mdpi", 48), ("mipmap-hdpi", 72), ("mipmap-xhdpi", 96), ("mipmap-xxhdpi", 144),
                       ("mipmap-xxxhdpi", 192)]:
        save_png(render(px), *res, folder, "ic_launcher.png")


def main() -> None:
    svg = icon_svg("rounded")
    write(svg, "packaging", "icon.svg")
    write(svg, "spartagen", "gui", "static", "icon.svg")
    save_png(render(256), "packaging", "icon.png")
    save_png(render(512), "app", "assets", "icon.png")

    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [render(s) for s in sizes]
    for target in (("packaging", "icon.ico"), ("app", "windows", "runner", "resources", "app_icon.ico")):
        full = os.path.join(ROOT, *target)
        frames[-1].save(full, format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
        print("wrote", os.path.relpath(full, ROOT))
    icns = os.path.join(ROOT, "packaging", "icon.icns")
    macos_icon(1024).save(icns, format="ICNS", append_images=[macos_icon(s) for s in (16, 32, 64, 128, 256, 512)])
    print("wrote", os.path.relpath(icns, ROOT))

    appiconset(os.path.join("app", "macos", "Runner", "Assets.xcassets", "AppIcon.appiconset"), macos_icon)
    appiconset(os.path.join("app", "ios", "Runner", "Assets.xcassets", "AppIcon.appiconset"),
               lambda px: render(px, plate="square").convert("RGB"))
    android()


if __name__ == "__main__":
    main()
