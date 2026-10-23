"""
packaging/cli_bundle.py (GUI-AUDIT item 36, ADR-0043): the command line as a
program that needs no Python, for the systems whose Python is older than the
one 4.0.0 needs. The helpers that do not need PyInstaller: the zip's name, the
licence files, and the check run on the unzipped program.
"""
import importlib.util
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "cli_bundle", os.path.join(ROOT, "packaging", "cli_bundle.py"))
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

VERSIONS = {"pyinstaller": "6.22.3", "python": "3.14.6"}


def test_the_zip_is_named_apart_from_the_wizards(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.shared, "tag", lambda: "windows-x86_64")
    folder = tmp_path / "out" / cli.NAME
    folder.mkdir(parents=True)
    (folder / "iemod-fetch.exe").write_bytes(b"MZ")
    path = cli.shared.pack(str(folder), str(tmp_path / "dist"), cli.ZIP)
    assert os.path.basename(path) == "iemod-fetch-cli-windows-x86_64.zip"
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == ["iemod-fetch/iemod-fetch.exe"]


def test_the_folder_carries_the_licences_and_no_qt_notice(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "versions", lambda: VERSIONS)
    folder = tmp_path / cli.NAME
    folder.mkdir()
    cli.add_licences(str(folder))
    assert (folder / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert sorted(os.listdir(folder / "licenses")) == ["filelock-LICENSE",
                                                       "publicsuffixlist-LICENSE"]
    assert (folder / "NOTICE-publicsuffixlist.txt").exists()      # MPL-2.0's source offer
    notice = (folder / "NOTICE.txt").read_text(encoding="utf-8")
    assert "Python 3.14.6" in notice and "PyInstaller 6.22.3" in notice
    assert not (folder / "NOTICE-Qt.txt").exists()
    assert not any("GPL" in name for name in os.listdir(folder / "licenses"))


def test_the_wizard_and_qt_are_left_out():
    assert {"PySide6", "shiboken6", "iemod_fetch_gui"} <= set(cli.EXCLUDE)


def fake_program(folder, script):
    """A stand-in for the built program: a script the check can run."""
    folder.mkdir(parents=True)
    path = folder / (cli.NAME + (".exe" if os.name == "nt" else ""))
    if os.name == "nt":
        pytest.skip("a script cannot stand in for an .exe")
    path.write_text(f"#!{sys.executable}\n{script}", encoding="utf-8")
    path.chmod(0o755)


def test_the_check_runs_the_version_and_the_help(tmp_path):
    fake_program(tmp_path / "p", "import sys\n"
                 "print('iemod-fetch 4.0.0' if '--version' in sys.argv else 'usage: x')\n")
    cli.check(str(tmp_path / "p"), str(tmp_path))


def test_a_program_that_does_not_start_stops_the_build(tmp_path):
    fake_program(tmp_path / "p", "import sys\nsys.exit('ModuleNotFoundError: filelock')\n")
    with pytest.raises(SystemExit, match="does not run --version"):
        cli.check(str(tmp_path / "p"), str(tmp_path))
