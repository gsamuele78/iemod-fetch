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


def test_mod_installer_12s_one_component_lines_and_ticks_are_read_too():
    """12.1.1, a player's own on Windows or macOS: `Component { ... }`, one
    at a time, and a row of dots logged each tick while WeiDU works."""
    reader = OutputReader()
    events = []
    for line in [
            ("[2026-10-24T00:00:00Z INFO  mod_installer::installers] Installing mod "
             'Component { tp_file: "ASKER.TP2", name: "asker", lang: "0", component: "3", '
             'component_name: "Asks", sub_component: "", version: "1" }\n'),
            "[2026-10-24T00:00:00Z INFO  mod_installer::weidu] \n",
            "[2026-10-24T00:00:00Z INFO  mod_installer::weidu] ...\n"]:
        events += reader.feed(line)
    assert [(e.kind, e.batch) for e in events if e.kind == "batch"] == \
        [("batch", (("asker.tp2", 3),))]
    assert [e for e in events if e.kind == "line" and set(e.text.split("] ")[-1]) <= {"."}] \
        == []                                    # the ticks say nothing


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
    return file.read_text(encoding="utf-8") if file.exists() else ""


def answers(setup):
    return setup["transcript"].read_text(encoding="utf-8").splitlines() if setup["transcript"].exists() else []


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
    assert argv[-8:] == ["--mod-directories", "/mods", "--weidu-binary", "/weidu",
                         "--language", "it_IT", "--download=false",
                         "--skip-installed=false"]
    one = command(setup["plan"], {"BG2EE": "/g"}, "/mods", "/mi", "/weidu")
    assert one[:6] == ["/mi", "normal", "--game-directory", "/g", "--log-file",
                       os.path.join(setup["plan"], "WeiDU.log")]


