"""
Known upstream faults said before installing (GUI-AUDIT M8 item 65): EET's
core and a Documents folder registered with a space, on Windows. EET's
GET_USER_DIRECTORY (lib/macros.tph, still so at c26a11a, 2026-10-29) keeps
the third `reg query` token only. The batch line below has its shape; it is
written here, not copied from EET (GPL-3.0).
"""
import sys

import pytest

from iemod_fetch import api, install_run

CUT = ('for /f "tokens=3,*" %%a in (\'reg query "HKEY_CURRENT_USER\\Software\\Microsoft'
       '\\Windows\\CurrentVersion\\Explorer\\User Shell Folders" /v Personal\') '
       'do set DOC_DIR=%%a\n')
WHOLE = CUT.replace("set DOC_DIR=%%a", 'set "DOC_DIR=%%a %%b"')     # a fix, as one could write it


def eet_mods(tmp_path, batch=CUT, folder="EET"):
    lib = tmp_path / "mods" / folder / "lib"
    lib.mkdir(parents=True)
    (lib / "macros.tph").write_text("DEFINE_ACTION_FUNCTION GET_USER_DIRECTORY\nBEGIN\n"
                                    + batch + "END\n")
    return str(tmp_path / "mods")


GAMES = {"BGEE": "/g/bgee", "EET": "/g/eet"}


def test_a_documents_folder_with_a_space_meets_eets_cut(tmp_path):
    issues = install_run.known_issues(GAMES, eet_mods(tmp_path),
                                      documents=lambda: r"C:\Users\ann\OneDrive - Acme\Documents")
    assert len(issues) == 1
    assert "keeps it only up to the first space ('C:\\\\Users\\\\ann\\\\OneDrive')" in issues[0]
    assert "OneDrive - Acme" in issues[0]


@pytest.mark.parametrize("value", [
    r"%USERPROFILE%\Documents",          # a user name with a space is expanded after the cut
    r"D:\Documents", None, "",
])
def test_no_space_in_the_registered_value_meets_nothing(tmp_path, value):
    assert install_run.known_issues(GAMES, eet_mods(tmp_path), documents=lambda: value) == []


def test_an_eet_that_keeps_the_whole_path_meets_nothing(tmp_path):
    mods = eet_mods(tmp_path, batch=WHOLE)
    assert install_run.known_issues(GAMES, mods, documents=lambda: r"D:\My Documents") == []


def test_no_eet_in_the_plan_or_none_downloaded_meets_nothing(tmp_path):
    mods = eet_mods(tmp_path)
    space = r"D:\My Documents"
    assert install_run.known_issues({"BG2EE": "/g"}, mods, documents=lambda: space) == []
    assert install_run.known_issues(GAMES, str(tmp_path / "none"), documents=lambda: space) == []


def test_the_eet_folder_is_found_whatever_its_case(tmp_path):
    mods = eet_mods(tmp_path, folder="eet")
    assert install_run.known_issues(GAMES, mods, documents=lambda: r"D:\My Documents")


def test_off_windows_the_registry_is_not_read():
    if sys.platform != "win32":
        assert install_run._documents_value() is None


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows registry")
def test_on_windows_the_registered_value_is_read_unexpanded():
    value = install_run._documents_value()
    assert value is None or "Documents" in value or "%" in value or ":" in value


def test_the_api_says_the_same(tmp_path, monkeypatch):
    monkeypatch.setattr(install_run, "_documents_value", lambda: r"D:\My Documents")
    assert api.install_known_issues(GAMES, eet_mods(tmp_path))
