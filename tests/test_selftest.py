"""The self-test every built app runs in CI (`SpartaGen --selftest`, `spartagen selftest`)."""

import json

from spartagen import selftest
from spartagen.cli import main


def test_selftest_makes_a_remix_and_writes_its_report(tmp_path):
    out = tmp_path / "report.json"
    report = selftest.run(str(out), quality="audio", log=lambda m: None)
    assert report["ok"], report.get("error")
    assert report["duration"] > 20 and report["events"] > 100
    assert {"pitch1", "chorus_a", "kick", "hat_closed"} <= set(report["samples"])
    assert json.loads(out.read_text())["ok"] is True


def test_selftest_reports_a_failure_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(selftest, "make_test_source", lambda path: (_ for _ in ()).throw(OSError("disk full")))
    report = selftest.run(str(tmp_path / "r.json"), log=lambda m: None)
    assert report["ok"] is False and "disk full" in report["error"]
    assert main(["selftest", "--out", str(tmp_path / "r2.json")]) == 1
