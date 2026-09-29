"""The engine behind the native app: token, headless mode and the native API, over real HTTP."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from spartagen import midi as M
from spartagen.gui.server import make_server

TOKEN = "t0ken"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    os.environ["SPARTAGEN_HOME"] = str(home)
    httpd, url = make_server("127.0.0.1", 0, str(home / "work"), token=TOKEN, web_ui=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield url.rstrip("/")
    httpd.shutdown()
    os.environ.pop("SPARTAGEN_HOME", None)


def call(base, path, body=None, token=TOKEN, expect=200):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET")
    if token:
        req.add_header("X-Sparta-Token", token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            assert r.status == expect
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        assert e.code == expect, e.read()
        return json.loads(e.read() or b"{}")


def wait(base, job):
    while job["status"] == "running":
        time.sleep(0.2)
        job = call(base, f"/api/job/{job['id']}")
    return job


def test_a_body_sent_in_chunks_is_read(engine):
    """Dart's HttpClient (and other HTTP/1.1 clients) may send a body in chunks, without its length."""
    import http.client
    from urllib.parse import urlparse
    u = urlparse(engine)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    body = json.dumps({"name": "Chunked name"}).encode()
    conn.request("POST", "/api/project/name", body=iter([body[:7], body[7:]]), encode_chunked=True,
                 headers={"X-Sparta-Token": TOKEN, "Content-Type": "application/json"})
    r = conn.getresponse()
    assert r.status == 200
    assert json.loads(r.read())["name"] == "Chunked name"


def test_the_engine_needs_its_token_and_has_no_web_page(engine):
    call(engine, "/api/status", token=None, expect=401)
    call(engine, "/api/status", token="wrong", expect=401)
    assert call(engine, "/api/status")["project"]["key"] == "D"
    call(engine, "/", expect=404)


def test_templates_are_listed_used_saved_and_deleted(engine):
    cat = call(engine, "/api/templates")
    assert {g["name"] for g in cat["groups"]} >= {"Standard bases", "Wiki bases", "My templates"}
    v = call(engine, "/api/template/use", {"id": "nemesis"})
    assert v["variant"] == "nemesis" and v["key"] == "D#" and v["template"]["name"].startswith("Nemesis")
    assert v["arrangement"]["key"] == "D#" and v["arrangement"]["bars"] == 79
    r = call(engine, "/api/template/save", {"name": "My Nemesis edit"})
    assert r["saved"]["id"] == "my.my_nemesis_edit"
    mine = next(g for g in r["catalog"]["groups"] if g["name"] == "My templates")["templates"]
    assert [t["id"] for t in mine] == ["my.my_nemesis_edit"] and mine[0]["key"] == "D#"
    call(engine, "/api/template/delete", {"id": "my.my_nemesis_edit"})
    call(engine, "/api/template/delete", {"id": "extended"}, expect=400)
    call(engine, "/api/template/use", {"id": "no_such_base"}, expect=400)
    assert call(engine, "/api/key", {"key": "F"})["key_mode"] == "manual"
    assert call(engine, "/api/template/use", {"id": "drlasp"})["key"] == "F"
    assert call(engine, "/api/key", {"key": "auto"})["key_mode"] == "auto"
    call(engine, "/api/template/use", {"id": "unextended"})


def test_midi_base_open_and_map(engine, tmp_path):
    from test_midi import classic_base
    path = M.write_midi(str(tmp_path / "b.mid"), classic_base(), bpm=150)
    v = call(engine, "/api/midi/open", {"path": path})
    assert v["variant"] == "midi" and v["midi"]["summary"]["bpm"] == 150
    parts = v["midi"]["summary"]["parts"]
    drums = next(p["id"] for p in parts if p["drums"])
    assert v["midi"]["mapping"][drums]["role"] == "drums" and "chords" in v["midi"]["roles"]
    v = call(engine, "/api/midi/mapping", {"mapping": {drums: {"role": "off"}}, "auto_percussion": False})
    assert v["midi"]["mapping"][drums]["role"] == "off" and not v["midi"]["auto_percussion"]
    call(engine, "/api/midi/mapping", {"mapping": {drums: {"role": "banjo"}}}, expect=400)
    assert call(engine, "/api/midi/clear", {})["midi"] is None


