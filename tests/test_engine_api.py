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
    assert [g["name"] for g in cat["groups"]] == ["Bases", "My templates"]
    assert [t["id"] for t in cat["groups"][0]["templates"]] == ["extended", "stroll", "nanairo", "blend_s", "decline_cte"]
    v = call(engine, "/api/template/use", {"id": "nanairo"})             # a MIDI base: its MIDI, roles and parts
    assert v["variant"] == "midi" and v["template_id"] == "nanairo" and v["midi"]["template"] == "nanairo"
    assert v["template"]["name"] == "Sparta Nana-iro Base" and v["key"] == "F#"
    assert v["arrangement"]["key"] == "F#" and v["arrangement"]["bars"] == 89
    r = call(engine, "/api/template/save", {"name": "My Nana-iro edit"})
    assert r["saved"]["id"] == "my.my_nana_iro_edit"
    mine = next(g for g in r["catalog"]["groups"] if g["name"] == "My templates")["templates"]
    assert [t["id"] for t in mine] == ["my.my_nana_iro_edit"] and mine[0]["key"] == "F#"
    call(engine, "/api/template/delete", {"id": "my.my_nana_iro_edit"})
    call(engine, "/api/template/delete", {"id": "extended"}, expect=400)
    call(engine, "/api/template/use", {"id": "no_such_base"}, expect=400)
    assert call(engine, "/api/key", {"key": "F"})["key_mode"] == "manual"
    assert call(engine, "/api/template/use", {"id": "decline_cte"})["key"] == "F"
    assert call(engine, "/api/key", {"key": "auto"})["key_mode"] == "auto"
    v = call(engine, "/api/template/use", {"id": "extended"})
    assert v["template_id"] == "extended" and v["key"] == "D"
    # The Extended base comes with its audio: the remix is built on it as it is read (bar for bar), and it plays.
    assert v["variant"] == "base" and v["base_template"] == "" and v["base_structure"] == "detected"
    assert v["mix"]["base_path"].endswith("sparta_remix_extended.mp3") and v["base"]["bpm"] == 140.0
    assert [(x["name"], x["bars"]) for x in v["arrangement"]["sections"][3:6]] == \
        [("Chorus 2", 8), ("Epicness", 4), ("Chorus 3", 8)]                 # the Epicness at 0:34
    v = call(engine, "/api/template/use", {"id": "stroll"})                  # another base: that one goes
    assert v["variant"] == "midi" and not v["mix"].get("base_path") and v["base"] is None


def test_volumes_leave_an_edited_structure_alone(engine):
    """Turning the base or a MIDI channel up or down changes levels, not the parts the user arranged."""
    call(engine, "/api/template/use", {"id": "extended"})
    arr = call(engine, "/api/arrangement")
    arr["sections"] = arr["sections"][:2]                        # an edit: two parts only
    call(engine, "/api/arrangement", arr)
    v = call(engine, "/api/base/options", {"base_gain_db": -6.0})
    assert v["arrangement"]["custom"] and len(v["arrangement"]["sections"]) == 2
    assert v["mix"]["base_gain_db"] == -6.0
    lk = call(engine, "/api/look", {"mix": {"base_gain_db": -9.0}})     # the Look page's slider: the same level
    assert lk["mix"]["base_gain_db"] == -9.0 and call(engine, "/api/project")["mix"]["base_gain_db"] == -9.0
    v = call(engine, "/api/template/use", {"id": "stroll"})
    arr = call(engine, "/api/arrangement")
    lead = [t["gain_db"] for sec in arr["sections"] for t in sec["tracks"] if t["id"] == "midi_t6c4"]
    arr["sections"] = arr["sections"][:3]
    call(engine, "/api/arrangement", arr)
    mapping = {"t6c4": dict(v["midi"]["mapping"]["t6c4"], gain_db=-6.0)}
    v = call(engine, "/api/midi/mapping", {"mapping": mapping})
    assert v["arrangement"]["custom"] and len(v["arrangement"]["sections"]) == 3
    got = [t["gain_db"] for sec in call(engine, "/api/arrangement")["sections"] for t in sec["tracks"]
           if t["id"] == "midi_t6c4"]
    assert got == [g - 6.0 for g in lead[:len(got)]] and got
    mapping = {"t6c4": dict(mapping["t6c4"], role="pitch2")}       # another role: rebuilt from the MIDI
    assert len(call(engine, "/api/midi/mapping", {"mapping": mapping})["arrangement"]["sections"]) == 6


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


