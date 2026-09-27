"""Entry script for the frozen desktop app (PyInstaller)."""

import os
import sys

# Windowed builds have no console: give print() somewhere harmless to write.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from spartagen.gui.launch import main  # noqa: E402

if __name__ == "__main__":
    main()
