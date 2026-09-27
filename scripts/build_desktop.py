"""Build the self-contained desktop app with PyInstaller.

    pip install pyinstaller numpy scipy pillow yt-dlp imageio-ffmpeg
    python scripts/build_desktop.py

Produces dist/SpartaGen-<os>-<arch>.zip containing a one-folder app with
ffmpeg bundled (taken from $SPARTAGEN_BUNDLE_FFMPEG, imageio-ffmpeg, or PATH).
Windows: SpartaGen.exe (console window shows the log and the local URL).
macOS:   SpartaGen.app (no console; use the Quit button in the app).
Linux:   SpartaGen/SpartaGen.
"""

from __future__ import annotations

import os
import platform
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
    if sys.platform == "darwin":
        args += ["--windowed", "--osx-bundle-identifier", "gen.sparta.remix"]
    else:
        args += ["--console"]
    args.append(os.path.join("packaging", "launcher.py"))
    subprocess.check_call(args)

    system = {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux")
    arch = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    out = os.path.join("dist", f"SpartaGen-{system}-{arch}.zip")
    target = os.path.join("dist", "SpartaGen.app" if sys.platform == "darwin" else "SpartaGen")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _dirs, files in os.walk(target):
            for f in files:
                full = os.path.join(folder, f)
                info = zipfile.ZipInfo.from_file(full, os.path.relpath(full, "dist"))
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)
    print(f"built {out}")


if __name__ == "__main__":
    main()