def test_a_video_gif_or_picture_of_your_own_as_the_background(engine, tmp_path):
    from spartagen import ffmpeg as ff
    gif = str(tmp_path / "loop.gif")
    ff.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=s=160x90:r=10:d=1", gif])
    lk = call(engine, "/api/look/background", {"path": gif})
    v = lk["video"]
    assert v["background"] == "file" and v["background_blur"] is False and os.path.isfile(v["background_file"])
    assert v["background_file"] != gif                      # a copy kept with the app's settings
    lk = call(engine, "/api/look", {"video": {"background_blur": True, "background_dim": 0.8}})
    assert lk["video"]["background_blur"] is True and lk["video"]["background_dim"] == 0.8
    wav = str(tmp_path / "sound.wav")
    ff.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=d=0.5", wav])
    call(engine, "/api/look/background", {"path": wav}, expect=400)        # no picture in it
    call(engine, "/api/look/background", {"path": str(tmp_path / "gone.png")}, expect=400)
    call(engine, "/api/look", {"video": {"background": "blur"}})


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
    v = call(engine, "/api/base/clear", {})                                  # yours goes: back on the Extended base
    assert v["template_id"] == "extended" and v["mix"]["base_path"].endswith("sparta_remix_extended.mp3")
    call(engine, "/api/base/open", {"path": str(tmp_path / "nope.wav")}, expect=400)


def test_exports_go_where_the_user_chose(engine, tmp_path, synthetic_source):
    call(engine, "/api/export/file", {"file": "", "dest": str(tmp_path)}, expect=400)
    r = call(engine, "/api/export/file", {"file": synthetic_source, "dest": str(tmp_path / "out" / "remix.mp4")})
    assert os.path.getsize(r["saved"]) == os.path.getsize(synthetic_source)
    call(engine, "/api/source/path", {"path": synthetic_source})
    call(engine, "/api/template/use", {"id": "extended"})
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
    first.session.save()
    assert App(root, resume=True).session.project.name == "Left it here"
    assert App(root).session.project.name != "Left it here"          # the web GUI starts fresh
    assert App(str(tmp_path / "empty"), resume=True).session.project.name   # nothing yet: a new project
    # Changed and not saved (the app was closed by force): it opens with the changes, still to save.
    again = App(root, resume=True)
    again.session.project.name = "Changed, not saved"
    again.session.autosave()
    last = App(root, resume=True).session
    assert last.project.name == "Changed, not saved" and last.dirty and last.saved


