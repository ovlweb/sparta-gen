"""The engine as the iOS app runs it (spartagen/ios.py): ffmpeg as a function of the app's own process.

iOS apps cannot start programs, so FFmpegKit runs ffmpeg command lines inside the app.  Here a stand-in does what
the app's function does — one command line per call, everything ffmpeg prints into a log file, no stdin or
stdout — so the engine's command lines, pipes and threads are tested the way the app runs them: once as a C
function called through ctypes (like the app's), once as a plain Python function."""

import json
import os
import shutil
import subprocess
import sysconfig
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from spartagen import ffmpeg as ff
from spartagen import ios, selftest

STAND_IN = r"""
#include <fcntl.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

/* What the iOS app's ffmpeg function does, with the ffmpeg program: one command line, what it prints into
   log_path (FFmpegKit keeps stdout and stderr in one log), no stdin. */
int sg_ffmpeg(int argc, const char **argv, const char *log_path) {
    const char *exe = getenv("SG_TEST_FFMPEG");
    pid_t pid = fork();
    if (pid == 0) {
        int null = open("/dev/null", O_RDONLY);
        int log = open(log_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        dup2(null, 0);
        dup2(log, 1);
        dup2(log, 2);
        char **args = calloc((size_t)argc + 1, sizeof(char *));
        args[0] = (char *)exe;
        for (int i = 1; i < argc; i++) args[i] = (char *)argv[i];
        execv(exe, args);
        _exit(127);
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}
"""


@pytest.fixture(scope="module")
def real_ffmpeg():
    ff.use_function(None)
    if not ff.available():
        pytest.skip("ffmpeg not available")
    return ff.ffmpeg_path()


@pytest.fixture(scope="module")
def c_function(real_ffmpeg, tmp_path_factory):
    """The stand-in, compiled: its address, as the app hands it to the engine."""
    cc = shutil.which(sysconfig.get_config_var("CC") or "cc") or shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("no C compiler")
    d = tmp_path_factory.mktemp("stand-in")
    (d / "stand_in.c").write_text(STAND_IN)
    lib = d / "libstandin.so"
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(lib), str(d / "stand_in.c")], check=True)
    os.environ["SG_TEST_FFMPEG"] = real_ffmpeg
    import ctypes
    handle = ctypes.CDLL(str(lib))
    return handle, ctypes.cast(handle.sg_ffmpeg, ctypes.c_void_p).value


def python_function(exe):
    def call(argv, log_path):
        with open(log_path, "wb") as log:
            return subprocess.run([exe] + list(argv[1:]), stdin=subprocess.DEVNULL, stdout=log, stderr=log).returncode
    return call


@pytest.fixture(params=["ctypes", "python"])
def as_function(request, real_ffmpeg):
    if request.param == "ctypes":
        _handle, address = request.getfixturevalue("c_function")
        ff.use_function(ios.native_ffmpeg(address))
    else:
        ff.use_function(python_function(real_ffmpeg))
    try:
        yield request.param
    finally:
        ff.use_function(None)


def finishes(fn, seconds=120):
    """Run ``fn`` on a thread; it has to end (a stuck pipe would hang it) — returns what it raised, if anything."""
    out = {}

    def run():
        try:
            fn()
        except BaseException as exc:            # noqa: BLE001 - reported to the test
            out["error"] = exc
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "ffmpeg as a function hung"
    return out.get("error")


def test_probe_decode_and_encode_through_the_function(as_function, tmp_path):
    assert ff.is_function() and ff.ffmpeg_path() == "ffmpeg" and ff.ffprobe_path() is None
    assert ff.version().startswith("ffmpeg version")
    wav = tmp_path / "tone.wav"
    ff.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=2", str(wav)])
    video = ff.make_test_card(str(tmp_path / "card.mp4"), 2.0, str(wav))
    info = ff.probe(video)                               # parsed from `ffmpeg -i`, which prints into the log
    assert info.has_video and info.has_audio and abs(info.duration - 2.0) < 0.2
    audio = ff.decode_audio(video, sr=22050)             # pipe:1 → a file
    assert abs(audio.size - 2 * 22050) < 2000 and float(np.abs(audio).max()) > 0.1
    frames = ff.read_frames(video, 0.5, 0.4, 25, 64, 36)
    assert frames.shape == (10, 36, 64, 3)
    out = tmp_path / "encoded.mp4"
    with ff.VideoWriter(str(out), 64, 36, 25, audio_path=str(wav)) as w:   # pipe:0 ← a named pipe
        for i in range(50):
            w.write(np.full((36, 64, 3), i * 5, dtype=np.uint8))
    enc = ff.probe(str(out))
    assert enc.has_video and enc.has_audio and abs(enc.duration - 2.0) < 0.2


def test_a_failing_encoder_says_so_instead_of_hanging(as_function, tmp_path):
    def write_to_a_missing_folder():
        with ff.VideoWriter(str(tmp_path / "no such folder" / "x.mp4"), 64, 36, 25) as w:
            for _ in range(200):
                w.write(np.zeros((36, 64, 3), dtype=np.uint8))
    assert isinstance(finishes(write_to_a_missing_folder), ff.FFmpegError)
    # an encoder that gets no frames at all ends too (with or without a file)
    error = finishes(lambda: ff.VideoWriter(str(tmp_path / "empty.mp4"), 64, 36, 25).close())
    assert error is None or isinstance(error, ff.FFmpegError)


def test_the_one_click_remix_runs_with_ffmpeg_as_a_function(as_function):
    if as_function != "python":
        pytest.skip("once is enough")
    report = selftest.run(quality="preview", log=lambda m: None)
    assert report["ok"], report.get("error")


KEYS = ("SPARTAGEN_HOME", "SPARTAGEN_MEMORY_MB", "TMPDIR", "SSL_CERT_FILE")


def call(port, path, token=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        req.add_header("X-Sparta-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_ios_engine_answers_only_the_app(c_function, tmp_path):
    _handle, address = c_function
    saved = {k: os.environ.pop(k, None) for k in KEYS}
    try:
        home, cache, info = tmp_path / "support", tmp_path / "tmp", tmp_path / "engine.json"
        port = ios.start(str(home), str(cache), "s3cret", address, str(info))
        assert ios.running() and ios.start(str(home), str(cache), "s3cret", address) == port   # started once
        assert json.loads(info.read_text()) == {"port": port, "token": "s3cret"}
        assert os.environ["SPARTAGEN_HOME"] == os.path.join(str(home), "SpartaGen")
        assert os.environ["TMPDIR"] == str(cache) and os.path.isdir(cache)
        assert call(port, "/api/status")[0] == 401
        code, body = call(port, "/api/status", "s3cret")
        st = json.loads(body)
        assert code == 200 and st["ffmpeg"] and st["ffmpeg_version"].startswith("ffmpeg version")
        ios.stop()
        assert not ios.running()
    finally:
        ios.stop()
        ff.use_function(None)
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