# ------------------------------------------------ reviews of the design
def alive(pid):
    """Whether process `pid` is still running (a zombie counts as gone)."""
    if os.name == "nt":
        import subprocess
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                capture_output=True, text=True, check=False).stdout
        return str(pid) in listed
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().split(")")[-1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_cancel_stops_what_mod_installer_started_too(setup, monkeypatch, tmp_path):
    """WeiDU, mod_installer's child, must not go on writing into the game."""
    import time
    pidfile = tmp_path / "weidu.pid"
    monkeypatch.setenv("FAKE_SLOW", "30")
    monkeypatch.setenv("FAKE_GRANDCHILD", str(pidfile))
    install, _events = run(setup, monkeypatch, {}, grace_s=1.0)
    timer = threading.Timer(1.0, install.cancel)
    timer.start()
    outcome = install.run()
    timer.cancel()
    assert outcome.cancelled
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not alive(pid)


def test_an_ended_install_does_not_wait_on_what_it_left_running(setup, monkeypatch, tmp_path):
    """
    mod_installer exits, something it started still holds its output (review
    of #83): the run ends soon after - not when that lets go - and stops it.
    """
    import time
    pidfile = tmp_path / "weidu.pid"
    monkeypatch.setenv("FAKE_GRANDCHILD", str(pidfile))
    monkeypatch.setenv("FAKE_EXIT_EARLY", "1")
    install, events = run(setup, monkeypatch, {}, grace_s=1.0, drain_s=0.5)
    started = time.monotonic()
    outcome = install.run()
    assert time.monotonic() - started < 15
    assert outcome.returncode == 0 and not outcome.cancelled
    assert any("still running: stopped" in e.text for e in events)
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not alive(pid)


def test_mod_installer_gets_the_child_environment(setup, monkeypatch):
    """A frozen bundle's library path is not handed down (childenv, #70)."""
    from iemod_fetch import install_run
    seen = []

    def marked(extra=None):
        seen.append(dict(extra or {}))
        return dict(os.environ, IEMOD_CHILD_ENV="cleaned", **(extra or {}))
    monkeypatch.setattr(install_run, "child_env", marked)
    monkeypatch.setenv("FAKE_ECHO_ENV", "IEMOD_CHILD_ENV")
    install, events = run(setup, monkeypatch, {})
    assert install.run().ok
    assert seen[0] == {"RUST_LOG": "info"}
    assert any(e.text.endswith("IEMOD_CHILD_ENV=cleaned") for e in events)


def test_mod_installers_options_never_come_from_the_players_environment(setup, monkeypatch):
    """clap reads NEW_EET_DIR, OVERWRITE, DOWNLOAD... from the environment as
    options (review of #86): none reaches mod_installer; the rest does."""
    monkeypatch.setenv("NEW_EET_DIR", "/somewhere/else")
    monkeypatch.setenv("overwrite", "true")              # Windows names are not case-sensitive
    monkeypatch.setenv("IEMOD_KEEP_ME", "kept")
    for name, expected in (("NEW_EET_DIR", ""), ("IEMOD_KEEP_ME", "kept")):
        monkeypatch.setenv("FAKE_ECHO_ENV", name)
        install, events = run(setup, monkeypatch, {}, allow_existing=True)
        assert install.run().ok
        assert any(e.text.endswith(f"{name}={expected}") for e in events), name
    from iemod_fetch import install_run
    env = install_run.mod_installer_env()
    assert "overwrite" not in env and "OVERWRITE" not in env and env["RUST_LOG"] == "info"


def test_answers_that_run_out_are_asked_never_left_blank(setup, monkeypatch):
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67 // @wlb-inputs: 1\n")
    asked = []
    install, _events = run(setup, monkeypatch, {
        "vienxay.tp2#0": ["Choose one", "And another"],
        "eet.tp2#0": [EET_QUESTION]},
        ask=lambda question, batch: asked.append(question) or "2")
    outcome = install.run()
    assert outcome.ok
    assert asked == ["And another"]
    assert answers(setup)[:2] == ["1", "2"]
    assert [a.source for a in outcome.answered][:2] == ["recorded", "player"]


def test_folders_with_spaces_and_accents_reach_it_whole(setup, monkeypatch, tmp_path):
    """The command is a list, never a shell line; an answer goes as UTF-8."""
    for name in ("BGEE", "EET"):
        folder = tmp_path / f"Baldur's Gate {name} – città"
        os.rename(setup["games"][name], folder)
        setup["games"][name] = str(folder)
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    outcome = install.run()
    assert outcome.ok
    assert answers(setup) == [setup["games"]["BGEE"]]
    assert "SETUP-UB.TP2" in read(setup["games"]["EET"], "WeiDU.log")


def test_an_accented_bgee_folder_is_not_refused(setup, tmp_path):
    """
    #83 refused one on Windows until it was measured; item 22b measured it
    (tests/test_real_mod_installer.py, on CI's Windows runner): the real
    WeiDU v251 opens a folder with accents given as UTF-8 through
    mod_installer. ADR-0046.
    """
    from iemod_fetch import install_run
    folder = tmp_path / "Baldur's Gate – città"
    os.rename(setup["games"]["BGEE"], folder)
    setup["games"]["BGEE"] = str(folder)
    args = (setup["games"], setup["mods"], setup["program"], setup["program"])
    assert install_run.preflight(*args) == []


# ------------------------------------------------------------ resuming (item 23)
def lines(path):
    from pathlib import Path
    return [line for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.startswith("~")]


def test_a_stopped_eet_install_resumes_with_only_what_is_left(setup, monkeypatch):
    """The fake fails at UB: BG:EE's part and EET's core are in. Resuming
    runs the EET game alone, with UB only - nothing installed twice."""
    monkeypatch.setenv("FAKE_FAIL", "setup-ub.tp2#0")
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    assert not install.run().ok
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "partial" and (progress["done"], progress["total"]) == (2, 3)
    assert [p["next"] for p in progress["phases"]] == [None, "ub/setup-ub.tp2 #0"]

    monkeypatch.delenv("FAKE_FAIL")
    install, events = run(setup, monkeypatch, {}, resume=True)
    assert install.argv[1] == "normal" and setup["games"]["EET"] in install.argv
    assert setup["games"]["BGEE"] not in install.argv
    assert install.run().ok
    assert [line.split("~")[1] for line in lines(os.path.join(setup["games"]["EET"],
                                                               "WeiDU.log"))] == \
        ["EET/EET.TP2", "UB/SETUP-UB.TP2"]
    assert len(lines(os.path.join(setup["games"]["BGEE"], "WeiDU.log"))) == 1
    assert api.install_progress(setup["plan"], setup["games"])["state"] == "finished"


def test_resuming_bgee_unfinished_runs_eet_mode_with_bgees_rest(setup, monkeypatch):
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #1 // Vienxay banter\n")
    Path(setup["games"]["BGEE"], "WeiDU.log").write_text(
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67\n")
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]}, resume=True)
    assert install.argv[1] == "eet"
    rest = install.argv[install.argv.index("--bg1-log-file") + 1]
    assert [line.split("#")[-1].split()[0] for line in lines(rest)] == ["1"]
    assert install.run().ok
    assert len(lines(os.path.join(setup["games"]["BGEE"], "WeiDU.log"))) == 2


