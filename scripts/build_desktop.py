"""Build the Sparta Gen desktop app: the native (Flutter) app with its engine inside.

    pip install pyinstaller numpy scipy pillow yt-dlp imageio-ffmpeg
    python scripts/build_desktop.py            # build
    python scripts/build_desktop.py --test     # build and test it (see below)

Needs Flutter on PATH; on Linux also clang, cmake, ninja, pkg-config, libgtk-3-dev and libmpv-dev.

1. The engine: a PyInstaller folder (packaging/engine.py → spartagen-engine) with numpy, scipy, yt-dlp and
   ffmpeg (from $SPARTAGEN_BUNDLE_FFMPEG, imageio-ffmpeg or PATH) inside.  On Windows it has no console
   window.
2. --test: its self-test — a test video through the one-click remix, then saved as MP4 and MP3 the way the
   app saves, with the bundled ffmpeg.
3. The app: `flutter build <windows|macos|linux> --release`.
4. The engine goes inside the app: SpartaGen/engine/ (Windows, Linux), Sparta Gen.app/Contents/Resources/engine/
   (macOS, then signed again ad hoc).
5. --test: the packaged app starts (SPARTAGEN_SMOKE_REPORT): it must find and start its engine, then quits.
6. dist/SpartaGen-<version>-<Windows|macOS|Linux>-<arch>.zip
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
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
BUILD = os.path.join(ROOT, "build", "desktop")
DIST = os.path.join(ROOT, "dist")
WINDOWS, MACOS = sys.platform == "win32", sys.platform == "darwin"
SYSTEM = "Windows" if WINDOWS else "macOS" if MACOS else "Linux"


def version() -> str:
    with open(os.path.join(ROOT, "spartagen", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__ = "([^"]+)"', fh.read()).group(1)


def arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(m, m)


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


def run(cmd: list[str], **kw) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, **kw)


# ── 1. the engine ──
def build_engine() -> str:
    sep = ";" if WINDOWS else ":"
    staging = tempfile.mkdtemp(prefix="sg-ffmpeg-")
    ff_dst = os.path.join(staging, "ffmpeg.exe" if WINDOWS else "ffmpeg")
    ff_src = find_ffmpeg()
    shutil.copy2(ff_src, ff_dst)
    os.chmod(ff_dst, 0o755)
    print(f"bundling ffmpeg from {ff_src}")
    work = os.path.join(BUILD, "engine")
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "spartagen-engine",
        "--distpath", os.path.join(work, "dist"), "--workpath", os.path.join(work, "work"), "--specpath", work,
        "--add-data", f"{os.path.join(ROOT, 'spartagen', 'gui', 'static')}{sep}spartagen/gui/static",
        "--add-binary", f"{ff_dst}{sep}bin",
        "--collect-submodules", "spartagen",
        "--hidden-import", "scipy.signal", "--hidden-import", "scipy.fft",
        "--exclude-module", "matplotlib", "--exclude-module", "tkinter", "--exclude-module", "pytest",
        "--exclude-module", "imageio_ffmpeg", "--exclude-module", "webview",
    ]
    if WINDOWS:
        args += ["--noconsole", "--icon", os.path.join(ROOT, "packaging", "icon.ico")]
    if MACOS:
        args += ["--osx-bundle-identifier", "gen.sparta.remix.engine"]
    args.append(os.path.join(ROOT, "packaging", "engine.py"))
    run(args, cwd=ROOT)
    return os.path.join(work, "dist", "spartagen-engine")


def engine_exe(folder: str) -> str:
    return os.path.join(folder, "spartagen-engine.exe" if WINDOWS else "spartagen-engine")


# ── 2. its self-test ──
def selftest_engine(folder: str) -> None:
    report = os.path.join(BUILD, "selftest.json")
    if os.path.exists(report):
        os.remove(report)
    env = dict(os.environ, SPARTAGEN_HOME=tempfile.mkdtemp(prefix="sg-home-"))
    code = subprocess.call([engine_exe(folder), "--selftest", report], env=env)
    data = json.load(open(report, encoding="utf-8")) if os.path.isfile(report) else {}
    print(json.dumps(data, indent=1))
    if code != 0 or not data.get("ok"):
        sys.exit(f"self-test of the engine failed (exit {code})")
    print("engine self-test passed")


# ── 3. the app ──
def flutter() -> str:
    exe = shutil.which("flutter.bat" if WINDOWS else "flutter") or shutil.which("flutter")
    if not exe:
        sys.exit("Flutter is not on PATH (https://docs.flutter.dev/get-started/install)")
    return exe


def build_app() -> str:
    target = {"Windows": "windows", "macOS": "macos", "Linux": "linux"}[SYSTEM]
    fl = flutter()
    run([fl, "pub", "get"], cwd=APP)
    run([fl, "build", target, "--release", f"--build-name={flutter_version()[0]}",
         f"--build-number={flutter_version()[1]}"], cwd=APP)
    if WINDOWS:
        return os.path.join(APP, "build", "windows", "x64", "runner", "Release")
    if MACOS:
        return os.path.join(APP, "build", "macos", "Build", "Products", "Release", "Sparta Gen.app")
    return os.path.join(APP, "build", "linux", "x64" if arch() == "x64" else "arm64", "release", "bundle")


def flutter_version() -> tuple[str, str]:
    """The app's version and build number, from pubspec.yaml (1.0.0-rc.1+100001)."""
    with open(os.path.join(APP, "pubspec.yaml"), encoding="utf-8") as fh:
        v = re.search(r"^version:\s*(\S+)", fh.read(), re.M).group(1)
    name, _, number = v.partition("+")
    return name, number or "1"


