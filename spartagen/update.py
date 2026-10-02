"""Updates from inside the app: the newest release on GitHub, and what this computer, phone or tablet needs of it.

* Windows, macOS, Linux: its zip, downloaded and unpacked; a small script waits for the app (and its engine) to
  quit, puts the new app where this one is and starts it.
* Android: its APK, handed to the system's installer — every release is signed with the same key, so it installs
  over this one and keeps its projects.
* iOS: an app cannot install apps.  TrollStore can: its URL scheme ``apple-magnifier://install?url=<IPA>``
  (once "URL Scheme Enabled" is on in TrollStore's settings) installs the new IPA over this one; SideStore and
  AltStore take ``sidestore://install?url=<IPA>`` and ``altstore://install?url=<IPA>`` the same way (signing it
  again with your Apple ID).  An app installed with a certificate of your own (Sideloadly, ESign …) is updated
  by hand: the new IPA, installed the way this one was.  (:data:`IOS_STORES`; the app opens the links.)
"""

from __future__ import annotations

import json
import os
import platform as _platform
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from typing import Callable, Optional

from . import __version__

#: Where SpartaGen is released (GitHub follows the repository if it moves again).
REPO = "ovlweb/sparta-gen"
GITHUB = "https://github.com"
GITHUB_API = "https://api.github.com"
RELEASES_PAGE = f"{GITHUB}/{REPO}/releases"

#: The release file each platform takes, by the end of its name: SpartaGen-Windows-x64.zip, as releases have them
#: (or SpartaGen-<version>-Windows-x64.zip, as the builds name them).
ASSETS = {
    "windows": r"-Windows-(?P<arch>x64|arm64)\.zip$",
    "macos": r"-macOS-(?P<arch>arm64|x64)\.zip$",
    "linux": r"-Linux-(?P<arch>x64|arm64)\.zip$",
    "android": r"-Android\.apk$",
    "ios": r"-iOS\.ipa$",
}
#: iOS: the apps that can install an IPA from a link, and theirs.
IOS_STORES = {
    "trollstore": ("TrollStore", "apple-magnifier://install?url="),
    "sidestore": ("SideStore", "sidestore://install?url="),
    "altstore": ("AltStore", "altstore://install?url="),
}

Progress = Optional[Callable[[float, str], None]]

_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-.]?(a|alpha|b|beta|c|rc)\.?(\d*))?$", re.IGNORECASE)
_STAGES = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2}


def parse_version(text: str) -> Optional[tuple]:
    """A version (1.0.0, v1.0.0-rc1, 1.0.0rc1, 1.2-beta.3) as a tuple that sorts the way releases come: alpha,
    beta and rc before the release itself.  None for what is not a version."""
    m = _VERSION.match((text or "").strip())
    if not m:
        return None
    major, minor, patch, stage, n = m.groups()
    return int(major), int(minor), int(patch or 0), _STAGES.get((stage or "").lower(), 3), int(n or 0)


def machine() -> str:
    m = _platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(m, m)


def pick_asset(assets: list, platform: str, arch: str = "") -> Optional[dict]:
    """The release file for a platform (its own processor's first, else another that runs there)."""
    pattern = ASSETS.get(platform)
    if pattern is None:
        raise ValueError(f"no updates for {platform!r} (platforms: {', '.join(ASSETS)})")
    found = [(a, re.search(pattern, a.get("name") or "")) for a in assets]
    found = [(a, m) for a, m in found if m]
    found.sort(key=lambda am: 0 if "arch" not in am[1].groupdict() or am[1]["arch"] == (arch or machine()) else 1)
    return found[0][0] if found else None


def _ssl_context():
    import ssl
    try:                          # (a bundled engine may not find the system's certificates; certifi has them)
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(url: str, timeout: float = 20.0):
    accept = "application/vnd.github+json" if url.startswith(GITHUB_API) else "*/*"
    req = urllib.request.Request(url, headers={"User-Agent": f"SpartaGen/{__version__}", "Accept": accept})
    if url.startswith("https:"):
        return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
    return urllib.request.urlopen(req, timeout=timeout)


