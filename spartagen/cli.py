"""Command line: `spartagen gui`, `make`, `analyze`, `base`, `pack`, `patterns`, `templates`, `selftest`."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__


def _progress_printer(quiet: bool = False):
    last = {"t": 0.0, "msg": ""}

    def cb(p: float, msg: str) -> None:
        if quiet:
            return
        now = time.time()
        if msg != last["msg"] or now - last["t"] > 0.5 or p >= 1.0:
            last["t"], last["msg"] = now, msg
            bar = "#" * int(p * 30)
            sys.stderr.write(f"\r[{bar:<30}] {int(p * 100):3d}%  {msg:<34}")
            sys.stderr.flush()
            if p >= 1.0:
                sys.stderr.write("\n")
    return cb


def _session_for(source: str, workspace: str | None, quiet: bool):
    from .project import Session
    from . import download
    s = Session(workspace=workspace)
    if download.is_url(source):
        path = download.download(source, s.path("source"), _progress_printer(quiet))
    else:
        path = source
    s.set_source(path)
    return s


def cmd_analyze(a: argparse.Namespace) -> int:
    s = _session_for(a.source, a.workspace, a.quiet)
    an = s.analysis(_progress_printer(a.quiet))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(an.to_dict(), fh, indent=1)
        print(f"analysis written to {a.json}")
    print(f"source: {s.project.source_path}  ({an.duration:.1f}s)")
    for kind in ("pitch", "kick", "snare", "hat", "crash", "quote", "word"):
        lst = an.candidates.get(kind, [])
        print(f"\n{kind.upper()}: {len(lst)} candidates")
        for c in lst[: a.top]:
            extra = ""
            if kind == "pitch":
                extra = f"{c.info.get('note')} ({c.info.get('cents', 0):+.0f}c) → tune to {c.info.get('d_note')}, " \
                        f"steady ±{c.info.get('stability_cents', 0):.0f}c"
            print(f"  {c.start:8.3f}s – {c.end:8.3f}s  ({c.duration:.2f}s)  score {c.score:.3f}  {extra}")
    return 0


def cmd_make(a: argparse.Namespace) -> int:
    s = _session_for(a.source, a.workspace, a.quiet)
    opts = {k: v for k, v in {
        "bpm": a.bpm, "key": a.key, "progression": a.progression, "pitching": a.pitching, "polish": a.polish,
        "minor": True if a.minor else None, "title": a.title, "chorus_pattern": a.chorus_pattern,
        "intro_pattern": a.intro_pattern, "chorus_pitch": True if a.chorus_pitch else None,
    }.items() if v is not None}
    opts.pop("key", None)
    if a.key:
        s.set_key(a.key)                 # otherwise the pitches follow the base's (or template's) key
    if a.pitch_octave:
        s.project.samples["pitch_octave"] = a.pitch_octave
    variant = a.variant or ("base" if a.base else "unextended")
    if a.base_structure:
        opts["base_structure"] = a.base_structure
    if a.base:
        s.project.options = dict(opts)
        bm = s.set_base(a.base, _progress_printer(a.quiet), fit=variant == "base",
                        template=a.base_template if a.base_template is not None else None)
        if not a.quiet:
            from .audio.base import BaseMap, describe
            print("base: " + describe(BaseMap.from_dict(bm)).replace("\n", "\n      "))
        if a.base_offset is not None:
            s.project.mix["base_offset"] = a.base_offset
        s.project.mix["base_mode"] = a.base_mode or ("remix" if variant == "base" else "replace")
    if a.midi:
        s.project.options = dict(opts, **{k: s.project.options[k] for k in ("key_mode",)
                                         if k in s.project.options})
        s.set_midi(a.midi)
        mapping = {}
        for item in (a.midi_map or "").split(","):
            if "=" in item:
                pid, role = item.split("=", 1)
                mapping[pid.strip()] = {"role": role.strip()}
        s.set_midi_mapping(mapping or None, auto_percussion=not a.no_auto_percussion,
                           auto_phrase=not a.no_auto_phrase)
        variant = "midi"
        if not a.quiet:
            _print_midi(s.midi_song(), s.project.midi["mapping"])
    s.set_variant(variant, opts)
    out = a.output
    quality = "audio" if a.audio_only else a.quality
    if out is None:
        ext = ".wav" if quality == "audio" else ".mp4"
        out = os.path.join(os.getcwd(), f"{s.project.name[:40]} - {variant}{ext}".replace("/", "_"))
    res = s.render(quality, _progress_printer(a.quiet), out_path=out, stems=a.stems)
    if a.export_midi:
        from .arrangement import compile_events
        from .midi import arrangement_to_midi
        arr = s.arrangement()
        arrangement_to_midi(arr, compile_events(arr, set(s.bank().samples)), a.export_midi)
        print(f"MIDI: {a.export_midi}")
    if a.pack:
        s.export_pack(a.pack, progress=_progress_printer(a.quiet))
        print(f"sample pack: {a.pack}")
    if a.project:
        s.project.save(a.project)
    print(f"\n{res['title']}\n  file: {res['file']}\n  length: {res['duration']:.1f}s   loudness: {res['lufs']} LUFS"
          f"   peak: {res['peak_db']} dBFS   notes: {res['events']}")
    return 0


def cmd_base(a: argparse.Namespace) -> int:
    from .audio.base import analyze_base_file, describe
    m = analyze_base_file(a.base, _progress_printer(a.quiet), bpm_hint=a.bpm)
    print(describe(m))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(m.to_dict(), fh, indent=1)
        print(f"base map written to {a.json}")
    return 0


def cmd_pack(a: argparse.Namespace) -> int:
    s = _session_for(a.source, a.workspace, a.quiet)
    s.project.samples["key"] = a.key
    res = s.export_pack(a.output, video=not a.no_video, progress=_progress_printer(a.quiet))
    print(f"{len(res['files'])} files written to {res['folder']}")
    return 0


def cmd_patterns(a: argparse.Namespace) -> int:
    from .patterns import library as lib
    from .patterns.notation import parse
    if a.parse:
        p = parse(a.parse, a.mode)
        print(f"mode: {p.mode}   length: {p.length} steps ({p.bars:.2f} bars)   voices: {p.voices}")
        for n in p.notes:
            print(f"  step {n.start:6.2f}  dur {n.dur:5.2f}  value {n.value:+d}" + (f"  voice {n.voice}" if p.voices > 1 else ""))
        for w in p.warnings:
            print("  warning:", w)
        return 0
    for section, title in lib.SECTION_TITLES.items():
        if a.section and a.section != section:
            continue
        print(f"\n== {title} ==")
        for d in lib.by_section(section):
            pp = d.parsed()
            print(f"  {d.id:30s} {d.name[:44]:44s} {pp.mode:8s} {pp.length / 16:5.2f} bars")
    return 0


def _print_midi(song, mapping: dict) -> None:
    from .midi import ROLES
    print(f"MIDI: {song.bpm:.2f} BPM, key {song.key}{' minor' if song.minor else ''}, {song.bars} bars, "
          f"{len(song.notes)} notes")
    for w in song.warnings:
        print(f"  note: {w}")
    for p in song.parts:
        m = mapping.get(p.id, {"role": "off"})
        print(f"  {p.id:8s} {p.name[:28]:28s} ch {p.channel:2d}  {p.notes:5d} notes  {p.range_text:9s} "
              f"poly {p.polyphony}  → {m['role']:7s} {ROLES[m['role']].split(' (')[0]}")


def cmd_midi(a: argparse.Namespace) -> int:
    from .midi import read_midi, suggest_roles
    song = read_midi(a.file)
    _print_midi(song, suggest_roles(song))
    print("\nuse: spartagen make VIDEO --midi FILE [--midi-map t1c0=pitch1,t4c9=drums …]")
    return 0


def cmd_templates(a: argparse.Namespace) -> int:
    from . import bases
    if a.import_file:
        t = bases.import_template(a.import_file)
        print(f"imported {t.name!r} as {t.id} ({t.path})")
        return 0
    for g in bases.catalog()["groups"]:
        print(f"\n{g['name']}")
        for t in g["templates"]:
            bpm = f"{t['bpm']:.0f}" + ("" if t["bpm_known"] else "?")
            print(f"  {t['id']:18s} {t['name']:40s} {bpm:>4s} BPM  {t['key']:3s} {t['bars']:3d} bars  "
                  f"{t['duration']:6.1f}s")
            if a.verbose:
                print(f"  {'':18s} {t['description']}")
    return 0


def cmd_selftest(a: argparse.Namespace) -> int:
    from .selftest import run
    return 0 if run(a.out, a.quality)["ok"] else 1


def cmd_gui(a: argparse.Namespace) -> int:
    from .gui.server import serve
    serve(host=a.host, port=a.port, open_browser=not a.no_browser, window=a.window, workspace=a.workspace)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spartagen", description="Sparta Remix generator — cuts a source video into "
                                 "pitch/percussion/quote samples and builds a Sparta Remix with ffmpeg.")
    ap.add_argument("--version", action="version", version=f"spartagen {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("gui", help="open the graphical app (default)")
    g.add_argument("--host", default="127.0.0.1")
    g.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    g.add_argument("--no-browser", action="store_true")
    g.add_argument("--window", action="store_true", help="open in a native window (needs pywebview)")
    g.add_argument("--workspace", default=None)
    g.set_defaults(fn=cmd_gui)

    m = sub.add_parser("make", help="build a remix from a video file or URL")
    m.add_argument("source", help="video/audio file or URL")
    m.add_argument("-o", "--output")
    m.add_argument("--template", "--variant", dest="variant", default=None,
                   help="base template (see `spartagen templates`: unextended, extended, nemesis, …); with --base "
                        "the default is 'base' (follow the base file's own sections)")
    m.add_argument("--quality", default="720p", choices=["preview", "720p", "1080p"])
    m.add_argument("--audio-only", action="store_true")
    m.add_argument("--bpm", type=float)
    m.add_argument("--key", default=None,
                   help="note the pitch samples are tuned to (default: the base's or template's key, else D)")
    m.add_argument("--pitch-octave", type=int, help="force the pitch octave (3, 4 or 5)")
    m.add_argument("--progression", help='chord roots, e.g. "0 1 -2 1" or "0 1 3 1 | -2"')
    m.add_argument("--pitching", choices=["classic", "normal", "hard"])
    m.add_argument("--polish", choices=["light", "normal", "hard"])
    m.add_argument("--minor", action="store_true")
    m.add_argument("--chorus-pattern", help="library id for the chorus (see `spartagen patterns`)")
    m.add_argument("--chorus-pitch", action="store_true",
                   help="tune the chorus (the main phrase) to the chords instead of playing it as is")
    m.add_argument("--intro-pattern", help="library id for the intro hits")
    m.add_argument("--title")
    m.add_argument("--base", help="a Sparta base (backing track): its tempo, bars, chords and sections are "
                   "detected and the remix is built on them")
    m.add_argument("--base-template", default=None,
                   help="which base template the --base file is: its tempo guides the analysis, its patterns "
                        "go on the base's parts")
    m.add_argument("--base-structure", choices=["detected", "template"], default=None,
                   help="follow the base's detected parts (default) or the --base-template's layout")
    m.add_argument("--base-offset", type=float, default=None,
                   help="seconds into the base where bar 1 starts (default: detected)")
    m.add_argument("--base-mode", default=None, choices=["replace", "remix", "layer"],
                   help="replace = mute our drums/bass/pads, remix = keep the source percussion (default with a "
                        "fitted base), layer = keep everything")
    m.add_argument("--midi", help="a MIDI base: the remix plays its notes (see `spartagen midi FILE`)")
    m.add_argument("--midi-map", help="roles for the MIDI's parts, e.g. t1c0=pitch1,t2c1=chords,t4c9=off "
                                      "(default: suggested)")
    m.add_argument("--no-auto-percussion", action="store_true",
                   help="do not add Sparta percussion when the MIDI has no drums")
    m.add_argument("--no-auto-phrase", action="store_true",
                   help="do not put the main phrase on the Chorus pattern when no MIDI part plays it")
    m.add_argument("--export-midi", help="also write the remix's notes as a MIDI file")
    m.add_argument("--stems", action="store_true", help="also write the stems")
    m.add_argument("--pack", help="also export the sample pack to this folder")
    m.add_argument("--project", help="save the project JSON here")
    m.add_argument("--workspace")
    m.add_argument("-q", "--quiet", action="store_true")
    m.set_defaults(fn=cmd_make)

    an = sub.add_parser("analyze", help="show what would be cut into samples")
    an.add_argument("source")
    an.add_argument("--json")
    an.add_argument("--top", type=int, default=5)
    an.add_argument("--workspace")
    an.add_argument("-q", "--quiet", action="store_true")
    an.set_defaults(fn=cmd_analyze)

    bs = sub.add_parser("base", help="map a Sparta base: tempo, bar 1, key, chord progression and sections")
    bs.add_argument("base")
    bs.add_argument("--bpm", type=float, help="tempo hint")
    bs.add_argument("--json", help="write the base map here")
    bs.add_argument("-q", "--quiet", action="store_true")
    bs.set_defaults(fn=cmd_base)

    pk = sub.add_parser("pack", help="export the sample pack (tuned pitches, percussion, quotes; wav + mp4)")
    pk.add_argument("source")
    pk.add_argument("-o", "--output", required=True)
    pk.add_argument("--key", default="D")
    pk.add_argument("--no-video", action="store_true")
    pk.add_argument("--workspace")
    pk.add_argument("-q", "--quiet", action="store_true")
    pk.set_defaults(fn=cmd_pack)

    pt = sub.add_parser("patterns", help="list the pattern library or parse a pattern")
    pt.add_argument("--section")
    pt.add_argument("--parse", help='e.g. "11_11_111_1_1_11222_2_222_222_2_"')
    pt.add_argument("--mode", default="auto", choices=["auto", "semitone", "compact", "index"])
    pt.set_defaults(fn=cmd_patterns)

    md = sub.add_parser("midi", help="show a MIDI base's parts and their suggested roles")
    md.add_argument("file")
    md.set_defaults(fn=cmd_midi)
    vv = sub.add_parser("templates", aliases=["variants"], help="list the base templates (or import one)")
    vv.add_argument("--import", dest="import_file", help="add a shared .spartabase.json to my templates")
    vv.add_argument("-v", "--verbose", action="store_true", help="show each template's description")
    vv.set_defaults(fn=cmd_templates)

    st = sub.add_parser("selftest", help="check this install: a test video through the one-click remix")
    st.add_argument("--out", help="write the report (JSON) here")
    st.add_argument("--quality", default="preview", choices=["audio", "preview", "720p"])
    st.set_defaults(fn=cmd_selftest)

    a = ap.parse_args(argv)
    if not getattr(a, "cmd", None):
        a = ap.parse_args(["gui"] + (argv or []))
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # show a clean message instead of a traceback
        if os.environ.get("SPARTAGEN_DEBUG"):
            raise
        sys.stderr.write(f"\nerror: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
