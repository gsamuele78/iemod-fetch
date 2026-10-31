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


TWO = """BACKUP ~two/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~First~
PRINT ~first~

BEGIN ~Second~
PRINT ~second~
"""


def test_a_resumed_install_installs_only_what_is_left(tmp_path):
    """Item 23, against the real programs: mod_installer's own skip reads
    `weidu.log` and, on Linux, would install the first component again
    (measured), so it is turned off; the resume hands it only the second."""
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    mods = tmp_path / "mods"
    (mods / "two").mkdir(parents=True)
    (mods / "two" / "two.tp2").write_text(TWO)
    plan = tmp_path / "plan"
    plan.mkdir()

    def install(components, **extra):
        (plan / "WeiDU.log").write_text(
            "// Log of Currently Installed WeiDU Mods\n"
            + "".join(f"~TWO/TWO.TP2~ #0 #{n} // x\n" for n in components))
        lines = []
        outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                    WEIDU, ask=lambda q, b: None,
                                    on_event=lambda e: lines.append(e.text), **extra).run()
        return outcome, "\n".join(lines)

    outcome, transcript = install([0])                       # stopped after the first
    assert outcome.ok, transcript
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~TWO/TWO.TP2~ #0 #0 // x\n~TWO/TWO.TP2~ #0 #1 // x\n")
    assert api.install_progress(str(plan), {"BG2EE": str(game)})["done"] == 1
    outcome, transcript = install([0, 1], resume=True)
    assert outcome.ok, transcript
    assert "Installing [Second]" in transcript, transcript
    assert "Installing [First]" not in transcript, transcript       # not again
    installed = [line for line in (game / "WeiDU.log").read_text().splitlines()
                 if line.startswith("~")]
    assert [line.split("#")[-1].split()[0] for line in installed] == ["0", "1"]


SLOW = """BACKUP ~slow/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~Quick~
COPY ~slow/a.txt~ ~override/quick.txt~

BEGIN ~Slow~
COPY ~slow/a.txt~ ~override/marker.txt~
OUTER_SET n = 0
OUTER_WHILE n < 300000000 BEGIN OUTER_SET n = n + 1 END
"""


def test_a_component_cancelled_inside_is_not_resumed(tmp_path):
    """Item 23, review: a Cancel inside a component leaves its files in the
    game (marker.txt is the mod's now) and its uninstall record, not its
    WeiDU.log line. The resume refuses it rather than let WeiDU back up the
    mod's marker.txt as the game's."""
    import threading
    import time

    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "override" / "marker.txt").write_text("original\n")
    mods = tmp_path / "mods"
    (mods / "slow").mkdir(parents=True)
    (mods / "slow" / "slow.tp2").write_text(SLOW)
    (mods / "slow" / "a.txt").write_text("mod\n")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    "~SLOW/SLOW.TP2~ #0 #0 // Quick\n"
                                    "~SLOW/SLOW.TP2~ #0 #1 // Slow\n")
    lines: list[str] = []
    install = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: None,
                                on_event=lambda e: lines.append(e.text))

    def cancel_inside():
        deadline = time.monotonic() + 60
        while not any("marker.txt" in line for line in lines) and time.monotonic() < deadline:
            time.sleep(0.05)
        install.cancel()
    threading.Thread(target=cancel_inside, daemon=True).start()
    assert not install.run().ok
    assert (game / "override" / "marker.txt").read_text() == "mod\n"     # left there
    progress = api.install_progress(str(plan), {"BG2EE": str(game)})
    assert progress["state"] == "mismatch", "\n".join(lines)
    assert "slow/slow.tp2 #1 stopped half-way" in progress["problem"]


BAD = """BACKUP ~bad/backup~
AUTHOR ~iemod-fetch test~

BEGIN ~Fine~
COPY ~bad/a.txt~ ~override/fine.txt~

BEGIN ~Broken~
COPY ~bad/a.txt~ ~override/marker.txt~
COPY ~bad/a.txt~ ~override/new.txt~
FAIL ~broken~
"""


def test_a_component_that_fails_is_undone_by_weidu_and_resumes(tmp_path):
    """The other way an install stops: WeiDU's own error. It undoes the
    component it was in - the game's file back, the new one gone, no
    uninstall record left - so the resume goes on from it."""
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "override" / "marker.txt").write_text("original\n")
    mods = tmp_path / "mods"
    (mods / "bad").mkdir(parents=True)
    (mods / "bad" / "bad.tp2").write_text(BAD)
    (mods / "bad" / "a.txt").write_text("mod\n")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    "~BAD/BAD.TP2~ #0 #0 // Fine\n"
                                    "~BAD/BAD.TP2~ #0 #1 // Broken\n")
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: None).run()
    assert not outcome.ok
    assert (game / "override" / "marker.txt").read_text() == "original\n"
    assert not (game / "override" / "new.txt").exists()
    progress = api.install_progress(str(plan), {"BG2EE": str(game)})
    assert progress["state"] == "partial" and progress["phases"][0]["next"] == "bad/bad.tp2 #1"


TWO_QUESTIONS = """BACKUP ~twoq/backup~
AUTHOR ~iemod-fetch test~
VERSION ~v30~

BEGIN ~Asks a yes or no, then a number~
PRINT ~Restore the tavern? [y]es or [n]o~
ACTION_READLN first
PRINT ~Please select 1 or 2 and press Enter.~
ACTION_READLN second
APPEND_OUTER ~twoq-answers.txt~ ~%first% %second%~
"""


