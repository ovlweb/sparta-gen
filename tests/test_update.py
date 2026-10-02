"""Updates from inside the app: which release is newer, its file for each platform, and putting it in place."""

import os
import stat
import subprocess
import sys
import time
import zipfile

import pytest

from spartagen import update as U


def _release(tag, *names, pre=False, draft=False):
    return {"tag_name": tag, "name": tag, "prerelease": pre, "draft": draft, "body": f"notes of {tag}",
            "html_url": f"https://github.com/{U.REPO}/releases/tag/{tag}", "published_at": "2026-10-01T00:00:00Z",
            "assets": [{"name": n, "size": 10, "browser_download_url": f"https://example.invalid/{tag}/{n}"}
                       for n in names]}


def _all(tag, version, pre=False, draft=False):
    return _release(tag, f"SpartaGen-{version}-Windows-x64.zip", f"SpartaGen-{version}-macOS-arm64.zip",
                    f"SpartaGen-{version}-Linux-x64.zip", f"SpartaGen-{version}-Linux-arm64.zip",
                    f"SpartaGen-{version}-Android.apk", f"SpartaGen-{version}-iOS.ipa", pre=pre, draft=draft)


def test_versions_sort_as_releases_come():
    order = ["0.9", "1.0.0a1", "1.0.0-beta2", "1.0.0rc1", "v1.0.0-rc2", "1.0.0", "v1.0.1-rc1", "1.0.1", "1.1"]
    parsed = [U.parse_version(v) for v in order]
    assert None not in parsed and parsed == sorted(parsed)
    assert U.parse_version("1.0.0rc1") == U.parse_version("v1.0.0-rc1")
    assert U.parse_version("nightly") is None


def test_the_newest_release_with_a_file_for_each_platform():
    releases = [_all("v1.0.0-rc1", "1.0.0rc1", pre=True), _all("v1.0.0", "1.0.0"),
                _all("v1.0.1-rc1", "1.0.1rc1", pre=True), _all("v2.0.0", "2.0.0", draft=True),
                _release("v1.0.2", "SpartaGen-1.0.2-Android.apk")]
    # A release candidate takes the newest of all (release candidates too); a release only releases.
    assert U.check("windows", "1.0.0rc1", "x64", releases)["latest"] == "1.0.1-rc1"
    final = U.check("windows", "1.0.0", "x64", releases)
    assert final["latest"] == "1.0.0" and final["newer"] is False
    assert U.check("android", "1.0.0", releases=releases)["latest"] == "1.0.2"       # (only Android has 1.0.2)
    win = U.check("windows", "1.0.0rc1", "x64", releases)
    assert win["newer"] and win["asset"]["name"] == "SpartaGen-1.0.1rc1-Windows-x64.zip" and win["notes"]
    assert U.check("linux", "1.0.0rc1", "arm64", releases)["asset"]["name"].endswith("-Linux-arm64.zip")
    assert U.check("linux", "1.0.0rc1", "x64", releases)["asset"]["name"].endswith("-Linux-x64.zip")
    assert U.check("macos", "1.0.1rc1", "arm64", releases)["newer"] is False
    nothing = U.check("windows", "1.0.0", "x64", [])
    assert nothing["newer"] is False and nothing["latest"] is None and nothing["page"] == U.RELEASES_PAGE
    with pytest.raises(ValueError):
        U.check("amiga", "1.0.0", releases=releases)


def test_ios_updates_go_through_trollstore_sidestore_or_altstore():
    """An iOS app cannot install apps: TrollStore, SideStore and AltStore install the new IPA from a link."""
    info = U.check("ios", "1.0.0rc1", releases=[_all("v1.0.0", "1.0.0")])
    url = info["asset"]["url"]
    from urllib.parse import parse_qs, urlparse
    for key, scheme in (("trollstore", "apple-magnifier"), ("sidestore", "sidestore"), ("altstore", "altstore")):
        link = urlparse(info["stores"][key]["link"])
        assert (link.scheme, link.netloc) == (scheme, "install") and parse_qs(link.query)["url"] == [url]


def _make_app(root, name="SpartaGen", program="spartagen", text="old"):
    app = os.path.join(root, name)
    os.makedirs(os.path.join(app, "data"))
    os.makedirs(os.path.join(app, "engine"))
    exe = os.path.join(app, program)
    marker = os.path.join(root, "started")
    with open(exe, "w") as fh:
        fh.write(f"#!/bin/sh\necho {text} > '{marker}'\n")
    os.chmod(exe, 0o755)
    with open(os.path.join(app, "engine", "version.txt"), "w") as fh:
        fh.write(text)
    with open(os.path.join(app, "data", "icudtl.dat"), "w") as fh:
        fh.write(text)
    return app, exe


