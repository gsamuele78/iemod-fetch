"""tools/download_measure.py: the summary of a download-sources run (ADR-0039)."""
import json

from tools import download_measure


def report(path, records, unresolved=()):
    path.write_text(json.dumps({"records": records, "unresolved": list(unresolved)}))
    return str(path)


def test_the_summary_counts_each_status_and_lists_the_misses(tmp_path, capsys):
    dry = report(tmp_path / "dry.json", [
        {"folder": "ub", "status": "planned", "origin": "release-asset", "detail": ""},
        {"folder": "eet", "status": "planned", "origin": "release-asset", "detail": ""},
        {"folder": "ghost", "status": "manual", "detail": "no manifest entry | none"}],
        unresolved=[{"folder": "x", "detail": "no entry"}])
    real = report(tmp_path / "real.json", [
        {"folder": "ub", "status": "ok", "origin": "release-asset", "detail": "installed"},
        {"folder": "eet", "status": "failed", "detail": "archive does not contain eet.tp2"}])
    assert download_measure.main([dry, "--real", real]) == 0
    out = capsys.readouterr().out
    assert "4 mods: 2 manual, 2 planned" in out
    assert "| release-asset | 2 |" in out
    assert "| ghost | manual | no manifest entry / none |" in out
    assert "| eet | failed | archive does not contain eet.tp2 |" in out


def test_pick_names_planned_mods_in_a_stable_order(tmp_path, capsys):
    dry = report(tmp_path / "dry.json", [
        {"folder": f, "status": s, "detail": ""} for f, s in
        (("zz", "planned"), ("aa", "planned"), ("mm", "manual"), ("bb", "planned"))])
    download_measure.main([dry, "--pick", "2"])
    assert capsys.readouterr().out.split() == ["aa", "bb"]
