"""The engine as the Android app starts it (spartagen/android.py), run on the desktop."""

import json
import os
import shutil
import urllib.error
import urllib.request

import pytest

from spartagen import android
from spartagen import ffmpeg as ff


KEYS = ("SPARTAGEN_HOME", "SPARTAGEN_FFMPEG", "SPARTAGEN_MEMORY_MB", "TMPDIR")


@pytest.fixture
def app_dirs(tmp_path):
    saved = {k: os.environ.pop(k, None) for k in KEYS}      # the engine sets these for the app
    lib = tmp_path / "lib"
    lib.mkdir()
    if ff.available():                      # the APK ships ffmpeg as lib/<abi>/libffmpeg.so
        shutil.copy(ff.ffmpeg_path(), lib / "libffmpeg.so")
    try:
        yield tmp_path / "files", lib, tmp_path / "cache"
    finally:
        android.stop()
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def call(port, path, token=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        req.add_header("X-Sparta-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_app_engine_answers_only_the_app_and_stops(app_dirs):
    home, lib, cache = app_dirs
    port = android.start(str(home), str(lib), str(cache), "s3cret")
    assert android.running() and android.start(str(home), str(lib), str(cache), "s3cret") == port   # started once
    assert os.environ["SPARTAGEN_HOME"] == os.path.join(str(home), "SpartaGen")
    assert os.environ["SPARTAGEN_MEMORY_MB"] == "320" and os.path.isdir(cache)
    if ff.available():
        assert os.environ["SPARTAGEN_FFMPEG"] == str(lib / "libffmpeg.so")
    assert call(port, "/api/status")[0] == 401                  # other apps on the phone get nothing
    assert call(port, "/", "s3cret")[0] == 404                   # and there is no web page: the app is native
    code, body = call(port, "/api/status", "s3cret")
    assert code == 200
    st = json.loads(body)
    assert st["project"]["workspace"].startswith(os.path.join(str(home), "SpartaGen"))
    android.stop()
    assert not android.running()
    port2 = android.start(str(home), str(lib), str(cache), "an0ther")    # the app opened again: a new secret
    assert call(port2, "/api/status", "an0ther")[0] == 200
    assert call(port2, "/api/status", "s3cret")[0] == 401


def test_without_a_token_it_is_the_web_app_for_a_desktop_browser(app_dirs):
    home, lib, cache = app_dirs
    port = android.start(str(home), str(lib), str(cache))
    code, html = call(port, "/")
    assert code == 200 and b"Make my Sparta Remix" in html