def test_every_change_is_kept_at_once_beside_the_saved_project(tmp_path):
    """The app can be closed by force (or crash): what was changed is kept at once — beside the saved project, so
    Don't save can still go back to it, and a project never saved leaves nothing behind."""
    httpd, url = make_server("127.0.0.1", 0, str(tmp_path / "work"), token=TOKEN, web_ui=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = url.rstrip("/")
    try:
        project = call(base, "/api/project")
        ws = project["workspace"]
        saved, auto = os.path.join(ws, "project.spartagen.json"), os.path.join(ws, "autosave.spartagen.json")
        assert not project["changed"] and not project["saved"]
        call(base, "/api/template/use", {"id": "blend_s"})
        assert json.load(open(auto, encoding="utf-8"))["midi"]["template"] == "blend_s"
        call(base, "/api/look", {"video": {"style": "neon"}})
        assert json.load(open(auto, encoding="utf-8"))["video"]["style"] == "neon" and not os.path.exists(saved)
        v = call(base, "/api/project")
        assert v["changed"] and not v["saved"]
        listed = call(base, "/api/projects")["projects"][0]
        assert listed["saved"] is False and listed["changed"] is True and listed["path"] == auto
        r = call(base, "/api/project/save", {})
        assert r["project"]["saved"] and not r["project"]["changed"] and os.path.isfile(saved)
        assert not os.path.exists(auto)
        # A change, then Don't save: back to the project as saved.
        call(base, "/api/look", {"video": {"style": "classic"}})
        assert call(base, "/api/project")["changed"]
        back = call(base, "/api/project/discard", {})
        assert back["workspace"] == ws and back["video"]["style"] == "neon" and not back["changed"]
        # A change undone is no change.
        call(base, "/api/look", {"video": {"style": "classic"}})
        call(base, "/api/look", {"video": {"style": "neon"}})
        assert not call(base, "/api/project")["changed"]
        # A new project, changed, never saved: Don't save leaves nothing of it.
        new = call(base, "/api/project/new", {})
        assert not new["changed"]
        call(base, "/api/project/name", {"name": "Throwaway"})
        assert call(base, "/api/project")["changed"]
        fresh = call(base, "/api/project/discard", {})
        assert not os.path.exists(new["workspace"]) and fresh["workspace"] != new["workspace"]
        # Out of Recent projects, with its folder.
        r = call(base, "/api/project/delete", {"path": saved})
        assert not os.path.exists(ws) and all(os.path.dirname(x["path"]) != ws for x in r["projects"])
        call(base, "/api/project/delete", {"path": str(tmp_path / "elsewhere" / "project.spartagen.json")}, expect=400)
        call(base, "/api/project/delete", {"path": str(tmp_path / "work")}, expect=400)
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
        assert lk["mix"]["mute_groups"] == ["quotes"]
        # A new project starts on the Extended base, its own audio under the remix.
        assert new["mix"]["base_path"].endswith("sparta_remix_extended.mp3") and new["template_id"] == "extended"
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
    assert 0.0 < max(wf["peaks"]) < 1.0 and min(wf["peaks"]) >= 0.0 and wf["duration"] > 5
    # One scale for the whole video: its loudest moment (the thumps) is full height, zoomed in or not.
    whole = call(engine, f"/api/waveform?start=0&end={wf['duration']}&n=400")
    assert max(whole["peaks"]) == 1.0
    assert max(call(engine, "/api/waveform?start=0.5&end=2.5&n=20")["peaks"]) == max(wf["peaks"])
    arr = call(engine, "/api/project")["arrangement"]
    assert arr["sections"][0]["start"] == 0.0 and arr["sections"][1]["start"] > 0


def test_a_pattern_as_blocks_and_back(engine, synthetic_source):
    """The block editor's round trip: a track's pattern as notes, the notes back as notation, and heard."""
    call(engine, "/api/project/new", {})
    call(engine, "/api/source/path", {"path": synthetic_source})
    arr = call(engine, "/api/arrangement")
    si = next(i for i, sec in enumerate(arr["sections"]) if sec["kind"] == "chorus")
    tr = next(t for t in arr["sections"][si]["tracks"] if t["kind"] == "drum")
    b = call(engine, "/api/pattern/blocks", {"track": tr})
    assert b["mode"] == "index" and b["notes"] and b["loop"] >= 16 and b["slots"]
    w = call(engine, "/api/pattern/write", {"notes": b["notes"], "mode": b["mode"], "length": b["pickup"] + b["loop"]})
    assert w["steps"] == b["pickup"] + b["loop"] and w["text"]
    melody = call(engine, "/api/pattern/write", {"notes": [{"start": 0, "dur": 2, "value": 0},
                                                           {"start": 4, "dur": 4, "value": 7}], "length": 16})
    assert melody == {"text": "0* __ 7*** ________", "mode": "semitone", "steps": 16.0}
    call(engine, "/api/pattern/write", {"notes": [{"start": 0, "dur": 1, "value": 10}], "mode": "index"}, expect=400)
    call(engine, "/api/pattern/listen", {"track": tr, "section": si}, expect=400)     # (no samples cut yet)
    wait(engine, call(engine, "/api/analyze", {}))
    heard = call(engine, "/api/pattern/listen", {"track": dict(tr, pattern="text:" + w["text"], mode="index"),
                                                 "section": si})
    assert os.path.isfile(heard["audio"]) and os.path.getsize(heard["audio"]) > 10000


def test_updates_are_found_downloaded_and_refused_where_they_cannot_go(engine, tmp_path, monkeypatch):
    from spartagen import update
    apk = tmp_path / "SpartaGen-9.0.0-Android.apk"
    apk.write_bytes(b"PK" + b"\0" * 3000)
    release = {"tag_name": "v9.0.0", "name": "9.0", "prerelease": False, "draft": False, "body": "Big news",
               "html_url": "https://github.com/ovlweb/sparta-gen/releases/tag/v9.0.0",
               "assets": [{"name": apk.name, "size": apk.stat().st_size, "browser_download_url": apk.as_uri()}]}
    monkeypatch.setattr(update, "fetch_releases", lambda: [release])
    info = call(engine, "/api/update?platform=android")
    assert info["newer"] is True and info["latest"] == "9.0.0" and info["notes"] == "Big news"
    assert call(engine, "/api/update?platform=windows")["latest"] is None            # no Windows file in it
    job = wait(engine, call(engine, "/api/update/download", {"platform": "android"}))
    assert job["status"] == "done" and os.path.getsize(job["result"]["file"]) == apk.stat().st_size
    call(engine, "/api/update/install", {"app": str(tmp_path), "executable": str(tmp_path / "x"), "pid": 1},
         expect=400)                                                              # not an installed app

    def offline():
        raise ValueError("could not reach GitHub to look for updates (offline)")
    monkeypatch.setattr(update, "fetch_releases", offline)
    call(engine, "/api/update?platform=android", expect=400)


def _raw(base, path):
    req = urllib.request.Request(base + path)
    req.add_header("X-Sparta-Token", TOKEN)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.headers["Content-Type"], r.read()


def test_samples_are_cut_from_several_videos(engine, synthetic_source, tmp_path):
    from test_sources import _second_video
    call(engine, "/api/project/new", {})
    call(engine, "/api/source/path", {"path": synthetic_source})
    other = _second_video(str(tmp_path))
    call(engine, "/api/source/add", {"path": str(tmp_path / "nowhere.mp4")}, expect=400)
    v = call(engine, "/api/source/add", {"path": other})
    assert [(x["id"], x["name"], x["analyzed"]) for x in v["sources"]] == [
        ("main", os.path.basename(synthetic_source), False), ("v2", "other.mp4", False)]
    call(engine, "/api/source/add", {"path": other}, expect=400)                    # (once)
    assert wait(engine, call(engine, "/api/analyze", {}))["status"] == "done"
    job = wait(engine, call(engine, "/api/samples/from", {"role": "pitch2", "source": "v2"}))
    assert job["status"] == "done"
    bank = job["result"]
    p2 = next(x for x in bank["samples"] if x["id"] == "pitch2")
    assert p2["source"] == "v2" and p2["source_path"] == other and p2["thumb_url"].endswith("&source=v2")
    assert bank["from"]["pitch2"] == "v2" and bank["from"]["pitch1"] == "main"
    assert [x["id"] for x in bank["sources"]] == ["main", "v2"] and bank["sources"][1]["analyzed"]
    cand = bank["source_candidates"]["v2"]["pitch"][0]
    assert cand["audio_url"].endswith("&source=v2") and cand["end"] <= bank["sources"][1]["duration"] + 0.01
    kind, wav = _raw(engine, cand["audio_url"])
    assert wav[:4] == b"RIFF"
    kind, jpg = _raw(engine, "/api/thumb?t=0.2&w=64&h=36&source=v2")
    assert kind == "image/jpeg" and jpg[:2] == b"\xff\xd8"
    wf = call(engine, "/api/waveform?start=0&end=1&n=16&source=v2")
    assert len(wf["peaks"]) == 16 and abs(wf["duration"] - bank["sources"][1]["duration"]) < 0.05
    call(engine, "/api/samples/from", {"role": "pitch2", "source": "v7"}, expect=400)
    call(engine, "/api/samples/from", {"role": "everything", "source": "v2"}, expect=400)
    v = call(engine, "/api/source/remove", {"id": "v2"})
    assert [x["id"] for x in v["sources"]] == ["main"]
    assert all(x["source"] == "main" for x in call(engine, "/api/samples")["samples"])


def test_a_template_is_exported_as_a_zip_and_imported(engine, tmp_path):
    import zipfile
    dest = str(tmp_path / "shared" / "Blend S.zip")
    assert call(engine, "/api/template/export", {"id": "blend_s", "dest": dest})["saved"] == dest
    with zipfile.ZipFile(dest) as z:
        assert sorted(z.namelist()) == ["blend_s.mid", "sparta_blend_s_base.spartabase.json"]
    r = call(engine, "/api/template/import", {"path": dest})
    assert r["saved"]["id"] == "my.sparta_blend_s_base" and r["saved"]["midi"] == "sparta_blend_s_base/blend_s.mid"
    mine = next(g for g in r["catalog"]["groups"] if g["name"] == "My templates")["templates"]
    assert "my.sparta_blend_s_base" in [t["id"] for t in mine]
    call(engine, "/api/template/use", {"id": "my.sparta_blend_s_base"})
    v = call(engine, "/api/project")
    assert v["variant"] == "midi" and v["midi"]["template"] == "my.sparta_blend_s_base"
    call(engine, "/api/template/export", {"id": "nope", "dest": dest}, expect=400)
    call(engine, "/api/template/export", {"id": "blend_s"}, expect=400)
    call(engine, "/api/template/delete", {"id": "my.sparta_blend_s_base"})


def test_don_t_save_never_deletes_a_folder_outside_the_workspace(tmp_path):
    """A project file can name any folder as its own: letting its changes go deletes nothing outside SpartaGen's."""
    httpd, url = make_server("127.0.0.1", 0, str(tmp_path / "work"), token=TOKEN, web_ui=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = url.rstrip("/")
    try:
        precious = tmp_path / "my documents"
        precious.mkdir()
        (precious / "keep.txt").write_text("mine")
        odd = tmp_path / "odd.spartagen.json"
        odd.write_text(json.dumps({"name": "Odd", "workspace": str(precious)}))
        call(base, "/api/project/open", {"path": str(odd)})
        call(base, "/api/project/name", {"name": "Odd, changed"})
        assert call(base, "/api/project")["changed"]
        call(base, "/api/project/discard", {})
        assert (precious / "keep.txt").read_text() == "mine"
        call(base, "/api/project/delete", {"path": str(precious / "autosave.spartagen.json")}, expect=400)
        assert precious.is_dir()
    finally:
        httpd.shutdown()
