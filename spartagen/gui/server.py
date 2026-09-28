"""The engine's HTTP server: a JSON API over the pipeline.

The Sparta Gen app (Flutter: Windows, macOS, Linux, Android) runs it headless with a secret token
(:func:`serve_engine`); `spartagen gui` serves the classic single-page web app with it too, for running
from source or in Termux.  Only the Python standard library is used, so it runs wherever the engine runs.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from .. import __version__
from .. import ffmpeg as ff
from .. import download as dl
from ..arrangement import VARIANTS, Arrangement, make_section, SECTION_BUILDERS
from ..patterns import library as lib
from ..patterns.notation import parse as parse_pattern, parse_progression
from ..project import Project, Session, default_workspace

STATIC = os.path.join(os.path.dirname(__file__), "static")


# ── jobs ─────────────────────────────────────────────────────────────────────


class JobCancelled(Exception):
    """Raised inside a job's progress callback once the user cancelled it."""


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.cancel_requested = False
        self.status = "running"
        self.progress = 0.0
        self.message = "starting"
        self.result: Any = None
        self.error: Optional[str] = None
        self.started = time.time()
        self.finished: Optional[float] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "progress": round(self.progress, 4),
                "message": self.message, "result": self.result, "error": self.error,
                "elapsed": round((self.finished or time.time()) - self.started, 1)}


class App:
    def __init__(self, workspace_root: Optional[str] = None, resume: bool = False):
        self.root = workspace_root or default_workspace()
        os.makedirs(self.root, exist_ok=True)
        self.session = self._last_session() if resume else None
        if self.session is None:
            self.session = Session(workspace=self._new_workspace())
        self.jobs: dict[str, Job] = {}
        self.heavy_lock = threading.Lock()

    def _new_workspace(self) -> str:
        return os.path.join(self.root, time.strftime("remix-%Y%m%d-%H%M%S"))

    def _last_session(self) -> Optional["Session"]:
        """The project worked on last (the app opens where you left it)."""
        for entry in _list_projects(self.root):
            try:
                return Session(Project.load(entry["path"]))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return None

    def start_job(self, kind: str, fn: Callable[[Callable[[float, str], None]], Any], heavy: bool = True) -> Job:
        job = Job(kind)
        self.jobs[job.id] = job

        def progress(p: float, msg: str) -> None:
            if job.cancel_requested:
                raise JobCancelled()
            job.progress = max(job.progress, min(1.0, float(p)))
            job.message = msg

        def run() -> None:
            acquired = False
            try:
                if heavy:
                    job.message = "waiting for the previous job"
                    self.heavy_lock.acquire()
                    acquired = True
                job.result = fn(progress)
                job.status = "done"
                job.progress = 1.0
                job.message = "done"
            except JobCancelled:
                job.status = "cancelled"
                job.message = "cancelled"
            except Exception as exc:  # reported to the UI
                job.status = "error"
                job.error = str(exc) or exc.__class__.__name__
                traceback.print_exc()
            finally:
                job.finished = time.time()
                if acquired:
                    self.heavy_lock.release()
                try:
                    self.session.project.save()
                except Exception:
                    pass

        threading.Thread(target=run, daemon=True).start()
        return job

    # ── views ──
    def media_url(self, path: str) -> Optional[str]:
        if not path:
            return None
        ws = os.path.abspath(self.root)
        ap = os.path.abspath(path)
        if ap.startswith(ws + os.sep):
            return "/media/" + quote(os.path.relpath(ap, ws).replace(os.sep, "/"))
        return "/file?path=" + quote(ap)

    def project_view(self) -> dict:
        p = self.session.project
        d = {
            "name": p.name, "workspace": p.workspace, "variant": p.variant, "options": p.options,
            "samples_config": p.samples, "mix": p.mix, "video": p.video,
            "source": None, "analyzed": p.analysis is not None, "outputs": {},
            "base": ({k: v for k, v in p.base.items() if k not in ("roots", "bar_db")} if p.base else None),
        }
        if p.source_path:
            d["source"] = dict(p.source_info, url=self.media_url(p.source_path), name=os.path.basename(p.source_path))
        for q, out in (p.outputs or {}).items():
            o = dict(out)
            o["file_url"] = self.media_url(out.get("file", ""))
            o["audio_url"] = self.media_url(out.get("audio", ""))
            d["outputs"][q] = o
        if p.source_path:
            d["source"]["path"] = p.source_path
        d["base_path"] = p.mix.get("base_path")
        from .native_api import extra_view
        d.update(extra_view(self.session))
        return d

    def bank_view(self) -> dict:
        s = self.session
        bank = s.bank()
        an = s.analysis()
        samples = []
        for sid, smp in bank.samples.items():
            d = smp.to_dict()
            d["audio_url"] = f"/api/sample/{sid}.wav?v={abs(hash(s._bank_key)) % 10 ** 8}"
            d["thumb_url"] = f"/api/thumb?t={smp.src_start + min(0.05, smp.duration / 2):.3f}"
            samples.append(d)
        cands = {}
        for kind, lst in an.candidates.items():
            cands[kind] = [dict(c.to_dict(), audio_url=f"/api/candidate/{kind}/{i}.wav",
                                thumb_url=f"/api/thumb?t={c.start + 0.02:.3f}") for i, c in enumerate(lst[:25])]
            for c in cands[kind]:
                c["info"].pop("mfcc", None)
                c["info"].pop("frames", None)
        return {"samples": samples, "candidates": cands, "config": s.project.samples,
                "analysis": {"duration": an.duration, "noise_floor_db": an.noise_floor_db,
                             "loud_ref_db": an.loud_ref_db}}