def _zip_like_a_release(app, out):
    """The way scripts/build_desktop.py zips an app: its folder, programs kept programs, links kept links."""
    base = os.path.dirname(app)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(app):
            for name in dirs + files:
                full = os.path.join(folder, name)
                rel = os.path.relpath(full, base)
                if os.path.islink(full):
                    info = zipfile.ZipInfo(rel)
                    info.create_system = 3
                    info.external_attr = 0o120777 << 16
                    z.writestr(info, os.readlink(full))
                elif name in files:
                    z.write(full, rel)
    return out


@pytest.mark.skipif(os.name == "nt" or sys.platform == "darwin", reason="the Linux update script")
def test_an_update_is_downloaded_unpacked_and_put_in_place(tmp_path):
    installed, exe = _make_app(str(tmp_path / "installed"))
    built, _ = _make_app(str(tmp_path / "built"), text="new")
    os.symlink("version.txt", os.path.join(built, "engine", "current"))
    release_zip = _zip_like_a_release(built, str(tmp_path / "SpartaGen-1.0.1-Linux-x64.zip"))
    asset = {"name": os.path.basename(release_zip), "url": "file://" + release_zip,
             "size": os.path.getsize(release_zip)}
    seen = []
    file = U.download(asset, str(tmp_path / "updates"), lambda p, m: seen.append(p))
    assert os.path.getsize(file) == asset["size"] and seen
    new_app = U.unpack(file, str(tmp_path / "updates" / "v1.0.1"))
    assert os.path.basename(new_app) == "SpartaGen"
    assert os.stat(os.path.join(new_app, "spartagen")).st_mode & stat.S_IXUSR             # still a program
    assert os.readlink(os.path.join(new_app, "engine", "current")) == "version.txt"      # still a link
    with pytest.raises(ValueError, match="short"):
        U.download(dict(asset, size=asset["size"] + 5, name="other.zip"), str(tmp_path / "updates"))
    # The app (a process that has quit already) is replaced and started again.
    gone = subprocess.Popen(["true"])
    gone.wait()
    cmd = U.install_script(new_app, exe, [gone.pid], str(tmp_path / "updates"))
    subprocess.run(cmd, check=True, timeout=30)
    with open(os.path.join(os.path.dirname(exe), "engine", "version.txt")) as fh:
        assert fh.read() == "new"
    marker = str(tmp_path / "built" / "started")              # (where the new app's program writes)
    for _ in range(50):
        if os.path.isfile(marker):
            break
        time.sleep(0.1)
    with open(marker) as fh:
        assert fh.read().strip() == "new"                                   # the new app started


def test_an_update_never_touches_what_is_not_an_installed_app(tmp_path):
    new_app, _ = _make_app(str(tmp_path / "new"))
    loose = tmp_path / "Downloads"
    loose.mkdir()
    (loose / "spartagen").write_text("#!/bin/sh\n")
    with pytest.raises(ValueError, match="by hand"):
        U.install_script(new_app, str(loose / "spartagen"), [1], str(tmp_path / "updates"))
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../outside.txt", "no")
    with pytest.raises(ValueError, match="outside"):
        U.unpack(str(evil), str(tmp_path / "unpacked"))
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("readme.txt", "no app")
    with pytest.raises(ValueError, match="no SpartaGen"):
        U.unpack(str(empty), str(tmp_path / "unpacked2"))


def test_the_app_folder_of_a_running_app():
    assert U.app_folder("/Applications/SpartaGen.app/Contents/MacOS/SpartaGen") == "/Applications/SpartaGen.app"
    assert U.app_folder("/opt/SpartaGen/spartagen") == "/opt/SpartaGen"