def test_look_and_sound(engine):
    lk = call(engine, "/api/look")
    assert "xleth" in lk["styles"] and "lofi" in lk["fx_presets"] and lk["video"]["style"] == "classic"
    lk = call(engine, "/api/look", {"video": {"style": "neon", "shake": 0.5}, "mix": {"fx_preset": "big_room"}})
    assert lk["video"]["style"] == "neon" and lk["video"]["border"] == "glow" and lk["video"]["shake"] == 0.5
    assert lk["mix"]["reverb"] == 2.0 and lk["mix"]["risers"] is True
    lk = call(engine, "/api/look", {"video": {"style": "clean"}, "replace_video": True, "mix": {"fx_preset": "clean"},
                                    "replace_fx": True})
    assert lk["video_set"] == {"style": "clean"} and lk["mix"]["reverb"] == 0.6
    call(engine, "/api/look", {"video": {"style": "vaporwave"}}, expect=400)
    call(engine, "/api/look", {"mix": {"fx_preset": "dubstep"}}, expect=400)


def test_base_file_by_path_with_a_template(engine, tmp_path):
    from test_base import make_base
    from spartagen.audio import base as B
    from spartagen.audio import dsp
    path = str(tmp_path / "base.wav")
    dsp.write_wav(path, make_base(root_midi=63), B.SR)
    job = wait(engine, call(engine, "/api/base/open", {"path": path, "template": "kaosz"}))
    assert job["status"] == "done", job
    v = job["result"]
    assert v["variant"] == "base" and v["base"]["bpm"] == pytest.approx(140.0, abs=0.1)
    assert v["key"] == "D#" and v["base_template"] == "kaosz"
    v = call(engine, "/api/base/options", {"structure": "template", "base_gain_db": -6.0})
    assert v["base_structure"] == "template" and v["mix"]["base_gain_db"] == -6.0
    assert call(engine, "/api/base/clear", {})["base"] is None
    call(engine, "/api/base/open", {"path": str(tmp_path / "nope.wav")}, expect=400)


def test_exports_go_where_the_user_chose(engine, tmp_path, synthetic_source):
    call(engine, "/api/export/file", {"file": "", "dest": str(tmp_path)}, expect=400)
    r = call(engine, "/api/export/file", {"file": synthetic_source, "dest": str(tmp_path / "out" / "remix.mp4")})
    assert os.path.getsize(r["saved"]) == os.path.getsize(synthetic_source)
    call(engine, "/api/source/path", {"path": synthetic_source})
    call(engine, "/api/template/use", {"id": "unextended"})
    r = call(engine, "/api/export/midi", {"dest": str(tmp_path / "remix.mid")})
    assert M.read_midi(r["saved"]).bpm == pytest.approx(140.0, abs=0.01)
    job = wait(engine, call(engine, "/api/export/pack", {"dest": str(tmp_path / "packs")}))
    assert job["status"] == "done", job
    assert os.path.isdir(job["result"]["saved"]) and job["result"]["count"] > 5
    job = wait(engine, call(engine, "/api/export/pack", {"dest": str(tmp_path / "pack.zip"), "video": False}))
    assert job["status"] == "done" and os.path.getsize(tmp_path / "pack.zip") > 1000


def test_a_job_can_be_cancelled(engine, synthetic_source):
    call(engine, "/api/source/path", {"path": synthetic_source})
    job = call(engine, "/api/render", {"quality": "preview"})
    call(engine, f"/api/job/{job['id']}/cancel", {})
    job = wait(engine, job)
    assert job["status"] == "cancelled"


@pytest.mark.skipif(os.name == "nt", reason="POSIX parent test")
def test_the_engine_quits_with_its_app(tmp_path):
    env = dict(os.environ, PYTHONPATH=ROOT, SPARTAGEN_HOME=str(tmp_path))
    shell = subprocess.Popen(["bash", "-c", f'"{sys.executable}" -m spartagen engine --port 0 --token x '
                                            f'--parent-pid $$ & wait'], stdout=subprocess.PIPE, env=env, text=True)
    line = shell.stdout.readline()
    assert line.startswith("SPARTAGEN_ENGINE_READY port=")
    port = int(line.strip().split("=")[1])
    url = f"http://127.0.0.1:{port}/api/status"
    req = urllib.request.Request(url, headers={"X-Sparta-Token": "x"})
    assert urllib.request.urlopen(req, timeout=10).status == 200
    shell.send_signal(signal.SIGKILL)                       # the app dies
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(req, timeout=2)
        except (urllib.error.URLError, ConnectionError, OSError):
            break
        time.sleep(0.5)
    else:
        pytest.fail("the engine outlived its app")


