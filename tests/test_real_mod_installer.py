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
