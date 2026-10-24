"""
The install the wizard runs (GUI-AUDIT M4 item 22, ADR-0045): mod_installer
as a child of this program, its output read line by line, WeiDU's questions
answered - EET's with the BG:EE folder, then what the planned log records
(`// @wlb-inputs:`), then by asking the player - and stopped on Cancel.

mod_installer is played by tests/data/fake_mod_installer.py, which prints
what the real one logs and asks the way it asks; the real mod_installer is
run against a stand-in WeiDU by test_real_mod_installer.py when it is built.
"""
import os
import sys
import threading

import pytest

from iemod_fetch import api
from iemod_fetch.errors import ConfigError
from iemod_fetch.install_run import command, preflight
from iemod_fetch.prompts import OutputReader, recorded_answers, wlb_inputs

HERE = os.path.dirname(__file__)
FAKE = os.path.join(HERE, "data", "fake_mod_installer.py")
EET_QUESTION = "Enter the full path to your BG:EE+SoD installation then press Enter."


# ----------------------------------------------------------- the answers
def test_recorded_answers_are_read_left_to_right_with_blanks():
    assert wlb_inputs("~A\\A.TP2~ #0 #10 // Confirm: v1.0 // @wlb-inputs: y,,c") == ["y", "", "c"]
    assert wlb_inputs("~A\\A.TP2~ #0 #10 // Confirm: v1.0") is None
    assert wlb_inputs(r"~EET\EET.TP2~ #0 #0 // EET core // @wlb-inputs: C:\My Games\BG2") == [
        r"C:\My Games\BG2"]
    log = ("// Log of Currently Installed WeiDU Mods\n"
           "~EET\\EET.TP2~ #0 #0 // EET core (resource importation): v14.0\n"
           "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67 // @wlb-inputs: 1,2\n")
    assert recorded_answers(log) == {("vienxay.tp2", 0): ["1", "2"]}


def test_the_output_is_read_into_batches_and_questions():
    reader = OutputReader()
    kinds = []
    for line in [
            ("[2026-10-24T00:00:00Z INFO  mod_installer::installers] Installing mod "
             'WeiduBatchedComponents([WeiduComponent { tp_file: "SETUP-UB.TP2", name: "ub", '
             'lang: "0", component: "0", component_name: "", sub_component: "", '
             'version: "" }, WeiduComponent { tp_file: "SETUP-UB.TP2", name: "ub", lang: "0", '
             'component: "10", component_name: "", sub_component: "", version: "" }])\n'),
            "some WeiDU output\n",
            "[2026-10-24T00:00:00Z INFO  mod_installer::runner] User Input required\n",
            "[2026-10-24T00:00:00Z INFO  mod_installer::runner] Question is\n",
            "[2026-10-24T00:00:00Z INFO  mod_installer::runner] Which portraits?\n",
            "1] classic\n", "2] new\n"]:
        kinds += [(e.kind, e.batch) for e in reader.feed(line) if e.kind != "line"]
    assert kinds == [("batch", (("setup-ub.tp2", 0), ("setup-ub.tp2", 10)))]
    assert reader.asking
    question = reader.question()
    assert question.text == "Which portraits?\n1] classic\n2] new"
    assert question.batch == (("setup-ub.tp2", 0), ("setup-ub.tp2", 10))
    assert not reader.asking and reader.question() is None


# ---------------------------------------------------------- the install
@pytest.fixture
def setup(tmp_path):
    """Two fresh games, the staged mods, the planned logs and the programs."""
    games = {}
    for name in ("BGEE", "EET"):
        folder = tmp_path / name.lower()
        folder.mkdir()
        (folder / "chitin.key").write_text("")
        games[name] = str(folder)
    mods = tmp_path / "mods"
    for folder in ("eet", "ub", "vienxay"):
        (mods / folder).mkdir(parents=True)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67 // @wlb-inputs: 1,\n")
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~EET/EET.TP2~ #0 #0 // EET core (resource importation): v14.0\n"
        "~UB/SETUP-UB.TP2~ #0 #0 // Restorations: v30\n")
    if os.name == "nt":
        program = tmp_path / "mod_installer.cmd"
        program.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        program = tmp_path / "mod_installer"
        program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        program.chmod(0o755)
    return {"games": games, "mods": str(mods), "plan": str(plan),
            "program": str(program), "transcript": tmp_path / "answers.txt"}


def run(setup, monkeypatch, questions, ask=lambda _q, _b: None, **extra):
    import json
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps(questions))
    monkeypatch.setenv("FAKE_TRANSCRIPT", str(setup["transcript"]))
    events = []
    install = api.start_install(setup["plan"], setup["games"], setup["mods"],
                                setup["program"], weidu=setup["program"], ask=ask,
                                on_event=events.append, quiet_s=0.3, **extra)
    return install, events


def read(*path):
    from pathlib import Path
    file = Path(*path)
    return file.read_text() if file.exists() else ""


