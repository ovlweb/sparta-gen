"""scripts/set_version.py: a release's version written into the engine and the app before they are built."""

import importlib.util
import os
import re
import shutil
import subprocess
import sys

import pytest

from spartagen import __version__
from spartagen.update import parse_version

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "set_version.py")
_spec = importlib.util.spec_from_file_location("set_version", SCRIPT)
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)
FILES = ("spartagen/__init__.py", "app/pubspec.yaml")


def test_forms():
    assert SV.forms("v1.0.0-rc2") == ("1.0.0rc2", "1.0.0-rc.2", 1000062)
    assert SV.forms("v1.0.0-rc.2") == SV.forms("1.0.0-rc2") == SV.forms(" v1.0.0-rc2\n")
    assert SV.forms("v1.0.0") == ("1.0.0", "1.0.0", 1000099)
    assert SV.forms("v1.2.3-beta1") == ("1.2.3b1", "1.2.3-beta.1", 1020331)
    assert SV.forms("v2.0.0-alpha.3") == ("2.0.0a3", "2.0.0-alpha.3", 2000003)


def test_every_release_goes_up():
    order = ["v1.0.0-rc2", "v1.0.0-rc3", "v1.0.0-rc29", "v1.0.0", "v1.0.1-alpha1", "v1.0.1-beta1", "v1.0.1-rc1",
             "v1.0.1", "v1.0.99", "v1.1.0-rc1", "v1.1.0", "v1.10.0", "v1.99.99", "v2.0.0-alpha0", "v2.0.0"]
    assert sorted(order, key=parse_version) == order                   # (the updater's order)
    builds = [SV.forms(v)[2] for v in order]
    assert builds == sorted(set(builds))
    # v1.0.0-rc1 went out as build 100001: Android installs every later APK over it.
    assert builds[0] > 100001
    for v in order:
        engine, app, _ = SV.forms(v)
        assert parse_version(engine) == parse_version(app) == parse_version(v)
        # The release's file names lose the version: SpartaGen-1.0.0rc2-Windows-x64.zip → SpartaGen-Windows-x64.zip
        name = f"SpartaGen-{engine}-Windows-x64.zip"
        assert re.sub(r"^SpartaGen-[0-9][0-9A-Za-z.+]*-", "SpartaGen-", name) == "SpartaGen-Windows-x64.zip"


@pytest.mark.parametrize("bad", ["", "main", "1.0", "v1.0", "v1.0.0-rc", "v1.0.0-test1", "v1.0.0-RC2", "v1.0.0rc2",
                                 "v1.0.0-rc30", "v1.100.0", "v1.0.100", "v3000.0.0", "v1.0.0-rc2; rm -rf /"])
def test_refused(bad):
    with pytest.raises(ValueError):
        SV.forms(bad)


def _copy(tmp_path):
    for f in FILES:
        os.makedirs(tmp_path / os.path.dirname(f), exist_ok=True)
        shutil.copy(os.path.join(ROOT, f), tmp_path / f)


def test_writes_the_engine_and_the_app(tmp_path):
    _copy(tmp_path)
    assert SV.write("v1.0.0-rc2", str(tmp_path)) == ("1.0.0rc2", "1.0.0-rc.2", 1000062)
    changed = {}
    for f in FILES:
        before = open(os.path.join(ROOT, f), encoding="utf-8").read().splitlines()
        after = (tmp_path / f).read_text(encoding="utf-8").splitlines()
        assert len(before) == len(after)
        changed[f] = [(a, b) for a, b in zip(before, after) if a != b]
    assert [b for _, b in changed["spartagen/__init__.py"]] == ['__version__ = "1.0.0rc2"']
    assert [b for _, b in changed["app/pubspec.yaml"]] == ["version: 1.0.0-rc.2+1000062"]
    # Written again: the same files (the comments above pubspec's version line are left alone).
    SV.write("v1.0.0", str(tmp_path))
    assert '__version__ = "1.0.0"\n' in (tmp_path / FILES[0]).read_text(encoding="utf-8")
    assert "\nversion: 1.0.0+1000099\n" in (tmp_path / FILES[1]).read_text(encoding="utf-8")


def test_command_line(tmp_path):
    r = subprocess.run([sys.executable, SCRIPT, "--check", "v1.0.0-rc2"], capture_output=True, text=True)
    assert r.returncode == 0 and "1.0.0rc2" in r.stdout and "1.0.0-rc.2" in r.stdout and "not written" in r.stdout
    r = subprocess.run([sys.executable, SCRIPT, "--check", "v1.0"], capture_output=True, text=True,
                       env=dict(os.environ, GITHUB_ACTIONS="true"))
    assert r.returncode == 1 and r.stderr.startswith("::error::")         # (shown on the run's page)
    assert subprocess.run([sys.executable, SCRIPT], capture_output=True).returncode == 2


def test_the_engine_and_the_app_are_one_version():
    with open(os.path.join(ROOT, "app", "pubspec.yaml"), encoding="utf-8") as fh:
        app = re.search(r"^version:\s*(\S+)", fh.read(), re.M).group(1)
    name, _, build = app.partition("+")
    assert parse_version(name) == parse_version(__version__) is not None
    assert build.isdigit()
