"""Entry script for the frozen desktop app (PyInstaller).

    SpartaGen                        the app, in its own window (the browser where no window can open)
    SpartaGen --browser              the app in the default browser
    SpartaGen --selftest [out.json]  a test video through the one-click remix; exit code 0 = all good
"""

import os
import sys

# Windowed builds have no console: give print() somewhere harmless to write.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


def _selftest() -> int:
    from spartagen.selftest import run
    i = sys.argv.index("--selftest")
    out = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("-") else None
    return 0 if run(out)["ok"] else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    from spartagen.gui.launch import main
    main()
