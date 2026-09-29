"""Build the SpartaGen desktop app: the native (Flutter) app with its engine inside.

    pip install pyinstaller numpy scipy pillow yt-dlp imageio-ffmpeg
    python scripts/build_desktop.py            # build
    python scripts/build_desktop.py --test     # build and test it (see below)

Needs Flutter on PATH; on Linux also clang, cmake, ninja, pkg-config, libgtk-3-dev and libmpv-dev.

1. The engine: a PyInstaller folder (packaging/engine.py → spartagen-engine) with numpy, scipy, yt-dlp and
   ffmpeg (from $SPARTAGEN_BUNDLE_FFMPEG, imageio-ffmpeg or PATH) inside.  On Windows it has no console
   window.
2. --test: its self-test — a test video through the one-click remix, then saved as MP4 and MP3 the way the
   app saves, with the bundled ffmpeg — and the engine started the way the app starts it, asked for its status
   with and without its token.
3. The app: `flutter build <windows|macos|linux> --release`.
4. The engine goes inside the app: SpartaGen/engine/ (Windows, Linux), SpartaGen.app/Contents/Resources/engine/
   (macOS, then signed again ad hoc).
5. --test: the engine inside the app started the app's way again, then the packaged app itself
   (SPARTAGEN_SMOKE_REPORT): it must find and start its engine, then quits.  A crash shows the engine's output
   (every thread's Python traceback) and, on macOS, the crash report.
6. dist/SpartaGen-<version>-<Windows|macOS|Linux>-<arch>.zip
"""

from __future__ import annotations

import http.client
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
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
        "--add-data", f"{os.path.join(ROOT, 'spartagen', 'templates')}{sep}spartagen/templates",
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


def serve_test_engine(folder: str, where: str) -> None:
    """The engine started the way the app starts it (``engine --port … --token … --parent-pid …``) and asked for
    its status, which runs ffmpeg and loads yt-dlp; without the token it must refuse.  (The self-test drives the
    engine's server inside its own process, not the app's way in.)"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = os.urandom(16).hex()
    home = tempfile.mkdtemp(prefix="sg-home-")
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", SPARTAGEN_HOME=home)
    env.pop("SPARTAGEN_ENGINE", None)
    args = ["engine", "--port", str(port), "--token", token, "--parent-pid", str(os.getpid())]
    print("$", engine_exe(folder), " ".join(args).replace(token, "…"), flush=True)
    t0 = time.time()
    proc = subprocess.Popen([engine_exe(folder)] + args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output: list[bytes] = []
    reader = threading.Thread(target=lambda: output.extend(iter(proc.stdout.readline, b"")), daemon=True)
    reader.start()
    web = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # (never through a proxy)
    base = f"http://127.0.0.1:{port}"

    def call(path: str, with_token: bool = True, body: bytes | None = None):
        req = urllib.request.Request(base + path, data=body, method="POST" if body is not None else "GET",
                                     headers={"X-Sparta-Token": token} if with_token else {})
        with web.open(req, timeout=120) as r:
            return json.loads(r.read())

    status, error = None, None
    try:
        deadline = time.time() + 180
        while status is None and time.time() < deadline and proc.poll() is None:
            try:
                status = call("/api/status")
            except (OSError, ValueError, http.client.HTTPException):        # not listening yet
                time.sleep(0.3)
        if status is None:
            error = (f"it stopped (exit code {proc.returncode})" if proc.poll() is not None
                     else "it did not answer in 180 s")
        elif status.get("version") != version() or not status.get("ffmpeg") or not status.get("yt_dlp"):
            error = f"its status is wrong: {status}"
        else:
            for _ in range(2):                                              # (it keeps answering)
                call("/api/status")
            try:
                call("/api/status", with_token=False)
                error = "it answered without its token"
            except urllib.error.HTTPError as e:
                if e.code != 401:
                    error = f"without its token it said {e.code}, not 401"
    except (OSError, ValueError, http.client.HTTPException) as e:
        error = f"{e.__class__.__name__}: {e}" + (f" (exit code {proc.returncode})" if proc.poll() is not None else "")
    finally:
        try:
            call("/api/quit", body=b"{}")                                   # how the app stops it
        except (OSError, ValueError, http.client.HTTPException):
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        reader.join(timeout=5)
    if error:
        print(b"".join(output).decode("utf-8", "replace")[-20000:])
        log = os.path.join(home, "engine.log")                              # (Windows: no console)
        if os.path.isfile(log):
            with open(log, encoding="utf-8", errors="replace") as fh:
                print(fh.read()[-20000:])
        if proc.returncode < 0:                                             # it died of a signal
            crash_report("spartagen-engine", t0)
        sys.exit(f"the engine does not work the way the app starts it ({where}): {error}")
    print(f"the engine the way the app starts it ({where}): answers in {time.time() - t0:.1f} s, "
          f"{status['ffmpeg_version']}, yt-dlp {'yes' if status['yt_dlp'] else 'no'}")


def crash_report(name: str, since: float) -> None:
    """macOS: print the crash report of the program ``name`` written since ``since`` (the system writes it a few
    seconds after the crash), in short: the exception, why, and the crashed thread's calls."""
    if not MACOS:
        return
    folders = [os.path.expanduser("~/Library/Logs/DiagnosticReports"), "/Library/Logs/DiagnosticReports"]
    deadline = time.time() + 60
    while time.time() < deadline:
        found = [os.path.join(d, f) for d in folders if os.path.isdir(d) for f in os.listdir(d)
                 if f.startswith(name) and os.path.getmtime(os.path.join(d, f)) >= since - 5]
        if found:
            time.sleep(2)                                                   # (let it finish writing)
            for path in sorted(found, key=os.path.getmtime)[-2:]:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                print(f"== crash report {path}")
                try:
                    print(_crash_summary(text))
                except (ValueError, KeyError, IndexError, TypeError):
                    print(text[:30000])
            return
        time.sleep(2)
    print(f"(no crash report for {name} in {' or '.join(folders)})")