# ── 4. the engine inside the app ──
def assemble(app_built: str, engine: str) -> str:
    os.makedirs(DIST, exist_ok=True)
    if MACOS:
        out = os.path.join(DIST, "Sparta Gen.app")
        if os.path.exists(out):
            shutil.rmtree(out)
        shutil.copytree(app_built, out, symlinks=True)
        shutil.copytree(engine, os.path.join(out, "Contents", "Resources", "engine"), symlinks=True)
        # The bundle changed after Flutter signed it: sign it again (ad hoc; see README for Gatekeeper).
        run(["codesign", "--force", "--deep", "--sign", "-", out])
        return out
    out = os.path.join(DIST, "SpartaGen")
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(app_built, out, symlinks=True)
    shutil.copytree(engine, os.path.join(out, "engine"), symlinks=True)
    if not WINDOWS:                                    # Linux: "add Sparta Gen to the applications menu"
        shutil.copy2(os.path.join(ROOT, "packaging", "linux", "add-to-menu.sh"), out)
    return out


def app_exe(app_dir: str) -> str:
    if MACOS:
        return os.path.join(app_dir, "Contents", "MacOS", "Sparta Gen")
    return os.path.join(app_dir, "SpartaGen.exe" if WINDOWS else "sparta-gen")


# ── 5. the app starts its engine ──
def smoke_test_app(app_dir: str) -> None:
    report = os.path.join(BUILD, "app-smoke.json")
    if os.path.exists(report):
        os.remove(report)
    env = dict(os.environ, SPARTAGEN_SMOKE_REPORT=report, SPARTAGEN_HOME=tempfile.mkdtemp(prefix="sg-home-"))
    env.pop("SPARTAGEN_ENGINE", None)                  # the bundled engine, not a development one
    cmd = [app_exe(app_dir)]
    if not WINDOWS and not MACOS and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a"] + cmd                 # Linux CI: a virtual screen
    print("$", " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, env=env)
    try:
        code = proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = "timeout"
    data = json.load(open(report, encoding="utf-8")) if os.path.isfile(report) else {}
    print(json.dumps(data, indent=1))
    if code != 0 or not data.get("ok"):
        sys.exit(f"the packaged app did not start its engine (exit {code})")
    time.sleep(2)                                      # its engine quits with it
    print("the packaged app starts its bundled engine")


# ── 6. the zip ──
def make_zip(app_dir: str) -> str:
    out = os.path.join(DIST, f"SpartaGen-{version()}-{SYSTEM}-{arch()}.zip")
    if os.path.exists(out):
        os.remove(out)
    if MACOS:                                          # ditto keeps the bundle's symlinks and signature
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app_dir, out])
        return out
    base = os.path.dirname(app_dir)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(app_dir):
            for name in dirs + files:
                full = os.path.join(folder, name)
                rel = os.path.relpath(full, base)
                if os.path.islink(full):
                    info = zipfile.ZipInfo(rel)
                    info.create_system = 3
                    info.external_attr = 0o120777 << 16
                    z.writestr(info, os.readlink(full))
                    continue
                if name in dirs:
                    continue
                info = zipfile.ZipInfo.from_file(full, rel)      # keeps the executables executable
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)
    return out


def main() -> None:
    test = "--test" in sys.argv
    os.makedirs(BUILD, exist_ok=True)
    engine = build_engine()
    if test:
        selftest_engine(engine)
    app_dir = assemble(build_app(), engine)
    if test:
        smoke_test_app(app_dir)
    print(f"built {make_zip(app_dir)}")


if __name__ == "__main__":
    main()
