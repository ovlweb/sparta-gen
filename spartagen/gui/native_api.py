"""The API the native app (Flutter: Windows, macOS, Linux, Android) uses on top of the classic one.

Everything is a local path: the app picks files and destinations with the system's own Open/Save
dialogs and hands the engine their paths — nothing is uploaded or downloaded through a browser.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from typing import Optional

from .. import bases
from ..arrangement import compile_events


def _safe(name: str) -> str:
    import re
    return re.sub(r"[^\w\- ()]", "_", name)[:60] or "remix"


def midi_view(session) -> Optional[dict]:
    from ..midi import ROLES
    m = session.project.midi
    if not m:
        return None
    return {"path": m["path"], "summary": m["summary"], "mapping": m["mapping"],
            "auto_percussion": m.get("auto_percussion", True), "auto_phrase": m.get("auto_phrase", True),
            "section_bars": m.get("section_bars", 8), "roles": ROLES}


def arrangement_view(session) -> Optional[dict]:
    try:
        arr = session.arrangement()
    except Exception as exc:                       # e.g. "load a MIDI base first"
        return {"error": str(exc)}
    return {"title": arr.title, "variant": arr.variant, "bpm": arr.bpm, "key": arr.key,
            "progression": arr.progression, "pitching": arr.pitching, "polish": arr.polish,
            "duration": round(arr.duration, 2), "bars": arr.total_bars,
            "sections": [{"name": s.name, "kind": s.kind, "bars": s.bars, "layout": s.layout,
                          "tracks": [{"id": t.id, "kind": t.kind, "pattern": t.pattern, "muted": t.muted,
                                      "gain_db": t.gain_db} for t in s.tracks]} for s in arr.sections]}


def extra_view(session) -> dict:
    """What the native app shows on top of the classic project view."""
    p = session.project
    tpl = None
    if p.variant not in ("base", "midi"):
        try:
            tpl = bases.get_template(p.variant).to_dict()
        except KeyError:
            tpl = None
    base_tpl = session.base_template()
    return {"template": tpl, "midi": midi_view(session),
            "base_template": p.options.get("base_template") or "",
            "base_template_info": base_tpl.to_dict() if base_tpl else None,
            "base_structure": p.options.get("base_structure") or "detected",
            "key": p.samples.get("key") or "D", "key_mode": p.options.get("key_mode") or "auto",
            "arrangement": arrangement_view(session)}


def look_view(session) -> dict:
    from ..render_audio import FX_AMOUNTS, FX_PRESET_NAMES, FX_PRESETS, FX_SWITCHES, MixConfig
    from ..render_video import STYLE_NAMES, STYLE_OPTIONS, STYLES, VideoConfig
    p = session.project
    v = VideoConfig.from_dict(dict(p.video, preset_name="720p"))
    m = MixConfig.from_dict(p.mix)
    video_keys = ["style", "flip_mode", "hit_anim", "punch", "shake", "rgb_split", "border", "border_color",
                  "color_fx", "tint", "scanlines", "grain", "vignette", "letterbox", "transition", "background",
                  "flash", "hold_last"]
    return {"styles": STYLE_NAMES, "style_settings": STYLES, "style_options": STYLE_OPTIONS,
            "video": {k: getattr(v, k) for k in video_keys}, "video_set": p.video,
            "fx_presets": FX_PRESET_NAMES, "fx_settings": FX_PRESETS,
            "fx_amounts": {k: {"default": d, "min": lo, "max": hi} for k, (d, lo, hi) in FX_AMOUNTS.items()},
            "fx_switches": FX_SWITCHES,
            "mix": {k: getattr(m, k) for k in ["fx_preset", *FX_AMOUNTS, *FX_SWITCHES, "base_gain_db", "base_mode"]},
            "mix_set": {k: v for k, v in p.mix.items() if k not in ("base_path", "base_offset")}}


def route(h, method: str, path: str, q: dict) -> bool:
    """Handle a native-app route; False when the path is not one of them."""
    app = h.app
    s = app.session

    def ok(obj=None):
        h._json(obj if obj is not None else dict(app.project_view()))
        return True

    # ── base templates ──
    if path == "/api/templates" and method == "GET":
        return ok(bases.catalog())
    if path == "/api/template/use" and method == "POST":
        b = h._body_json()
        opts = dict(s.project.options)
        for k in ("bpm", "title", "pitching", "polish", "progression", "chorus_pitch", "patterns"):
            if k in b:
                opts[k] = b[k]
        if b.get("id") and b["id"] != s.project.variant:
            opts.pop("bpm", None) if "bpm" not in b else None
        s.set_variant(b.get("id") or s.project.variant, opts)
        return ok()
    if path == "/api/template/save" and method == "POST":
        b = h._body_json()
        name = str(b.get("name") or "").strip()
        if not name:
            h._error("give the template a name")
            return True
        t = bases.template_from_arrangement(s.arrangement(), name, str(b.get("description") or ""),
                                            key=s.project.samples.get("key"),
                                            options=dict(s.project.options.get("patterns") or {}))
        saved = bases.save_user_template(t)
        return ok({"saved": saved.to_dict(), "catalog": bases.catalog()})
    if path == "/api/template/import" and method == "POST":
        t = bases.import_template(h._body_json()["path"])
        return ok({"saved": t.to_dict(), "catalog": bases.catalog()})
    if path == "/api/template/delete" and method == "POST":
        bases.delete_user_template(h._body_json()["id"])
        return ok({"catalog": bases.catalog()})

    # ── base audio file ──
    if path == "/api/base/open" and method == "POST":
        b = h._body_json()
        src = b.get("path", "")
        if not os.path.isfile(src):
            h._error(f"file not found: {src}")
            return True
        if "structure" in b:
            s.project.options["base_structure"] = b["structure"]

        def run(progress):
            try:
                s.set_base(src, progress, fit=b.get("follow", True), template=b.get("template"))
            except Exception as exc:                 # still usable as a plain backing track
                s.project.mix["base_path"] = src
                s.project.base = None
                return dict(app.project_view(), base_error=str(exc))
            return app.project_view()
        h._json(app.start_job("base", run).to_dict())
        return True
    if path == "/api/base/options" and method == "POST":
        b = h._body_json()
        if "template" in b:
            s.project.options["base_template"] = b["template"] or ""
        if "structure" in b:
            s.project.options["base_structure"] = b["structure"]
        for k in ("base_gain_db", "base_mode", "base_offset"):
            if k in b:
                s.project.mix[k] = b[k]
        if b.get("follow") and s.project.base:
            s.project.variant = "base"
        s.project.arrangement = None
        return ok()
    if path == "/api/base/clear" and method == "POST":
        s.clear_base()
        return ok()

    # ── MIDI base ──
    if path == "/api/midi/open" and method == "POST":
        src = h._body_json().get("path", "")
        if not os.path.isfile(src):
            h._error(f"file not found: {src}")
            return True
        s.set_midi(src)
        return ok()
    if path == "/api/midi/mapping" and method == "POST":
        b = h._body_json()
        s.set_midi_mapping(b.get("mapping"), b.get("auto_percussion"), b.get("auto_phrase"), b.get("section_bars"))
        if b.get("use"):
            s.set_variant("midi", s.project.options)
        return ok()
    if path == "/api/midi/clear" and method == "POST":
        s.clear_midi()
        return ok()

    # ── key ──
    if path == "/api/key" and method == "POST":
        s.set_key(h._body_json().get("key"))
        if s.project.variant not in ("base", "midi"):
            s.project.arrangement = None
        return ok()

    # ── look & sound ──
    if path == "/api/look" and method == "GET":
        return ok(look_view(s))
    if path == "/api/look" and method == "POST":
        from ..render_audio import MixConfig
        from ..render_video import VideoConfig
        b = h._body_json()
        video = dict(b.get("video") or {})
        mix = dict(b.get("mix") or {})
        new_video = video if b.get("replace_video") else dict(s.project.video, **video)
        new_video = {k: v for k, v in new_video.items() if v is not None}
        new_mix = dict(s.project.mix)
        if b.get("replace_fx"):
            from ..render_audio import FX_AMOUNTS, FX_SWITCHES
            for k in ["fx_preset", *FX_AMOUNTS, *FX_SWITCHES]:
                new_mix.pop(k, None)
        new_mix.update({k: v for k, v in mix.items()})
        new_mix = {k: v for k, v in new_mix.items() if v is not None}
        VideoConfig.from_dict(dict(new_video, preset_name="720p"))      # raise on bad values
        MixConfig.from_dict(new_mix)
        s.project.video = new_video
        s.project.mix = new_mix
        return ok(look_view(s))

    # ── exports (to paths the user chose in a Save dialog) ──
    if path == "/api/export/file" and method == "POST":
        b = h._body_json()
        src, dest = b.get("file", ""), os.path.expanduser(b.get("dest", ""))
        if not src or not os.path.isfile(src):
            h._error("render the remix first")
            return True
        if not dest:
            h._error("choose where to save it")
            return True
        if os.path.isdir(dest):
            dest = os.path.join(dest, os.path.basename(src))
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        if b.get("audio_format") in ("mp3", "wav", "flac", "m4a") and not dest.lower().endswith(".wav") \
                and b["audio_format"] != "wav":
            from .. import ffmpeg as ff
            ff.encode_audio(src, dest)
        else:
            shutil.copyfile(src, dest)
        return ok({"saved": dest})
    if path == "/api/export/pack" and method == "POST":
        b = h._body_json()
        dest = os.path.expanduser(b.get("dest", ""))
        if not dest:
            h._error("choose a folder for the sample pack")
            return True

        def run(progress):
            if dest.lower().endswith(".zip"):
                folder = s.path("sample_pack")
                if os.path.isdir(folder):
                    shutil.rmtree(folder)
                res = s.export_pack(folder, video=bool(b.get("video", True)), progress=lambda p, m: progress(0.9 * p, m))
                top = f"{_safe(s.project.name)} - sample pack"
                with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in res["files"]:
                        z.write(f, top + "/" + os.path.relpath(f, folder).replace(os.sep, "/"))
                return {"saved": dest, "count": len(res["files"])}
            folder = os.path.join(dest, f"{_safe(s.project.name)} - sample pack")
            if os.path.isdir(folder):
                shutil.rmtree(folder)
            res = s.export_pack(folder, video=bool(b.get("video", True)), progress=progress)
            return {"saved": folder, "count": len(res["files"])}
        h._json(app.start_job("pack", run).to_dict())
        return True
    if path == "/api/export/midi" and method == "POST":
        from ..midi import arrangement_to_midi
        dest = os.path.expanduser(h._body_json().get("dest", ""))
        if not dest:
            h._error("choose where to save the MIDI file")
            return True
        arr = s.arrangement()
        try:
            available = set(s.bank().samples) if s.project.analysis else None
        except Exception:
            available = None
        arrangement_to_midi(arr, compile_events(arr, available), dest)
        return ok({"saved": dest})

    # ── projects ──
    if path == "/api/project/save_as" and method == "POST":
        dest = os.path.expanduser(h._body_json().get("dest", ""))
        if not dest:
            h._error("choose where to save the project")
            return True
        return ok({"saved": s.project.save(dest)})

    # ── jobs ──
    if path.startswith("/api/job/") and path.endswith("/cancel") and method == "POST":
        job = app.jobs.get(path.split("/")[3])
        if job is None:
            h._error("unknown job", 404)
            return True
        job.cancel_requested = True
        return ok(job.to_dict())
    return False
