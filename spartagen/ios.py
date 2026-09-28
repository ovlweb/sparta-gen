"""The engine inside the iOS app (``app/ios/`` in the repository).

iOS apps cannot start programs, so everything runs inside the app: Python is embedded in it
(``app/ios/Runner/SpartaGenEngine.m`` starts it and calls :func:`start` with a secret token), and ffmpeg is
FFmpegKit — ffmpeg compiled into the app — which the engine runs its command lines through as a function
(:func:`spartagen.ffmpeg.use_function`).  Like the Android app, the Flutter side then talks to
``http://127.0.0.1:<port>/`` with the token.
"""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
import threading
from typing import Callable, Optional

_server = None
_thread: Optional[threading.Thread] = None
_lock = threading.Lock()


def native_ffmpeg(address: int) -> Callable[[list, str], int]:
    """The app's ffmpeg function (``int f(int argc, const char **argv, const char *log_path)`` at ``address``)
    as a Python callable.  ctypes lets the engine's other threads run while ffmpeg works."""
    proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), ctypes.c_char_p)
    fn = proto(address)

    def call(argv: list, log_path: str) -> int:
        args = (ctypes.c_char_p * len(argv))(*[os.fsencode(a) for a in argv])
        return int(fn(len(argv), args, os.fsencode(log_path)))

    return call


def configure(home: str, cache_dir: str, ffmpeg_function: int) -> dict:
    """Point the engine at the app's folders and its ffmpeg (before a project is opened)."""
    os.environ.setdefault("SPARTAGEN_HOME", os.path.join(home, "SpartaGen"))
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        os.environ["TMPDIR"] = cache_dir
        tempfile.tempdir = None
    # Phones have less memory than desktops: keep fewer decoded clips in the video renderer.
    os.environ.setdefault("SPARTAGEN_MEMORY_MB", "320")
    try:                        # OpenSSL on iOS has no certificate store: certifi's (video links over HTTPS)
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
    from . import ffmpeg

    ffmpeg.use_function(native_ffmpeg(ffmpeg_function))
    return {"home": os.environ["SPARTAGEN_HOME"]}


def start(home: str, cache_dir: str, token: str, ffmpeg_function: int, info_file: Optional[str] = None) -> int:
    """Start (or find running) the engine for the app; returns its port.  Every call must carry the token;
    the project worked on last is opened again.  ``info_file`` (debug builds): where the port and token are
    written for the simulator test."""
    global _server, _thread
    with _lock:
        if _server is not None and _thread is not None and _thread.is_alive():
            return int(_server.server_address[1])
        if _server is not None:                 # stopped: free its port
            _server.server_close()
        configure(home, cache_dir, ffmpeg_function)
        from .gui.server import make_server
        httpd, url = make_server("127.0.0.1", 0, token=token, web_ui=False, resume=True)
        _server = httpd
        _thread = threading.Thread(target=httpd.serve_forever, name="spartagen-http", daemon=True)
        _thread.start()
        port = int(httpd.server_address[1])
        if info_file:
            with open(info_file, "w", encoding="utf-8") as fh:
                json.dump({"port": port, "token": token}, fh)
        print(f"SpartaGen engine at {url} (ffmpeg: FFmpegKit)", flush=True)
        return port


def running() -> bool:
    return _server is not None and _thread is not None and _thread.is_alive()


def stop() -> None:
    """Stop the server."""
    global _server, _thread
    with _lock:
        httpd, _server, _thread = _server, None, None
    if httpd is not None:
        try:
            httpd.shutdown()
        finally:
            httpd.server_close()
