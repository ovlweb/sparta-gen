"""Double-click entry point (desktop shortcut / the desktop app): start the GUI.

The desktop apps open in their own window (pywebview: Edge WebView2 on Windows, WebKit on macOS);
`--browser` (or no window toolkit) opens the default browser instead.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    from .server import serve
    frozen = getattr(sys, "frozen", False)
    window = ("--window" in sys.argv or os.environ.get("SPARTAGEN_WINDOW") == "1"
              or (frozen and "--browser" not in sys.argv and os.environ.get("SPARTAGEN_WINDOW") != "0"))
    host = os.environ.get("SPARTAGEN_HOST", "127.0.0.1")
    port = int(os.environ.get("SPARTAGEN_PORT", "0"))
    serve(host=host, port=port, open_browser="--no-browser" not in sys.argv, window=window)


if __name__ == "__main__":
    main()