def test_a_game_that_is_not_the_plans_beginning_is_not_resumed(setup, monkeypatch):
    from pathlib import Path
    Path(setup["games"]["BGEE"], "WeiDU.log").write_text("~OTHER/OTHER.TP2~ #0 #0 // x\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "mismatch" and "not this plan's install" in progress["problem"]
    with pytest.raises(ConfigError, match="cannot resume: .*restore the backup"):
        run(setup, monkeypatch, {}, resume=True)


def test_a_finished_install_has_nothing_to_resume(setup, monkeypatch):
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    assert install.run().ok
    with pytest.raises(ConfigError, match="nothing to resume"):
        run(setup, monkeypatch, {}, resume=True)


def test_a_fresh_game_resumes_as_a_plain_install(setup, monkeypatch):
    assert api.install_progress(setup["plan"], setup["games"])["state"] == "fresh"
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]}, resume=True)
    assert install.argv[1] == "eet" and install.run().ok


def test_an_eet_game_with_components_while_bgees_part_is_unfinished_is_not_resumed(
        setup, monkeypatch):
    """EET's log is only begun once BG:EE's part is whole (review of item 23)."""
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #1 // Vienxay banter\n")
    Path(setup["games"]["BGEE"], "WeiDU.log").write_text(
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67\n")
    Path(setup["games"]["EET"], "WeiDU.log").write_text("~EET/EET.TP2~ #0 #0 // EET core\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "mismatch"
    assert progress["problem"] == ("WeiDU.log: the game has 1 component(s) while "
                                   "WeiDU-BGEE.log is not finished (1 of 2 in): the game "
                                   "is not this plan's install")
    with pytest.raises(ConfigError, match="cannot resume: WeiDU.log: the game has 1"):
        run(setup, monkeypatch, {}, resume=True)


def test_mod_installer_is_told_not_to_skip(setup, monkeypatch):
    """Its skip reads `weidu.log` in lower case (16.0.0): what is left is ours."""
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    assert "--skip-installed=false" in install.argv


def test_a_component_stopped_half_way_is_not_resumed(setup, monkeypatch):
    """WeiDU's uninstall record of the next component is in the game while its
    log line is not: a Cancel inside it (measured with WeiDU 251). Installing
    it again would back up its own leftovers as the game's originals."""
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~SLOW/SLOW.TP2~ #0 #0 // Quick\n~SLOW/SLOW.TP2~ #0 #1 // Slow\n")
    game = Path(setup["games"]["BGEE"])
    (game / "WeiDU.log").write_text("~SLOW/SLOW.TP2~ #0 #0 // Quick\n")
    (game / "SLOW").mkdir()
    (game / "SLOW" / "slow.tp2").write_text("BACKUP ~slow/Backup~\nAUTHOR ~t~\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "partial"                 # no record: resumable
    (game / "SLOW" / "Backup" / "1").mkdir(parents=True)
    (game / "SLOW" / "Backup" / "1" / "UNINSTALL.1").write_text("override/first.txt\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "mismatch"
    assert "slow/slow.tp2 #1 stopped half-way" in progress["problem"]
    assert "UNINSTALL.1" in progress["problem"]
    with pytest.raises(ConfigError, match="stopped half-way.*restore the backup"):
        run(setup, monkeypatch, {}, resume=True)