def test_recorded_answers_fit_the_real_window(tmp_path):
    """Item 63, review of #98: mod_installer sends each question with WeiDU's
    lines before it - here the yes/no before "select 1 or 2". The recorded
    answers both go in, nobody is asked, and what was answered is recorded."""
    import json

    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "twoq-answers.txt").write_text("")
    mods = tmp_path / "mods"
    (mods / "twoq").mkdir(parents=True)
    (mods / "twoq" / "twoq.tp2").write_text(TWO_QUESTIONS)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~TWOQ/TWOQ.TP2~ #0 #0 // Asks a yes or no, then a number // @wlb-inputs: y,2\n")
    lines, asked = [], []
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: asked.append(q) or None,
                                on_event=lambda e: lines.append(e.text)).run()
    transcript = "\n".join(lines)
    assert outcome.ok and asked == [], transcript
    assert [a.source for a in outcome.answered] == ["recorded", "recorded"], transcript
    assert (game / "twoq-answers.txt").read_text().split() == ["y", "2"]
    assert any("Installing [" in a.question for a in outcome.answered), transcript
    kept = json.loads((plan / "answers.json").read_text())["answered"]
    assert [(k["question"], k["answer"]) for k in kept] == [
        ("Restore the tavern? [y]es or [n]o", "y"),
        ("Please select 1 or 2 and press Enter.", "2")]


MENU_AFTER = """BACKUP ~menu/backup~
AUTHOR ~iemod-fetch test~
VERSION ~v30~

BEGIN ~Asks with its menu after the question~
PRINT ~Which portraits?~
PRINT ~1] Original~
PRINT ~2] Select 5 or 10 random ones~
ACTION_READLN choice
APPEND_OUTER ~menu-answer.txt~ ~%choice%~
"""


def test_a_menu_after_the_question_does_not_limit_its_answer(tmp_path):
    """Second review of #98: mod_installer fires on "2] Select 5 or 10 random
    ones" (its choice words); the recorded "1" still goes in."""
    import json

    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "menu-answer.txt").write_text("")
    mods = tmp_path / "mods"
    (mods / "menu").mkdir(parents=True)
    (mods / "menu" / "menu.tp2").write_text(MENU_AFTER)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~MENU/MENU.TP2~ #0 #0 // Asks with its menu after the question // @wlb-inputs: 1\n")
    lines, asked = [], []
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: asked.append(q) or None,
                                on_event=lambda e: lines.append(e.text)).run()
    transcript = "\n".join(lines)
    assert outcome.ok and asked == [], transcript
    assert (game / "menu-answer.txt").read_text().split() == ["1"]
    kept = json.loads((plan / "answers.json").read_text())["answered"]
    assert [(k["answer"], k["source"]) for k in kept] == [("1", "recorded")], kept


WARNS = """BACKUP ~warns/backup~
AUTHOR ~iemod-fetch test~
VERSION ~2~

BEGIN ~One~
COPY ~warns/f.txt~ ~override/one.txt~

BEGIN ~Careful~
COPY ~warns/f.txt~ ~override/careful.txt~
WARN ~careful~
"""


def test_each_component_gets_weidus_own_verdict(tmp_path):
    """Item 69 (ADR-0053): mod_installer starts WeiDU with --logapp --autolog,
    so every run appends to the game's WSETUP.DEBUG; each component's
    verdict is read from what this install appended, and held to WeiDU.log."""
    import json

    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    # an earlier install's debug file, with a verdict on a component this
    # install never reaches: not read, only what this install appends is
    (game / "WSETUP.DEBUG").write_text(
        f"WeiDU v 25100 Log\n\n {WEIDU} bad/bad.tp2 --force-install-list 2 --logapp\n"
        "Installing [Later]\nSUCCESSFULLY INSTALLED      Later\n")
    mods = tmp_path / "mods"
    for name, tp2 in (("warns", WARNS), ("bad", BAD)):
        (mods / name).mkdir(parents=True)
        (mods / name / f"{name}.tp2").write_text(tp2)
    (mods / "warns" / "f.txt").write_text("f\n")
    (mods / "bad" / "a.txt").write_text("mod\n")
    with open(mods / "bad" / "bad.tp2", "a") as fh:
        fh.write("\nBEGIN ~Later~\nCOPY ~bad/a.txt~ ~override/later.txt~\n")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    "~WARNS/WARNS.TP2~ #0 #0 // One\n"
                                    "~WARNS/WARNS.TP2~ #0 #1 // Careful\n"
                                    "~BAD/BAD.TP2~ #0 #0 // Fine\n"
                                    "~BAD/BAD.TP2~ #0 #1 // Broken\n"
                                    "~BAD/BAD.TP2~ #0 #2 // Later\n")
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: None).run()
    assert not outcome.ok                                   # the exit code: something failed
    got = [(x.key, x.status, x.name) for x in outcome.results]
    assert got[:4] == [(("warns.tp2", 0), "installed", "One"),
                       (("warns.tp2", 1), "installed with warnings", "Careful"),
                       (("bad.tp2", 0), "installed", "Fine"),
                       (("bad.tp2", 1), "not installed (errors)", "Broken")], got
    assert all(not x.note for x in outcome.results[:4])
    assert (got[4][0], got[4][1]) == (("bad.tp2", 2), "not reached")     # stopped before
    written = json.loads((plan / "results.json").read_text())["components"]
    assert [c["status"] for c in written[:4]] == [x[1] for x in got[:4]]
