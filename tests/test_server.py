"""The GUI's JSON API, exercised over real HTTP."""

import json
import threading
import time
import urllib.request

import pytest

from spartagen.gui.server import make_server


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    httpd, url = make_server("127.0.0.1", 0, str(tmp_path_factory.mktemp("home")))
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield url.rstrip("/")
    httpd.shutdown()


def call(base, path, body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, headers=headers or {}, method="POST" if data else "GET")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def wait(base, job):
    while job["status"] == "running":
        time.sleep(0.3)
        job = call(base, f"/api/job/{job['id']}")
    assert job["status"] == "done", job.get("error")
    return job["result"]


def test_static_and_status(base_url):
    html = urllib.request.urlopen(base_url + "/").read().decode()
    assert "SPARTA" in html
    st = call(base_url, "/api/status")
    assert "ffmpeg" in st and st["project"]["source"] is None


def test_catalog_and_parse(base_url):
    cat = call(base_url, "/api/patterns")
    assert any(p["id"] == "chorus.standard" for p in cat["sections"]["chorus"])
    r = call(base_url, "/api/pattern/parse", {"text": "0*__0*__1*__1*__-2*__-2*__1*__1*__"})
    assert r["ok"] and r["length"] == 32


def test_full_flow(base_url, synthetic_source):
    raw = open(synthetic_source, "rb").read()
    r = call(base_url, "/api/source/upload", raw=raw, headers={"X-Filename": "my%20source.mp4"})
    assert r["project"]["source"]["name"] == "my source.mp4"
    bank = wait(base_url, call(base_url, "/api/analyze", {}))
    assert any(s["id"] == "pitch1" for s in bank["samples"])
    # Swap pitch2 to another candidate, then check the processed audio is served.
    bank = call(base_url, "/api/samples/select", {"role": "pitch2", "index": 1})
    wav = urllib.request.urlopen(base_url + "/api/sample/pitch1.wav").read()
    assert wav[:4] == b"RIFF"
    arr = call(base_url, "/api/arrangement/variant", {"variant": "classic", "options": {}})
    assert arr["variant"] == "classic"
    # Trim the arrangement for speed and render the audio preview.
    arr["sections"] = arr["sections"][:3]
    call(base_url, "/api/arrangement", arr)
    res = wait(base_url, call(base_url, "/api/render", {"quality": "audio"}))
    assert res["file_url"]
    # Range request on the result (what <video>/<audio> seeking uses).
    req = urllib.request.Request(base_url + res["file_url"], headers={"Range": "bytes=0-99"})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206 and len(r.read()) == 100


def test_media_path_traversal_is_blocked(base_url):
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base_url + "/media/..%2F..%2Fetc%2Fpasswd")
    assert e.value.code in (400, 404)
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base_url + "/file?path=/etc/passwd")
    assert e.value.code == 403


def test_base_upload_maps_and_fits(base_url, tmp_path):
    from tests.test_base import make_base, SR
    from spartagen.audio import dsp
    wav = tmp_path / "base.wav"
    dsp.write_wav(str(wav), make_base(), SR)
    r = call(base_url, "/api/base/upload", raw=wav.read_bytes(), headers={"X-Filename": "toy%20base.wav"})
    assert r["base"] and abs(r["base"]["bpm"] - 140) < 0.05 and r["variant"] == "base"
    assert r["mix"]["base_mode"] == "remix" and abs(r["mix"]["base_offset"] - 0.25) < 0.02
    arr = call(base_url, "/api/arrangement")
    assert arr["variant"] == "base" and arr["total_bars"] == r["base"]["bars"]
    r = call(base_url, "/api/mix", {"clear_base": True})
    # Your base goes; the remix is back on the Extended base, its own audio under it.
    assert r["template_id"] == "extended" and r["mix"]["base_path"].endswith("sparta_remix_extended.mp3")
    assert r["base"]["bpm"] == 140.0 and r["base_path"] == r["mix"]["base_path"]


def test_one_click_auto_remix(tmp_path_factory, synthetic_source):
    """Source in, remix out: samples cut automatically, arranged and rendered by one call."""
    httpd, url = make_server("127.0.0.1", 0, str(tmp_path_factory.mktemp("auto-home")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = url.rstrip("/")
    try:
        with pytest.raises(urllib.error.HTTPError):             # nothing loaded yet
            call(base, "/api/auto", {"quality": "audio"})
        call(base, "/api/source/upload", raw=open(synthetic_source, "rb").read(), headers={"X-Filename": "src.mp4"})
        res = wait(base, call(base, "/api/auto", {"quality": "audio"}))
        assert res["file_url"] and res["events"] > 100 and res["duration"] > 20
        project = call(base, "/api/project")
        assert project["analyzed"] and project["outputs"]["audio"]["file"] == res["file"]
        samples = call(base, "/api/samples")["samples"]
        assert {"pitch1", "chorus_a", "kick"} <= {s["id"] for s in samples}
    finally:
        httpd.shutdown()


def test_copy_final_file_goes_to_the_suggested_folder_when_none_is_typed(tmp_path, monkeypatch):
    """The web app's "Copy" with its folder box left empty used to answer "nothing to save"."""
    import urllib.error
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    httpd, url = make_server("127.0.0.1", 0, str(tmp_path / "work"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = url.rstrip("/")
    try:
        render = tmp_path / "remix-720p.mp4"
        render.write_bytes(b"not really a video")
        r = call(base, "/api/save_as", {"file": str(render), "dest": ""})
        assert r["saved"] == str(tmp_path / "home" / "Videos" / "remix-720p.mp4")
        r = call(base, "/api/save_as", {"file": str(render), "dest": str(tmp_path / "out")})    # a folder
        assert r["saved"] == str(tmp_path / "out" / "remix-720p.mp4")
        r = call(base, "/api/save_as", {"file": str(render), "dest": str(tmp_path / "My remix.mp4")})
        assert r["saved"] == str(tmp_path / "My remix.mp4") and (tmp_path / "My remix.mp4").read_bytes()
        with pytest.raises(urllib.error.HTTPError) as err:            # nothing rendered yet: say so
            call(base, "/api/save_as", {"file": "", "dest": ""})
        assert b"render the remix first" in err.value.read()
    finally:
        httpd.shutdown()
