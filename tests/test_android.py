"""The engine as the Android app starts it (spartagen/android.py), run on the desktop."""

import json
import os
import shutil
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


def test_the_app_engine_serves_the_web_app_and_stops(app_dirs):
    home, lib, cache = app_dirs
    port = android.start(str(home), str(lib), str(cache))
    assert android.running() and android.start(str(home), str(lib), str(cache)) == port   # started once
    assert os.environ["SPARTAGEN_HOME"] == os.path.join(str(home), "SpartaGen")
    assert os.environ["SPARTAGEN_MEMORY_MB"] == "320" and os.path.isdir(cache)
    if ff.available():
        assert os.environ["SPARTAGEN_FFMPEG"] == str(lib / "libffmpeg.so")
    html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read().decode()
    assert "SpartaAndroid" in urllib.request.urlopen(f"http://127.0.0.1:{port}/static/app.js", timeout=10).read().decode()
    assert "Make my Sparta Remix" in html
    st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=10).read())
    assert st["project"]["workspace"].startswith(os.path.join(str(home), "SpartaGen"))
    android.stop()
    assert not android.running()
    port2 = android.start(str(home), str(lib), str(cache))                 # the app opened again
    assert urllib.request.urlopen(f"http://127.0.0.1:{port2}/api/status", timeout=10).status == 200