def test_the_engine_opens_the_project_worked_on_last(tmp_path):
    from spartagen.gui.server import App
    root = str(tmp_path / "work")
    first = App(root)
    first.session.project.name = "Left it here"
    first.session.project.save()
    assert App(root, resume=True).session.project.name == "Left it here"
    assert App(root).session.project.name != "Left it here"          # the web GUI starts fresh
    assert App(str(tmp_path / "empty"), resume=True).session.project.name   # nothing yet: a new project


def test_every_change_is_saved_at_once(tmp_path):
    """The app can be closed by force (or crash): what was changed is already in the project file."""
    httpd, url = make_server("127.0.0.1", 0, str(tmp_path / "work"), token=TOKEN, web_ui=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = url.rstrip("/")
    try:
        project = call(base, "/api/project")
        call(base, "/api/template/use", {"id": "extended"})
        path = os.path.join(project["workspace"], "project.spartagen.json")
        saved = json.load(open(path, encoding="utf-8"))
        assert saved["variant"] == "extended"
        call(base, "/api/look", {"video": {"style": "neon"}})
        assert json.load(open(path, encoding="utf-8"))["video"]["style"] == "neon"
    finally:
        httpd.shutdown()


def test_a_new_project_keeps_the_look_and_sound_chosen_last(tmp_path):
    """Changes to the look are permanent: a new project starts with them, and renders with them."""
    httpd, url = make_server("127.0.0.1", 0, str(tmp_path / "work"), token=TOKEN, web_ui=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = url.rstrip("/")
    try:
        call(base, "/api/look", {"video": {"style": "neon", "shake": 0.4},
                                 "mix": {"fx_preset": "lofi", "volumes": {"pitches": -6, "drums": 3},
                                         "mute_groups": ["quotes"]}})
        first = call(base, "/api/project")["workspace"]
        new = call(base, "/api/project/new", {})
        assert new["workspace"] != first
        assert new["video"] == {"style": "neon", "shake": 0.4}               # what the render reads
        lk = call(base, "/api/look")
        assert lk["video"]["style"] == "neon" and lk["video"]["shake"] == 0.4 and lk["video"]["border"] == "glow"
        assert lk["mix"]["fx_preset"] == "lofi" and lk["mix"]["volumes"] == {"pitches": -6.0, "drums": 3.0}
        assert lk["mix"]["mute_groups"] == ["quotes"] and "base_path" not in new["mix"]
        assert lk["volume_groups"]["pitches"] == "Pitches" and lk["volume_range"] == [-24.0, 12.0]
    finally:
        httpd.shutdown()
    from spartagen.gui.server import App
    assert App(str(tmp_path / "work")).session.project.video["style"] == "neon"   # the next start too


def test_a_still_of_the_remix_and_the_sound_of_the_source_are_served(engine, synthetic_source):
    """The Look page's live preview (a picture of the remix at any time) and the sample cutter's waveform."""
    call(engine, "/api/source/path", {"path": synthetic_source})
    call(engine, "/api/frame?t=1", expect=400)                              # nothing cut yet
    assert wait(engine, call(engine, "/api/analyze", {}))["status"] == "done"
    req = urllib.request.Request(engine + "/api/frame?t=6.5&w=320&h=180")
    req.add_header("X-Sparta-Token", TOKEN)
    with urllib.request.urlopen(req, timeout=120) as r:
        png = r.read()
        assert r.headers["Content-Type"] == "image/png"
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    import struct
    assert struct.unpack(">II", png[16:24]) == (320, 180)
    wf = call(engine, "/api/waveform?start=0.5&end=2.5&n=100")
    assert (wf["start"], wf["end"]) == (0.5, 2.5) and len(wf["peaks"]) == 100
    assert max(wf["peaks"]) == 1.0 and min(wf["peaks"]) >= 0.0 and wf["duration"] > 5
    arr = call(engine, "/api/project")["arrangement"]
    assert arr["sections"][0]["start"] == 0.0 and arr["sections"][1]["start"] > 0
