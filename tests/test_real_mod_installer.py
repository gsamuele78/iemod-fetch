"""
The install the wizard runs, with the REAL mod_installer driving the REAL
WeiDU (ADR-0045): a synthetic BG2:EE folder (test_real_weidu.make_game), a
test mod whose tp2 asks two questions, and the planned log recording their
answers as `// @wlb-inputs:`. The claim: mod_installer's question reaches
this program, the recorded answers go back in order, and WeiDU installs the
component with them.

Opt-in: IEMOD_MOD_INSTALLER=/path/to/mod_installer (16.0.0, built from
source) and IEMOD_WEIDU=/path/to/weidu.
"""
import os

import pytest

from iemod_fetch import api

MOD_INSTALLER = os.environ.get("IEMOD_MOD_INSTALLER", "")
WEIDU = os.environ.get("IEMOD_WEIDU", "")
if os.environ.get("IEMOD_REQUIRE_REAL") and not (os.path.isfile(MOD_INSTALLER)
                                                  and os.path.isfile(WEIDU)):
    raise RuntimeError("IEMOD_REQUIRE_REAL is set but IEMOD_MOD_INSTALLER or IEMOD_WEIDU "
                       "is not a file")
pytestmark = pytest.mark.skipif(
    not (os.path.isfile(MOD_INSTALLER) and os.path.isfile(WEIDU)),
    reason="real mod_installer and WeiDU not given (IEMOD_MOD_INSTALLER, IEMOD_WEIDU)")

ASKER = """BACKUP ~asker/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~Asks two things~
PRINT ~Please enter the first answer:~
ACTION_READLN first
PRINT ~Please enter the second answer:~
ACTION_READLN second
APPEND_OUTER ~asker-answers.txt~ ~%first% %second%~
"""


def test_the_real_mod_installer_asks_and_gets_the_recorded_answers(tmp_path):
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    mods = tmp_path / "mods"
    (mods / "asker").mkdir(parents=True)
    (mods / "asker" / "asker.tp2").write_text(ASKER)
    (game / "asker-answers.txt").write_text("")              # APPEND_OUTER needs it there
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "// The top of the file is the 'oldest' mod\n"
        "// ~TP2_File~ #language_number #component_number // [Subcomponent Name -> ] "
        "Component Name [ : Version]\n"
        "~ASKER/ASKER.TP2~ #0 #0 // Asks two things: 1 // @wlb-inputs: hello,world\n")
    lines, asked = [], []
    install = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: asked.append(q) or None,
                                on_event=lambda e: lines.append(e.text))
    outcome = install.run()
    transcript = "\n".join(lines)
    assert outcome.ok, transcript
    assert asked == [], transcript
    assert [a.source for a in outcome.answered] == ["recorded", "recorded"], transcript
    assert (game / "asker-answers.txt").read_text().split() == ["hello", "world"]
    installed = (game / "WeiDU.log").read_text()
    assert "ASKER" in installed.upper()


ASKPATH = """BACKUP ~askpath/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~Asks a folder~
PRINT ~Please enter the full path to the folder:~
ACTION_READLN folder
ACTION_IF FILE_EXISTS ~%folder%/marker.txt~ THEN BEGIN
  APPEND_OUTER ~askpath-result.txt~ ~found~
END ELSE BEGIN
  APPEND_OUTER ~askpath-result.txt~ ~missing~
END
"""


# "città – über" fits Windows' ANSI code page (cp1252); "Игры ゲーム" does
# not: a program opening paths with the ANSI API would fail only that one
# (review of #86). Both tell WeiDU's wide-API use apart from cp1252 luck.
@pytest.mark.parametrize("name", ["plain folder", "città – über", "Игры ゲーム"],
                         ids=["ascii", "cp1252", "beyond-cp1252"])
def test_a_folder_answered_through_mod_installer_reaches_weidu(tmp_path, name):
    """
    The measurement ADR-0046 records (review of #83): a folder given as an
    answer travels as UTF-8 through mod_installer (its read_line takes
    nothing else) to WeiDU, which opens it. EET's BG:EE folder travels so
    on Windows and macOS. ASCII is the control: when it fails, the setup
    does, not the encoding.
    """
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    mods = tmp_path / "mods"
    (mods / "askpath").mkdir(parents=True)
    (mods / "askpath" / "askpath.tp2").write_text(ASKPATH)
    (game / "askpath-result.txt").write_text("")
    folder = tmp_path / name
    folder.mkdir()
    (folder / "marker.txt").write_text("here")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        f"~ASKPATH/ASKPATH.TP2~ #0 #0 // Asks a folder: 1 // @wlb-inputs: {folder}\n",
        encoding="utf-8")
    lines = []
    install = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: None,
                                on_event=lambda e: lines.append(e.text))
    outcome = install.run()
    transcript = "\n".join(lines)
    assert outcome.ok, transcript
    assert [a.source for a in outcome.answered] == ["recorded"], transcript
    assert (game / "askpath-result.txt").read_text().split() == ["found"], transcript
