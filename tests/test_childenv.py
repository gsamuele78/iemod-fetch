"""
A program the bundle starts gets the system's libraries, not the bundle's
(review of #70): PyInstaller's bootloader puts `_internal` first on
LD_LIBRARY_PATH, and git, gh, 7-Zip and unrar would inherit it.
"""
import subprocess
import sys

import pytest

from iemod_fetch import archives, auth
from iemod_fetch.childenv import child_env


def test_outside_a_bundle_the_environment_is_inherited(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert child_env() is None
    monkeypatch.setenv("KEEP", "1")
    assert child_env({"X": "y"})["KEEP"] == "1"


def test_in_a_bundle_a_child_gets_the_library_path_from_before(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/iemod-fetch/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    env = child_env({"GIT_TERMINAL_PROMPT": "0"})
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env and env["GIT_TERMINAL_PROMPT"] == "0"


def test_in_a_bundle_with_no_path_before_the_child_gets_none(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/iemod-fetch/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/Applications/x/_internal")
    env = child_env()
    assert "LD_LIBRARY_PATH" not in env and "DYLD_LIBRARY_PATH" not in env


@pytest.mark.parametrize("call", ["gh", "git", "7z-list", "extract"])
def test_every_program_started_gets_that_environment(monkeypatch, tmp_path, call):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/iemod-fetch/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    seen = []

    def fake_run(cmd, **kw):
        seen.append(kw.get("env"))
        return subprocess.CompletedProcess(cmd, 1, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(archives, "find_tool", lambda name: "/usr/bin/" + name)
    archive = tmp_path / "a.7z"
    archive.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\0" * 32)
    if call == "gh":
        auth._from_gh_cli()
    elif call == "git":
        auth._from_git_credential()
    elif call == "7z-list":
        archives._seven_zip_listing(str(archive))
    else:
        with pytest.raises(archives.ExtractionError):
            archives._extract_external(str(archive), str(tmp_path / "out"), archives.Kind.SEVENZIP)
    assert seen, "no program was started"
    assert all(env is not None and "LD_LIBRARY_PATH" not in env for env in seen)