def test_the_windows_and_mac_scripts():
    win = U.windows_script(r"C:\Users\Me\AppData\SpartaGen\updates\v1.0.1\SpartaGen", r"C:\Apps\100% SpartaGen",
                           r"C:\Apps\100% SpartaGen\SpartaGen.exe", [4321, 99], r"C:\x\update.log")
    assert win.count("goto wait") == 2 and 'find " 4321 "' in win and 'find " 99 "' in win
    assert r'robocopy "C:\Users\Me\AppData\SpartaGen\updates\v1.0.1\SpartaGen" "C:\Apps\100%% SpartaGen" /E' in win
    assert win.index("robocopy") < win.index("if errorlevel 8 (start") < win.rindex('start "" "C:\\Apps\\100%% '
                                                                                      'SpartaGen\\SpartaGen.exe"')
    assert "\r\n" in win and "\n" not in win.replace("\r\n", "")
    mac = U.posix_script("/u/updates/v1.0.1/SpartaGen.app", "/Applications/SpartaGen.app",
                         "/Applications/SpartaGen.app/Contents/MacOS/SpartaGen", [4321, 99], "/u/update.log")
    assert "while kill -0 4321 2>/dev/null || kill -0 99 2>/dev/null; do sleep 0.3; done" in mac
    assert "ditto '/u/updates/v1.0.1/SpartaGen.app' '/Applications/SpartaGen.app'" in mac
    assert "rm -rf '/Applications/SpartaGen.app'; mv \"$OLD\" '/Applications/SpartaGen.app'; }" in mac  # (failed: old)
    assert mac.rstrip().endswith("open '/Applications/SpartaGen.app'")


# ── from the GitHub repository ───────────────────────────────────────────────


def test_the_published_release_files_are_found():
    """The release as the repository has it (tests/fixtures/releases.json: v1.0.0-rc1, its files named without
    the version) gives every platform its file."""
    import json
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "releases.json")) as fh:
        releases = json.load(fh)
    want = {"windows": "SpartaGen-Windows-x64.zip", "macos": "SpartaGen-macOS-arm64.zip",
            "linux": "SpartaGen-Linux-x64.zip", "android": "SpartaGen-Android.apk", "ios": "SpartaGen-iOS.ipa"}
    for plat, name in want.items():
        older = U.check(plat, "0.9.0rc1", "arm64" if plat == "macos" else "x64", releases)
        assert older["newer"] and older["asset"]["name"] == name, plat
        assert U.check(plat, "0.9.0", "x64", releases)["newer"] is False      # (a release is not offered a release
        #                                                                         candidate: only rc to rc users)
        assert older["asset"]["url"] == f"https://github.com/ovlweb/sparta-gen/releases/download/v1.0.0-rc1/{name}"
        assert older["page"] == "https://github.com/ovlweb/sparta-gen/releases/tag/v1.0.0-rc1"
        assert U.check(plat, "1.0.0rc1", "x64", releases)["newer"] is False           # this very version
    assert U.REPO == "ovlweb/sparta-gen"


_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/" xml:lang="en-US">
  <id>tag:github.com,2008:https://github.com/ovlweb/sparta-gen/releases</id>
  <title>Release notes from sparta-gen</title>
  <entry>
    <id>tag:github.com,2008:Repository/1389859976/v1.0.0</id>
    <updated>2026-10-20T10:00:00Z</updated>
    <link rel="alternate" type="text/html" href="{base}/ovlweb/sparta-gen/releases/tag/v1.0.0"/>
    <title>1.0</title>
    <content type="html">&lt;p&gt;Blocks for patterns &amp;amp; updates&lt;/p&gt;</content>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/1389859976/v1.0.0-rc1</id>
    <updated>2026-09-29T18:23:41Z</updated>
    <link rel="alternate" type="text/html" href="{base}/ovlweb/sparta-gen/releases/tag/v1.0.0-rc1"/>
    <title>1.0 (RC)</title>
    <content type="html">&lt;p&gt;First release candidate&lt;/p&gt;</content>
  </entry>
</feed>
"""

_FILES = """<div data-view-component="true" class="Box Box--condensed mt-3"><ul>
  <li class="Box-row"><a href="/ovlweb/sparta-gen/releases/download/{tag}/SpartaGen-Android.apk" rel="nofollow"
     data-turbo="false" class="Truncate"><span class="Truncate-text text-bold">SpartaGen-Android.apk</span></a></li>
  <li class="Box-row"><a href="/ovlweb/sparta-gen/releases/download/{tag}/SpartaGen-Linux-x64.zip" rel="nofollow"
     data-turbo="false" class="Truncate"><span class="Truncate-text text-bold">SpartaGen-Linux-x64.zip</span></a></li>
  <li class="Box-row"><a href="/ovlweb/sparta-gen/archive/refs/tags/{tag}.zip" rel="nofollow">Source code (zip)</a></li>
