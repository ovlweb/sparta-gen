"""Entry script for the frozen engine (PyInstaller): what the Sparta Gen app runs in the background.

    spartagen-engine engine --port P --token T --parent-pid PID   how the app starts it (no window)
    spartagen-engine --selftest [out.json]                         a test video through the one-click remix;
                                                                    exit code 0 = all good
    spartagen-engine make video.mp4 …                              any other spartagen command
"""

import os
import sys


def _workspace_log():
    root = os.environ.get("SPARTAGEN_HOME") or os.path.join(os.path.expanduser("~"), "SpartaGen")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "engine.log")


# The Windows build has no console (so no black window opens next to the app): print() goes to a log file in
# the workspace instead, which can be sent along with a bug report.
if sys.stdout is None or sys.stderr is None:
    try:
        _log = open(_workspace_log(), "w", encoding="utf-8", buffering=1)
    except OSError:
        _log = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = _log
    if sys.stderr is None:
        sys.stderr = _log


def _selftest() -> int:
    from spartagen.selftest import run
    i = sys.argv.index("--selftest")
    out = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("-") else None
    return 0 if run(out)["ok"] else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    from spartagen.cli import main
    sys.exit(main(sys.argv[1:] or ["--help"]))
