"""Build the self-contained desktop app with PyInstaller.

    pip install pyinstaller numpy scipy pillow yt-dlp imageio-ffmpeg pywebview
    python scripts/build_desktop.py            # build
    python scripts/build_desktop.py --test     # build, then run the built app's self-test

Produces dist/SpartaGen-<version>-<os>-<arch>.zip: a one-folder app with ffmpeg bundled (taken from
$SPARTAGEN_BUNDLE_FFMPEG, imageio-ffmpeg, or PATH).
Windows: SpartaGen\\SpartaGen.exe — opens in its own window (Edge WebView2).
macOS:   SpartaGen.app             — opens in its own window (WebKit).
Linux:   SpartaGen/SpartaGen       — opens in the default browser (the terminal shows the log).
Every build runs `SpartaGen --selftest`: a test video through the one-click remix, with the bundled ffmpeg.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_ffmpeg() -> str:
    env = os.environ.get("SPARTAGEN_BUNDLE_FFMPEG")
    if env and os.path.isfile(env):
        return env
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    sys.exit("No ffmpeg to bundle: pip install imageio-ffmpeg or set SPARTAGEN_BUNDLE_FFMPEG.")


def version() -> str:
    with open(os.path.join(ROOT, "spartagen", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__ = "([^"]+)"', fh.read()).group(1)


def app_executable() -> str:
    if sys.platform == "darwin":
        return os.path.join("dist", "SpartaGen.app", "Contents", "MacOS", "SpartaGen")
    return os.path.join("dist", "SpartaGen", "SpartaGen.exe" if os.name == "nt" else "SpartaGen")


def selftest() -> None:
    """Run the built app's self-test (the report goes to a file: windowed apps have no console)."""
    report = os.path.abspath(os.path.join("dist", "selftest.json"))
    code = subprocess.call([os.path.abspath(app_executable()), "--selftest", report])
    data = json.load(open(report, encoding="utf-8")) if os.path.isfile(report) else {}
    print(json.dumps(data, indent=1))
    if code != 0 or not data.get("ok"):
        sys.exit(f"self-test of the built app failed (exit {code})")
    print("self-test passed")


def main() -> None:
    os.chdir(ROOT)
    sep = ";" if os.name == "nt" else ":"
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    staging = tempfile.mkdtemp(prefix="sg-ffmpeg-")
    ff_src = find_ffmpeg()
    ff_dst = os.path.join(staging, exe)
    shutil.copy2(ff_src, ff_dst)
    os.chmod(ff_dst, 0o755)
    print(f"bundling ffmpeg from {ff_src}")

    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", "SpartaGen",
        "--add-data", f"spartagen/gui/static{sep}spartagen/gui/static",
        "--add-binary", f"{ff_dst}{sep}bin",
        "--collect-submodules", "spartagen",
        "--hidden-import", "scipy.signal", "--hidden-import", "scipy.fft",
        "--exclude-module", "matplotlib", "--exclude-module", "tkinter", "--exclude-module", "pytest",
        "--exclude-module", "imageio_ffmpeg",  # ffmpeg itself is bundled in bin/ above
    ]
    try:                                        # the app's own window (Windows, macOS)
        import webview  # type: ignore  # noqa: F401
        args += ["--hidden-import", "webview"]
        has_window = sys.platform in ("darwin", "win32")
    except ImportError:
        has_window = False
        print("pywebview not installed: the app will open in the browser")
    if sys.platform == "darwin":
        args += ["--windowed", "--osx-bundle-identifier", "gen.sparta.remix",
                 "--icon", os.path.join("packaging", "icon.icns")]
    elif sys.platform == "win32":
        args += ["--windowed" if has_window else "--console", "--icon", os.path.join("packaging", "icon.ico")]
    else:
        args += ["--console"]
    args.append(os.path.join("packaging", "launcher.py"))
    subprocess.check_call(args)

    if "--test" in sys.argv:
        selftest()

    system = {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux")
    arch = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64").replace("aarch64", "arm64")
    out = os.path.join("dist", f"SpartaGen-{version()}-{system}-{arch}.zip")
    target = os.path.join("dist", "SpartaGen.app" if sys.platform == "darwin" else "SpartaGen")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(target):
            for name in dirs + files:                      # keep the .app's symlinks as symlinks
                full = os.path.join(folder, name)
                rel = os.path.relpath(full, "dist")
                if os.path.islink(full):
                    info = zipfile.ZipInfo(rel)
                    info.create_system = 3
                    info.external_attr = 0o120777 << 16
                    z.writestr(info, os.readlink(full))
                    continue
                if name in dirs:
                    continue
                info = zipfile.ZipInfo.from_file(full, rel)
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)
    print(f"built {out}")


if __name__ == "__main__":
    main()