</ul></div>
"""


@pytest.fixture
def github(tmp_path, monkeypatch):
    """GitHub on this computer: its API answering ``state["api"]`` (403 when it refuses, 301 when the repository
    moved), the releases feed, each release's file list and the files themselves."""
    import http.server
    import json
    import threading
    state = {"api": 200, "hits": []}
    apk = b"PK\x03\x04" + b"\x00" * 5000

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body=b"", kind="application/json", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            p = self.path
            state["hits"].append(p)
            if p.startswith("/repos/OldName/sparta-gen/releases"):
                return self.send(301, extra=[("Location", "/repos/ovlweb/sparta-gen/releases?per_page=30")])
            if p.startswith("/repos/ovlweb/sparta-gen/releases"):
                if state["api"] == 403:
                    return self.send(403, json.dumps({"message": "API rate limit exceeded for 1.2.3.4."}).encode())
                rel = {"tag_name": "v1.0.0", "name": "1.0", "prerelease": False, "draft": False, "body": "API notes",
                       "html_url": f"{base}/ovlweb/sparta-gen/releases/tag/v1.0.0",
                       "assets": [{"name": "SpartaGen-Android.apk", "size": len(apk),
                                   "browser_download_url": f"{base}/ovlweb/sparta-gen/releases/download/v1.0.0/"
                                                           "SpartaGen-Android.apk"}]}
                return self.send(200, json.dumps([rel]).encode())
            if p == "/ovlweb/sparta-gen/releases.atom":
                return self.send(200, _FEED.replace("{base}", base).encode(), "application/atom+xml")
            if p.startswith("/ovlweb/sparta-gen/releases/expanded_assets/"):
                return self.send(200, _FILES.replace("{tag}", p.rsplit("/", 1)[1]).encode(), "text/html")
            if p.startswith("/ovlweb/sparta-gen/releases/download/"):
                return self.send(200, apk, "application/octet-stream")
            self.send(404)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setattr(U, "GITHUB", url)
    monkeypatch.setattr(U, "GITHUB_API", url)
    yield state, apk
    httpd.shutdown()


def test_an_update_comes_from_the_repository_through_its_api(github, tmp_path):
    state, apk = github
    info = U.check("android", "1.0.0rc1")
    assert info["newer"] and info["latest"] == "1.0.0" and info["notes"] == "API notes"
    assert U.download(info["asset"], str(tmp_path)) and (tmp_path / "SpartaGen-Android.apk").read_bytes() == apk


def test_a_moved_repository_is_followed(github, monkeypatch):
    state, _apk = github
    monkeypatch.setattr(U, "REPO", "OldName/sparta-gen")
    assert U.check("android", "1.0.0rc1")["latest"] == "1.0.0"
    assert state["hits"][:2] == ["/repos/OldName/sparta-gen/releases?per_page=30",
                                 "/repos/ovlweb/sparta-gen/releases?per_page=30"]


def test_when_the_api_refuses_the_releases_feed_finds_the_update(github, tmp_path):
    """GitHub's API answers 60 times an hour per address (fewer behind a shared one): then the releases feed and
    the release's list of files find the update just the same."""
    state, apk = github
    state["api"] = 403
    info = U.check("android", "1.0.0rc1")
    assert info["newer"] and info["latest"] == "1.0.0" and info["notes"] == "Blocks for patterns & updates"
    assert info["asset"]["name"] == "SpartaGen-Android.apk" and info["asset"]["url"].endswith(
        "/ovlweb/sparta-gen/releases/download/v1.0.0/SpartaGen-Android.apk")
    assert U.check("linux", "1.0.0rc1", "x64")["asset"]["name"] == "SpartaGen-Linux-x64.zip"
    assert U.check("windows", "1.0.0rc1", "x64")["latest"] is None                 # (no Windows file listed)
    assert (tmp_path / "x").mkdir() is None and U.download(info["asset"], str(tmp_path / "x"))
    assert (tmp_path / "x" / "SpartaGen-Android.apk").read_bytes() == apk           # (no size known: all of it)
    assert "/ovlweb/sparta-gen/releases.atom" in state["hits"]


def test_no_connection_says_so(monkeypatch):
    monkeypatch.setattr(U, "GITHUB", "http://127.0.0.1:9")
    monkeypatch.setattr(U, "GITHUB_API", "http://127.0.0.1:9")
    with pytest.raises(ValueError, match="could not reach GitHub"):
        U.check("android", "1.0.0rc1")
