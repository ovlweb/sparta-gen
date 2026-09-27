"""Double-click entry point (desktop shortcut / PyInstaller app): start the GUI."""

from __future__ import annotations

import os
import sys


def main() -> None:
    from .server import serve
    window = "--window" in sys.argv or os.environ.get("SPARTAGEN_WINDOW") == "1"
    host = os.environ.get("SPARTAGEN_HOST", "127.0.0.1")
    port = int(os.environ.get("SPARTAGEN_PORT", "0"))
    serve(host=host, port=port, open_browser="--no-browser" not in sys.argv, window=window)


if __name__ == "__main__":
    main()