def _crash_summary(ips: str) -> str:
    """The parts of a macOS crash report (.ips: a JSON line, then JSON) that say what happened."""
    data = json.loads(ips.partition("\n")[2])
    images = data.get("usedImages", [])
    exc = data.get("exception", {})
    lines = [f"exception: {exc.get('type')} {exc.get('signal')} {exc.get('subtype', '')} {exc.get('codes', '')}",
             f"termination: {data.get('termination', {}).get('indicator', data.get('termination'))}",
             f"parent: {data.get('parentProc')}  cpu: {data.get('cpuType')}  os: {data.get('osVersion')}"]
    if data.get("asi"):
        lines.append(f"application info: {data['asi']}")
    crashed = data.get("faultingThread", 0)
    for i, thread in enumerate(data.get("threads", [])):
        frames = thread.get("frames", [])
        if i != crashed:                                                    # other threads: where they were
            top = next((f for f in frames if f.get("symbol")), frames[0] if frames else {})
            lines.append(f"thread {i} {thread.get('name', '')}: {top.get('symbol', '?')}")
            continue
        lines.append(f"thread {i} crashed {thread.get('name', '')} {thread.get('queue', '')}")
        for f in frames[:48]:
            index = f.get("imageIndex", -1)
            image = images[index].get("name", "?") if 0 <= index < len(images) else "?"
            symbol = f.get("symbol")
            lines.append(f"    {image:28} " + (f"{symbol} + {f.get('symbolLocation', 0)}" if symbol
                                                else hex(f.get("imageOffset", 0))))
    return "\n".join(lines)


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
        return os.path.join(APP, "build", "macos", "Build", "Products", "Release", "SpartaGen.app")
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
        out = os.path.join(DIST, "SpartaGen.app")
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
    if not WINDOWS:                                    # Linux: "add SpartaGen to the applications menu"
        shutil.copy2(os.path.join(ROOT, "packaging", "linux", "add-to-menu.sh"), out)
    return out


def engine_in_app(app_dir: str) -> str:
    return os.path.join(app_dir, "Contents", "Resources", "engine") if MACOS else os.path.join(app_dir, "engine")


def app_exe(app_dir: str) -> str:
    if MACOS:
        return os.path.join(app_dir, "Contents", "MacOS", "SpartaGen")
    return os.path.join(app_dir, "SpartaGen.exe" if WINDOWS else "spartagen")


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
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env)
    try:
        code = proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = "timeout"
    data = json.load(open(report, encoding="utf-8")) if os.path.isfile(report) else {}
    log = data.pop("log", "")
    print(json.dumps(data, indent=1))
    if code != 0 or not data.get("ok"):
        if log:
            print("the engine's output:\n" + log)
        if isinstance(code, int) and code < 0:
            crash_report("SpartaGen", t0)
        if "exit code -" in str(data.get("error", "")):                    # the engine died of a signal
            crash_report("spartagen-engine", t0)
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
        serve_test_engine(engine, "as built")
    app_dir = assemble(build_app(), engine)
    if test:
        serve_test_engine(engine_in_app(app_dir), "inside the app")
        smoke_test_app(app_dir)
    print(f"built {make_zip(app_dir)}")


if __name__ == "__main__":
    main()