# ── HTTP handler ─────────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    app: App = None  # type: ignore
    server_version = f"SpartaGen/{__version__}"

    def log_message(self, fmt: str, *args) -> None:  # quiet
        if os.environ.get("SPARTAGEN_DEBUG"):
            super().log_message(fmt, *args)

    # ── helpers ──
    def _json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, msg: str, status: int = 400) -> None:
        self._json({"error": msg}, status)

    def _body_json(self) -> dict:
        cached = getattr(self, "_body_cache", None)
        if cached is not None:
            return cached
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            raw = self._read_chunked()
        else:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n > 0 else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except ValueError:
            body = {}
        self._body_cache = body if isinstance(body, dict) else {}
        return self._body_cache

    def _read_chunked(self, limit: int = 64 << 20) -> bytes:
        """A body sent in chunks (HTTP/1.1 clients that do not say its length up front)."""
        out = bytearray()
        while True:
            line = self.rfile.readline(65537)
            if not line:
                break
            size = int(line.split(b";")[0].strip() or b"0", 16)
            if size == 0:
                while self.rfile.readline(65537) not in (b"\r\n", b"\n", b""):   # trailers
                    pass
                break
            out += self.rfile.read(size)
            self.rfile.readline()                                                   # the chunk's CRLF
            if len(out) > limit:
                raise ValueError("request body too large")
        return bytes(out)

    def _send_file(self, path: str, download_name: Optional[str] = None) -> None:
        if not os.path.isfile(path):
            self._error("not found", 404)
            return
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download_name:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(download_name)}")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def _receive_upload(self, folder: str) -> str:
        name = unquote(self.headers.get("X-Filename") or "") or parse_qs(urlparse(self.path).query).get("name", ["upload.mp4"])[0]
        name = re.sub(r"[^\w.\- ()\[\]]", "_", os.path.basename(name))[:120] or "upload.mp4"
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, name)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ValueError("empty upload")
        with open(dest, "wb") as fh:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                fh.write(chunk)
                left -= len(chunk)
        return dest

    # ── routing ──
    def do_GET(self) -> None:
        try:
            self._route("GET")
        except Exception as exc:
            traceback.print_exc()
            self._error(str(exc), 500)

    def do_POST(self) -> None:
        try:
            self._route("POST")
        except Exception as exc:
            traceback.print_exc()
            self._error(str(exc), 500)

    def do_PUT(self) -> None:
        self.do_POST()

    def _route(self, method: str) -> None:
        app = self.app
        url = urlparse(self.path)
        path = url.path
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        token = getattr(self.server, "token", None)
        if token and self.headers.get("X-Sparta-Token") != token and q.get("token") != token:
            return self._error("not allowed", 401)
        if not getattr(self.server, "web_ui", True) and (path in ("/", "/index.html") or path.startswith("/static/")):
            return self._error("this engine serves the Sparta Gen app only", 404)

        if method == "GET" and path in ("/", "/index.html"):
            return self._send_file(os.path.join(STATIC, "index.html"))
        if method == "GET" and path.startswith("/static/"):
            rel = os.path.normpath(unquote(path[len("/static/"):]))
            if rel.startswith(".."):
                return self._error("bad path", 400)
            return self._send_file(os.path.join(STATIC, rel))
        if method == "GET" and path.startswith("/media/"):
            rel = unquote(path[len("/media/"):])
            full = os.path.abspath(os.path.join(app.root, rel))
            if not full.startswith(os.path.abspath(app.root) + os.sep):
                return self._error("bad path", 400)
            return self._send_file(full, q.get("download"))
        if method == "GET" and path == "/file":
            # Only files the project references (the source / a render) may be served from outside the workspace.
            full = os.path.abspath(q.get("path", ""))
            p = app.session.project
            allowed = {os.path.abspath(p.source_path)} | {os.path.abspath(o.get("file", "")) for o in p.outputs.values()}
            if p.mix.get("base_path"):
                allowed.add(os.path.abspath(p.mix["base_path"]))
            if full not in allowed:
                return self._error("forbidden", 403)
            return self._send_file(full, q.get("download"))

        s = app.session
        if path == "/api/status":
            return self._json({
                "version": __version__, "ffmpeg": ff.available(),
                "ffmpeg_version": ff.version() if ff.available() else None,
                "yt_dlp": dl.available(), "scipy": _has("scipy"), "pillow": _has("PIL"),
                "project": app.project_view(),
                "jobs": [j.to_dict() for j in app.jobs.values() if j.status == "running"],
            })
        if path == "/api/project" and method == "GET":
            return self._json(app.project_view())
        if path == "/api/project/new" and method == "POST":
            app.session = Session(workspace=app._new_workspace())
            return self._json(app.project_view())
        if path == "/api/project/save" and method == "POST":
            where = s.project.save()
            return self._json({"saved": where})
        if path == "/api/projects" and method == "GET":
            return self._json({"projects": _list_projects(app.root)})
        if path == "/api/project/open" and method == "POST":
            body = self._body_json()
            proj = Project.load(body["path"])
            app.session = Session(proj)
            return self._json(app.project_view())
        if path == "/api/project/name" and method == "POST":
            s.project.name = str(self._body_json().get("name", s.project.name))[:80]
            return self._json(app.project_view())    # a structure you edited keeps its own title

        # ── source ──
        if path == "/api/source/upload" and method == "POST":
            dest = self._receive_upload(s.path("source"))
            info = s.set_source(dest)
            return self._json({"source": info, "project": app.project_view()})
        if path == "/api/source/path" and method == "POST":
            p = self._body_json().get("path", "")
            if not os.path.isfile(p):
                return self._error(f"file not found: {p}")
            s.set_source(p)
            return self._json({"project": app.project_view()})
        if path == "/api/source/url" and method == "POST":
            link = self._body_json().get("url", "").strip()
            if not link:
                return self._error("no URL given")

            def run(progress):
                file = dl.download(link, s.path("source"), progress)
                s.set_source(file)
                return app.project_view()
            return self._json(app.start_job("download", run).to_dict())

        # ── analysis & samples ──
        if path == "/api/analyze" and method == "POST":
            body = self._body_json()

            def run(progress):
                s.analysis(lambda p, m: progress(0.8 * p, m), force=bool(body.get("force")))
                s.bank(lambda p, m: progress(0.8 + 0.2 * p, m))
                return app.bank_view()
            return self._json(app.start_job("analyze", run).to_dict())
        if path == "/api/samples" and method == "GET":
            if not s.project.source_path:
                return self._error("load a source first")
            if s.project.analysis is None:
                return self._error("not analysed yet", 409)
            return self._json(app.bank_view())
        if path == "/api/samples/select" and method == "POST":
            body = self._body_json()
            role = body.get("role")
            sel = s.project.samples.setdefault("selections", {})
            if body.get("reset"):
                sel.pop(role, None)
            elif "start" in body and "end" in body:
                sel[role] = {"start": float(body["start"]), "end": float(body["end"])}
            else:
                sel[role] = int(body.get("index", 0))
            return self._json(app.bank_view())
        if path == "/api/samples/config" and method == "POST":
            body = self._body_json()
            for k in ("key", "pitch_octave", "flatten", "bass_octave"):
                if k in body:
                    s.project.samples[k] = body[k] if body[k] not in ("", "auto") else None
            if not s.project.samples.get("key"):
                s.project.samples["key"] = "D"
            return self._json(app.bank_view())
        m = re.match(r"^/api/sample/([\w]+)\.wav$", path)
        if m:
            return self._send_file(s.sample_wav(m.group(1)))
        m = re.match(r"^/api/candidate/(\w+)/(\d+)\.wav$", path)
        if m:
            return self._send_file(s.candidate_wav(m.group(1), int(m.group(2))))
        if path == "/api/thumb":
            if not s.project.source_path or not s.project.source_info.get("has_video"):
                return self._send_file(os.path.join(STATIC, "noframe.svg"))
            t = float(q.get("t", 0))
            w, h = int(q.get("w", 240)), int(q.get("h", 135))
            out = s.path("thumbs", f"{int(t * 1000)}-{w}x{h}.jpg")
            if not os.path.isfile(out):
                ff.save_jpeg(s.project.source_path, t, out, w, h)
            return self._send_file(out)

        # ── patterns & arrangement ──
        if path == "/api/variants":
            return self._json({"variants": {k: {"title": v["title"], "description": v["description"],
                                                "bpm": v["bpm"], "pitching": v["pitching"], "polish": v["polish"],
                                                "plan": v["plan"]} for k, v in VARIANTS.items()},
                               "section_kinds": list(SECTION_BUILDERS)})
        if path == "/api/patterns":
            return self._json(lib.catalog())
        if path == "/api/pattern/parse" and method == "POST":
            body = self._body_json()
            text = body.get("text", "")
            if body.get("progression"):
                try:
                    pr = parse_progression(text)
                    return self._json({"ok": True, "progression": pr.roots})
                except ValueError as exc:
                    return self._json({"ok": False, "error": str(exc)})
            if body.get("lines") == "sequence" and "\n" in text.strip():
                p = lib.parse_sequence(text, body.get("mode", "auto"))
                loop = p.length
            else:
                p = parse_pattern(text, body.get("mode", "auto"))
                loop = p.loop_length()
            return self._json({"ok": bool(p.notes), **p.to_dict(), "loop": loop})
        if path == "/api/pattern/add" and method == "POST":
            body = self._body_json()
            pid = "user." + re.sub(r"\W+", "_", body.get("name", "pattern")).lower()[:40]
            d = lib.PatternDef(pid, body.get("name", pid), body.get("section", "chorus"), body["text"],
                               mode=body.get("mode", "auto"), credit="user")
            lib.register(d)
            s.project.options.setdefault("user_patterns", {})[pid] = d.to_dict()
            return self._json({"id": pid, "pattern": d.to_dict()})
        if path == "/api/arrangement" and method == "GET":
            return self._json(s.arrangement().to_dict())
        if path == "/api/arrangement/variant" and method == "POST":
            body = self._body_json()
            arr = s.set_variant(body.get("variant", s.project.variant), body.get("options", s.project.options))
            return self._json(arr.to_dict())
        if path == "/api/arrangement" and method == "POST":
            body = self._body_json()
            arr = Arrangement.from_dict(body)          # validates the structure
            s.project.arrangement = arr.to_dict()
            return self._json(arr.to_dict())
        if path == "/api/arrangement/section" and method == "POST":
            body = self._body_json()
            opts = dict(s.project.options)
            opts["hard"] = s.arrangement().pitching == "hard"
            sec = make_section(body["kind"], int(body.get("bars", 8)), opts)
            return self._json(sec.to_dict())
        if path == "/api/mix" and method == "POST":
            body = self._body_json()
            for k in ("base_offset", "base_gain_db", "base_mode", "stem_gains", "mute", "target_lufs"):
                if k in body:
                    s.project.mix[k] = body[k]
            if body.get("clear_base"):
                s.clear_base()
            for k in ("width", "height", "fps", "crf", "flash", "zoom_punch", "hold_last", "titles", "background"):
                if k in body.get("video", {}):
                    s.project.video[k] = body["video"][k]
            return self._json(app.project_view())
        if path == "/api/base/upload" and method == "POST":
            dest = self._receive_upload(s.path("base"))
            try:
                s.set_base(dest, fit=True)       # map tempo, bars, chords, sections; follow them
            except Exception as exc:              # still usable as a plain backing track
                s.project.mix["base_path"] = dest
                s.project.base = None
                return self._json(dict(app.project_view(), base_error=str(exc)))
            return self._json(app.project_view())

        # ── one click: samples cut automatically, the remix built (on the base when there is one), a preview ──
        if path == "/api/auto" and method == "POST":
            body = self._body_json()
            quality = body.get("quality", "preview")
            if not s.project.source_path:
                return self._error("load a source video first")

            def run(progress):
                s.analysis(lambda p, m: progress(0.3 * p, m))
                s.bank(lambda p, m: progress(0.3 + 0.15 * p, m))
                if s.project.base and s.project.variant != "base" and not s.project.arrangement:
                    s.set_variant("base", s.project.options)
                res = s.render(quality, lambda p, m: progress(0.45 + 0.55 * p, m))
                out = dict(res)
                out["file_url"] = app.media_url(res.get("file", ""))
                out["audio_url"] = app.media_url(res.get("audio", ""))
                return out
            return self._json(app.start_job(f"auto-{quality}", run).to_dict())

        # ── render & export ──
        if path == "/api/render" and method == "POST":
            body = self._body_json()
            quality = body.get("quality", "preview")

            def run(progress):
                res = s.render(quality, progress)
                out = dict(res)
                out["file_url"] = app.media_url(res.get("file", ""))
                out["audio_url"] = app.media_url(res.get("audio", ""))
                return out
            return self._json(app.start_job(f"render-{quality}", run).to_dict())
        if path == "/api/pack" and method == "POST":
            body = self._body_json()

            def run(progress):
                folder = s.path("sample_pack")
                if os.path.isdir(folder):
                    shutil.rmtree(folder)
                res = s.export_pack(folder, video=bool(body.get("video", True)), progress=lambda p, m: progress(0.9 * p, m))
                zpath = s.path("exports", f"{_safe(s.project.name)} - sample pack.zip")
                top = f"{_safe(s.project.name)} - sample pack"
                with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in res["files"]:
                        z.write(f, top + "/" + os.path.relpath(f, folder).replace(os.sep, "/"))
                return {"zip": zpath, "zip_url": app.media_url(zpath), "count": len(res["files"])}
            return self._json(app.start_job("pack", run).to_dict())
        if path == "/api/save_as" and method == "POST":
            body = self._body_json()
            src = body.get("file", "")
            # An empty box means the folder it suggests (~/Videos); a path without a file name is a folder.
            dest = os.path.expanduser(str(body.get("dest") or "").strip() or os.path.join("~", "Videos"))
            if not src or not os.path.isfile(src):
                return self._error("render the remix first — there is no file to copy yet")
            if os.path.isdir(dest) or dest.endswith(("/", "\\")) or not os.path.splitext(dest)[1]:
                os.makedirs(dest, exist_ok=True)
                dest = os.path.join(dest, os.path.basename(src))
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
            shutil.copy2(src, dest)
            return self._json({"saved": dest})
        if path == "/api/quit" and method == "POST":
            self._json({"bye": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        m = re.match(r"^/api/job/(\w+)$", path)
        if m:
            job = app.jobs.get(m.group(1))
            if job is None:
                return self._error("unknown job", 404)
            return self._json(job.to_dict())
        from .native_api import route as native_route
        try:
            if native_route(self, method, path, q):
                return None
        except (ValueError, KeyError, FileNotFoundError) as exc:     # bad input: the app shows the message
            msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
            return self._error(str(msg), 400)
        return self._error(f"no route for {method} {path}", 404)


def _json_default(o: Any):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    return str(o)


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def _safe(name: str) -> str:
    return re.sub(r"[^\w\- ()]", "_", name)[:60] or "remix"


def _list_projects(root: str) -> list[dict]:
    out = []
    if not os.path.isdir(root):
        return out
    for d in sorted(os.listdir(root), reverse=True):
        f = os.path.join(root, d, "project.spartagen.json")
        if os.path.isfile(f):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                out.append({"path": f, "name": meta.get("name"), "variant": meta.get("variant"),
                            "source": os.path.basename(meta.get("source_path") or "") or None,
                            "modified": os.path.getmtime(f)})
            except (OSError, ValueError):
                continue
    out.sort(key=lambda p: p["modified"], reverse=True)
    return out[:50]


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
        sk.bind((host, 0))
        return sk.getsockname()[1]


def _open_url(url: str) -> None:
    if shutil.which("termux-open-url"):  # Android / Termux
        subprocess.Popen(["termux-open-url", url])
        return
    webbrowser.open(url)


def make_server(host: str = "127.0.0.1", port: int = 0, workspace: Optional[str] = None,
                token: Optional[str] = None, web_ui: bool = True,
                resume: bool = False) -> tuple[ThreadingHTTPServer, str]:
    app = App(workspace, resume=resume)
    Handler.app = app
    if port == 0:
        port = _free_port(host)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.token = token or None                     # type: ignore[attr-defined]
    httpd.web_ui = web_ui                           # type: ignore[attr-defined]
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    return httpd, f"http://{shown}:{port}/"


def _parent_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32                # type: ignore[attr-defined]
        h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102   # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(h)
    return os.getppid() == pid


def serve_engine(port: int = 0, token: Optional[str] = None, parent_pid: Optional[int] = None,
                 workspace: Optional[str] = None, host: str = "127.0.0.1", resume: bool = True) -> None:
    """The engine behind the native app: no browser, no web page, a token on every call, and gone as
    soon as the app that started it is. It opens the project worked on last."""
    httpd, url = make_server(host, port, workspace, token=token, web_ui=False, resume=resume)
    real_port = httpd.server_address[1]
    try:
        print(f"SPARTAGEN_ENGINE_READY port={real_port}", flush=True)
    except Exception:                               # no console (windowed build): the app polls instead
        pass
    if parent_pid:
        def watch() -> None:
            while _parent_alive(parent_pid):
                time.sleep(1.0)
            httpd.shutdown()
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=watch, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def serve(host: str = "127.0.0.1", port: int = 0, open_browser: bool = True,
          workspace: Optional[str] = None) -> None:
    """The classic web app in a browser (`spartagen gui`): for running from source without the app, or on a
    phone in Termux.  The Sparta Gen app itself is native and uses :func:`serve_engine`."""
    httpd, url = make_server(host, port, workspace)
    print(f"Sparta Gen {__version__} running at {url}  (Ctrl+C to quit)")
    if not ff.available():
        print("warning: ffmpeg was not found — install it or `pip install imageio-ffmpeg`.")
    if open_browser:
        threading.Timer(0.6, _open_url, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
