"""Write a release's version into the engine and the app before they are built.

    python scripts/set_version.py v1.0.0-rc2            # writes it
    python scripts/set_version.py --check v1.0.0-rc2    # only says whether it can be written

The Release workflow runs it with the version it releases (the pushed tag, or the one typed in Run workflow), so
every app is built as the version it is released as.  The updater compares that version with the releases on
GitHub: an app that called itself older than it is would be offered its own release again and again.

- spartagen/__init__.py: ``__version__ = "1.0.0rc2"`` — the engine's version, which the app shows and the updater
  compares (Python's way of writing it: never a "-" in it, so the release's file names lose it cleanly);
- app/pubspec.yaml: ``version: 1.0.0-rc.2+1000062`` — the app's version and its build number, which is Android's
  versionCode.  That has to go up from release to release (Android installs an APK over the app only then), so it
  comes from the version: major·1000000 + minor·10000 + patch·100 + alpha n, beta 30+n, rc 60+n or the release 99.

Versions: v1.0.0, v1.0.0-rc2 (or -rc.2), v1.0.0-beta1, v1.0.0-alpha1 — the kinds Release marks as pre-releases.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.?(\d+))?$")
STAGES = {"alpha": ("a", 0), "beta": ("b", 30), "rc": ("rc", 60)}
RELEASE = 99
MAX_BUILD = 2_100_000_000                  # (the largest versionCode Android takes)


def forms(tag: str) -> tuple[str, str, int]:
    """The engine's version, the app's and its build number for a release's version
    (v1.0.0-rc2 → 1.0.0rc2, 1.0.0-rc.2, 1000062)."""
    m = TAG.match((tag or "").strip())
    if not m:
        raise ValueError(f"{tag!r} is not a release's version: v1.0.0, v1.0.0-rc2, v1.0.0-beta1 or v1.0.0-alpha1")
    major, minor, patch = (int(x) for x in m.group(1, 2, 3))
    stage, n = m.group(4), int(m.group(5) or 0)
    if minor > 99 or patch > 99:
        raise ValueError(f"{tag}: the second and third numbers go up to 99 (two digits each in the build number)")
    if n > 29:
        raise ValueError(f"{tag}: up to {stage}29 (the build number has room for 30 of each)")
    numbers = f"{major}.{minor}.{patch}"
    build = major * 1_000_000 + minor * 10_000 + patch * 100
    if stage is None:
        engine, app, build = numbers, numbers, build + RELEASE
    else:
        short, base = STAGES[stage]
        engine, app, build = f"{numbers}{short}{n}", f"{numbers}-{stage}.{n}", build + base + n
    if build > MAX_BUILD:
        raise ValueError(f"{tag}: too big for Android's versionCode")
    return engine, app, build


def write(tag: str, root: str = ROOT) -> tuple[str, str, int]:
    """Writes the version into the engine and the app under ``root``; returns what it wrote."""
    engine, app, build = forms(tag)
    _replace(os.path.join(root, "spartagen", "__init__.py"), r'^__version__ = "[^"]*"$', f'__version__ = "{engine}"')
    _replace(os.path.join(root, "app", "pubspec.yaml"), r"^version:[ \t]*\S+$", f"version: {app}+{build}")
    return engine, app, build


def _replace(path: str, pattern: str, line: str) -> None:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    text, found = re.subn(pattern, line, text, count=1, flags=re.M)
    if not found:
        raise ValueError(f"{path} has no line like {pattern!r} to write the version in")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    args = [a for a in argv if a != "--check"]
    if len(args) != 1:
        print("usage: python scripts/set_version.py [--check] v1.0.0-rc2", file=sys.stderr)
        return 2
    try:
        engine, app, build = forms(args[0]) if check else write(args[0])
    except ValueError as e:
        print(("::error::" if os.environ.get("GITHUB_ACTIONS") else "error: ") + str(e), file=sys.stderr)
        return 1
    print(f"{args[0]}: the engine is {engine}, the app {app} (build {build})"
          + (" — not written (--check)" if check else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