def _get(url: str) -> bytes:
    with _open(url) as r:
        return r.read()


def fetch_releases() -> list:
    """The repository's releases, newest first: from GitHub's API — or, when that refuses (it answers 60 times an
    hour per address, fewer on a shared one), from its releases feed and each release's list of files."""
    try:
        data = json.loads(_get(f"{GITHUB_API}/repos/{REPO}/releases?per_page=30").decode("utf-8"))
        if isinstance(data, list):
            return data
        api_error: Exception = ValueError(str(data.get("message") if isinstance(data, dict) else data))
    except (OSError, ValueError) as exc:          # (an HTTP error is an OSError too)
        api_error = exc
    try:
        return releases_from_feed(_get(f"{GITHUB}/{REPO}/releases.atom"),
                                  lambda tag: _get(f"{GITHUB}/{REPO}/releases/expanded_assets/{tag}"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not reach GitHub to look for updates ({api_error}; {exc})") from exc


def releases_from_feed(feed: bytes, files_page: Callable[[str], bytes], newest: int = 4) -> list:
    """The releases in GitHub's releases feed (Atom), each like the API's: its tag, name, notes, page and — for
    the ``newest`` few — its files, read from the release's list of them (``files_page(tag)``)."""
    import html
    import xml.etree.ElementTree as ET
    from urllib.parse import unquote
    a = "{http://www.w3.org/2005/Atom}"
    try:
        root = ET.fromstring(feed)
    except ET.ParseError as exc:
        raise ValueError(f"the releases feed could not be read ({exc})") from exc
    out = []
    for entry in root.findall(f"{a}entry"):
        link = entry.find(f"{a}link")
        page = link.get("href", "") if link is not None else ""
        if "/releases/tag/" not in page:
            continue
        tag = unquote(page.rsplit("/releases/tag/", 1)[1])
        v = parse_version(tag)
        notes = html.unescape(re.sub(r"<[^>]+>", " ", entry.findtext(f"{a}content") or ""))
        out.append({"tag_name": tag, "name": (entry.findtext(f"{a}title") or tag).strip(), "draft": False,
                    "prerelease": v is not None and v[3] < 3, "html_url": page,
                    "published_at": entry.findtext(f"{a}updated"),
                    "body": re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", notes)).strip(), "assets": []})
    out.sort(key=lambda r: parse_version(r["tag_name"]) or (0,), reverse=True)
    for r in out[:newest]:
        page = files_page(r["tag_name"]).decode("utf-8", "replace")
        seen = set()
        for path in re.findall(r'href="(/[^"]+/releases/download/[^"]+)"', page):
            name = unquote(path.rsplit("/", 1)[1])
            if name not in seen:
                seen.add(name)
                r["assets"].append({"name": name, "size": 0, "browser_download_url": GITHUB + html.unescape(path)})
    return out


def check(platform: str, current: str = __version__, arch: str = "", releases: Optional[list] = None,
          prereleases: Optional[bool] = None) -> dict:
    """The newest release with a file for ``platform`` and whether it is newer than ``current``.  Pre-releases
    (rc, beta) count when this is one too, or when ``prereleases`` says so."""
    if releases is None:
        releases = fetch_releases()
    now = parse_version(current) or (0, 0, 0, 3, 0)
    pre = now[3] < 3 if prereleases is None else bool(prereleases)
    best = None
    for r in releases:
        v = parse_version(r.get("tag_name") or "")
        if v is None or r.get("draft") or (r.get("prerelease") and not pre):
            continue
        asset = pick_asset(r.get("assets") or [], platform, arch)
        if asset is not None and (best is None or v > best[0]):
            best = (v, r, asset)
    out = {"current": current, "platform": platform, "newer": False, "latest": None, "page": RELEASES_PAGE}
    if best is None:
        return out
    v, r, asset = best
    out.update({
        "newer": v > now, "latest": (r.get("tag_name") or "").lstrip("v"), "tag": r.get("tag_name"),
        "name": r.get("name") or r.get("tag_name"), "notes": (r.get("body") or "").strip()[:6000],
        "page": r.get("html_url") or RELEASES_PAGE, "published": r.get("published_at"),
        "prerelease": bool(r.get("prerelease")),
        "asset": {"name": asset["name"], "url": asset["browser_download_url"], "size": int(asset.get("size") or 0)},
    })
    if platform == "ios":
        url = asset["browser_download_url"]
        out["stores"] = {k: {"name": name, "link": prefix + _quote(url)} for k, (name, prefix) in IOS_STORES.items()}
    return out


def _quote(url: str) -> str:
    from urllib.parse import quote
    return quote(url, safe="")


# ── downloading and unpacking ────────────────────────────────────────────────


def download(asset: dict, folder: str, progress: Progress = None) -> str:
    """The release file into ``folder`` (kept: a second try starts over only when it is not whole)."""
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(asset["name"])
    dest = os.path.join(folder, name)
    size = int(asset.get("size") or 0)
    if size and os.path.isfile(dest) and os.path.getsize(dest) == size:
        return dest
    part = dest + ".part"
    got = 0
    with _open(asset["url"], timeout=60.0) as r, open(part, "wb") as out:
        total = size or int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if progress and total:
                progress(min(0.99, got / total), f"downloading {got / 1e6:.1f} of {total / 1e6:.1f} MB")
    if total and got != total:
        os.remove(part)
        raise ValueError(f"the download stopped short ({got} of {total} bytes) — try again")
    os.replace(part, dest)
    return dest


def unpack(zip_path: str, folder: str) -> str:
    """A desktop release's zip unpacked into ``folder`` (emptied first); the app in it: the SpartaGen folder, or
    SpartaGen.app on macOS.  Programs stay programs and links stay links (a Mac app's signature needs them)."""
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    if sys.platform == "darwin" and shutil.which("ditto"):
        subprocess.run(["ditto", "-x", "-k", zip_path, folder], check=True)
    else:
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                target = os.path.realpath(os.path.join(folder, info.filename))
                if not target.startswith(os.path.realpath(folder) + os.sep):
                    raise ValueError(f"the zip has a file outside its folder: {info.filename}")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.symlink(z.read(info).decode("utf-8"), target)
                    continue
                z.extract(info, folder)
                if mode & 0o777 and not info.is_dir():
                    os.chmod(target, mode & 0o777)
    for name in ("SpartaGen.app", "SpartaGen"):
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            return path
    raise ValueError("the downloaded zip has no SpartaGen in it")


# ── putting it in place ──────────────────────────────────────────────────────


def app_folder(executable: str) -> str:
    """The folder (or Mac app) the running app is: what an update replaces."""
    exe = os.path.abspath(executable)
    parts = exe.split(os.sep)
    if ".app" in exe and "Contents" in parts:                     # …/SpartaGen.app/Contents/MacOS/SpartaGen
        return os.sep.join(parts[:parts.index("Contents")])
    return os.path.dirname(exe)


def _looks_like_app(path: str) -> bool:
    if path.endswith(".app"):
        return os.path.isdir(os.path.join(path, "Contents", "MacOS"))
    names = set(os.listdir(path)) if os.path.isdir(path) else set()
    return "data" in names and bool(names & {"SpartaGen.exe", "spartagen"})


def install_script(new_app: str, executable: str, pids: list, folder: str) -> list:
    """Write the script that puts ``new_app`` where the running app is, once processes ``pids`` (the app and its
    engine) have quit, and starts it again; returns the command that runs it.  Refused (ValueError) when the
    running app is not an installed SpartaGen, or sits where this user cannot write."""
    dest = app_folder(executable)
    if not _looks_like_app(dest) or not _looks_like_app(new_app):
        raise ValueError("this SpartaGen does not run from an app folder of its own — update it by hand")
    if not _writable(dest) or not _writable(os.path.dirname(dest)):
        raise ValueError(f"SpartaGen is in a folder it cannot change ({dest}) — update it by hand, or move it to a "
                         "folder of yours")
    os.makedirs(folder, exist_ok=True)
    log = os.path.join(folder, "update.log")
    pids = [int(p) for p in pids if int(p) > 0]
    exe = os.path.join(dest, os.path.basename(executable))
    if os.name == "nt":
        script = os.path.join(folder, "update.cmd")
        with open(script, "w", encoding="utf-8", newline="") as fh:
            fh.write(windows_script(new_app, dest, exe, pids, log))
        return ["cmd.exe", "/c", script]
    script = os.path.join(folder, "update.sh")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(posix_script(new_app, dest, exe, pids, log))
    os.chmod(script, 0o755)
    return ["/bin/sh", script]


def _writable(folder: str) -> bool:
    """Whether this user can put files in ``folder`` (tried: Windows answers os.access for folders without
    looking at their permissions)."""
    import tempfile
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def windows_script(new_app: str, dest: str, exe: str, pids: list, log: str) -> str:
    """Windows: wait while the processes run, copy the new app over this one (robocopy), start it."""
    def path(p: str) -> str:
        return p.replace("%", "%%")                        # (cmd reads % as a variable)
    waits = "".join(f'tasklist /FI "PID eq {p}" /NH | find " {p} " >nul && '
                    '(ping -n 2 127.0.0.1 >nul & goto wait)\r\n' for p in pids)
    return ("@echo off\r\n"
            "rem SpartaGen's update: waits for the app to quit, puts the new one in its place, starts it.\r\n"
            f":wait\r\n{waits}"
            f'robocopy "{path(new_app)}" "{path(dest)}" /E /R:10 /W:1 /NFL /NDL /NJH /NJS /NP >"{path(log)}"\r\n'
            f'if errorlevel 8 (start "" "{path(exe)}" & exit /b 1)\r\n'          # (not copied: the old one again)
            f'start "" "{path(exe)}"\r\n')


def posix_script(new_app: str, dest: str, exe: str, pids: list, log: str) -> str:
    """macOS: the new app bundle swapped for this one (back again if that fails), then opened; Linux: the new
    app's files copied over this one's, then started."""
    q = _sh
    wait = " || ".join(f"kill -0 {p} 2>/dev/null" for p in pids) or "false"
    if dest.endswith(".app"):
        put = (f"OLD={q(dest + '.old')}\nrm -rf \"$OLD\"\n"
               f"mv {q(dest)} \"$OLD\" && ditto {q(new_app)} {q(dest)} && rm -rf \"$OLD\" || "
               f"{{ rm -rf {q(dest)}; mv \"$OLD\" {q(dest)}; }}\n"          # (not swapped: the old one back)
               f"xattr -dr com.apple.quarantine {q(dest)} 2>/dev/null\n"
               f"open {q(dest)}\n")
    else:
        put = (f"cp -Rf {q(new_app + '/.')} {q(dest + '/')} || echo 'not copied: the old SpartaGen starts again'\n"
               f"cd {q(dest)} && nohup {q(exe)} >/dev/null 2>&1 &\n")
    return ("#!/bin/sh\n# SpartaGen's update: waits for the app to quit, puts the new one in its place, starts it.\n"
            f"exec >{q(log)} 2>&1\n"
            f"while {wait}; do sleep 0.3; done\n{put}")


def _sh(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def launch(command: list) -> None:
    """Start the update script on its own: it outlives the app and the engine it waits for."""
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200 | 0x08000000      # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
        subprocess.Popen(command, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(command, start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
