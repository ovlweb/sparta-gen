"""The engine inside the Android app (the APK built from ``app/android/`` in the repository).

The app is the same Flutter app as on the desktop: the Java side starts Python (Chaquopy) in a foreground
service and calls :func:`start` with a secret token; the app then talks to ``http://127.0.0.1:<port>/``
with that token, like the desktop app talks to its engine process. ffmpeg ships in the APK as
``libffmpeg.so`` (Android only lets an app run programs from its native library folder), found here and
handed to the engine through ``SPARTAGEN_FFMPEG``.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

_server = None
_thread: Optional[threading.Thread] = None
_lock = threading.Lock()


def configure(home: str, native_lib_dir: str = "", cache_dir: str = "") -> dict:
    """Point the engine at the app's folders and its bundled ffmpeg (before anything imports it)."""
    os.environ.setdefault("SPARTAGEN_HOME", os.path.join(home, "SpartaGen"))
    ffmpeg = os.path.join(native_lib_dir, "libffmpeg.so") if native_lib_dir else ""
    if ffmpeg and os.path.isfile(ffmpeg):
        os.environ["SPARTAGEN_FFMPEG"] = ffmpeg
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        os.environ.setdefault("TMPDIR", cache_dir)
    # Phones have less memory than desktops: keep fewer decoded clips in the video renderer.
    os.environ.setdefault("SPARTAGEN_MEMORY_MB", "320")
    return {"home": os.environ["SPARTAGEN_HOME"], "ffmpeg": os.environ.get("SPARTAGEN_FFMPEG")}


def start(home: str, native_lib_dir: str = "", cache_dir: str = "", token: str = "") -> int:
    """Start (or find running) the engine for the app; returns its port. With a token (the app's), every
    call must carry it and there is no web page; the project worked on last is opened again."""
    global _server, _thread
    with _lock:
        if _server is not None and _thread is not None and _thread.is_alive():
            return int(_server.server_address[1])
        if _server is not None:                 # stopped by the app's Quit: free its port
            _server.server_close()
        configure(home, native_lib_dir, cache_dir)
        from .gui.server import make_server
        httpd, _url = make_server("127.0.0.1", 0, token=token or None, web_ui=not token, resume=True)
        _server = httpd
        _thread = threading.Thread(target=httpd.serve_forever, name="spartagen-http", daemon=True)
        _thread.start()
        print(f"SpartaGen engine at {_url} (ffmpeg: {os.environ.get('SPARTAGEN_FFMPEG', 'PATH')})")
        return int(httpd.server_address[1])


def running() -> bool:
    return _server is not None and _thread is not None and _thread.is_alive()


def stop() -> None:
    """Stop the server (the app's Quit, or the service ending)."""
    global _server, _thread
    with _lock:
        httpd, _server, _thread = _server, None, None
    if httpd is not None:
        try:
            httpd.shutdown()
        finally:
            httpd.server_close()


if __name__ == "__main__":        # `python -m spartagen.android [home]`: the app's engine on a desktop
    import sys
    import time
    home = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser("~"), "SpartaGen-android")
    print("port", start(home))
    try:
        while running():
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop()