def answers(setup):
    return setup["transcript"].read_text().splitlines() if setup["transcript"].exists() else []


def test_eet_is_installed_answering_each_question_from_where_it_should(setup, monkeypatch):
    asked = []
    install, events = run(setup, monkeypatch, {
        "vienxay.tp2#0": ["Choose one", "Press Enter"],
        "eet.tp2#0": [EET_QUESTION],
        "setup-ub.tp2#0": ["Restore the tavern? [y]es or [n]o"]},
        ask=lambda question, batch: asked.append((question, batch)) or "y")
    outcome = install.run()
    assert outcome.ok, [e.text for e in events]
    assert answers(setup) == ["1", "", setup["games"]["BGEE"], "y"]
    assert [a.source for a in outcome.answered] == ["recorded", "recorded", "EET", "player"]
    # the player was asked only what nothing recorded, with its component
    assert asked == [("Restore the tavern? [y]es or [n]o", (("setup-ub.tp2", 0),))]
    # each game's WeiDU.log now names what went in, the recorded answers not copied
    eet_log = read(setup["games"]["EET"], "WeiDU.log")
    assert "EET core" in eet_log and "SETUP-UB.TP2" in eet_log
    assert "@wlb-inputs" not in read(setup["games"]["BGEE"], "WeiDU.log")
    assert [e.batch for e in events if e.kind == "batch"] == [
        (("vienxay.tp2", 0),), (("eet.tp2", 0),), (("setup-ub.tp2", 0),)]


def test_a_question_the_player_cancels_stops_the_install(setup, monkeypatch):
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": ["Something unknown?"]})
    outcome = install.run()
    assert outcome.cancelled and not outcome.ok
    assert "SETUP-UB" not in read(setup["games"]["EET"], "WeiDU.log")       # never reached


def test_cancel_from_another_thread_stops_it(setup, monkeypatch):
    monkeypatch.setenv("FAKE_SLOW", "30")
    install, events = run(setup, monkeypatch, {}, grace_s=2.0)
    timer = threading.Timer(0.5, install.cancel)
    timer.start()
    outcome = install.run()
    timer.cancel()
    assert outcome.cancelled and outcome.returncode is not None
    assert any(e.kind == "batch" for e in events)


def test_a_failed_component_is_a_failed_install(setup, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "eet.tp2#0")
    install, events = run(setup, monkeypatch, {})
    outcome = install.run()
    assert outcome.returncode == 1 and not outcome.ok and not outcome.cancelled
    assert any("not installed due to errors" in e.text for e in events if e.kind == "line")


# ------------------------------------------------------- before it starts
def test_what_stops_it_before_it_starts_is_named(setup, tmp_path):
    games, program = setup["games"], setup["program"]
    assert preflight(games, setup["mods"], program, program) == []
    os.remove(os.path.join(games["BGEE"], "chitin.key"))
    with open(os.path.join(games["EET"], "WeiDU.log"), "w") as fh:
        fh.write("~EET/EET.TP2~ #0 #0 // EET core\n")
    problems = preflight(games, str(tmp_path / "nowhere"), program, str(tmp_path / "weidu"))
    assert any("BGEE: no chitin.key" in p for p in problems)
    assert any("EET:" in p and "already has mods" in p for p in problems)
    assert any("does not exist - download first" in p for p in problems)
    assert any(p.startswith("WeiDU is not a program here") for p in problems)
    assert not any("already has mods" in p for p in preflight(
        games, setup["mods"], program, program, allow_existing=True))
    with pytest.raises(ConfigError, match="no chitin.key"):
        api.start_install(setup["plan"], games, setup["mods"], program, program,
                          ask=lambda *_a: None)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux's case rule")
def test_a_mixed_case_mod_folder_is_refused_on_linux(setup):
    os.rename(os.path.join(setup["mods"], "ub"), os.path.join(setup["mods"], "UB"))
    assert any("lower-case on Linux: UB" in p for p in preflight(
        setup["games"], setup["mods"], setup["program"], setup["program"]))


def test_the_command_is_the_one_the_scripts_run(setup):
    argv = command(setup["plan"], setup["games"], "/mods", "/mi", "/weidu", "it_IT")
    assert argv[:2] == ["/mi", "eet"]
    assert argv[argv.index("--bg1-log-file") + 1].endswith("WeiDU-BGEE.log")
    assert argv[argv.index("--bg2-game-directory") + 1] == setup["games"]["EET"]
    assert argv[-6:] == ["--mod-directories", "/mods", "--weidu-binary", "/weidu",
                         "--language", "it_IT"]
    one = command(setup["plan"], {"BG2EE": "/g"}, "/mods", "/mi", "/weidu")
    assert one[:6] == ["/mi", "normal", "--game-directory", "/g", "--log-file",
                       os.path.join(setup["plan"], "WeiDU.log")]
