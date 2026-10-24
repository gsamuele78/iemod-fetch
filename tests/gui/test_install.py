"""
Phase 5, installation, driven like a player drives it (GUI-AUDIT M4 item 22c,
ADR-0045, ADR-0046): the programs found or not - said in their own words -
WeiDU downloaded only after a confirmation naming its licence, a backup of
each game folder first, then the install: the real api.start_install over a
stand-in mod_installer (tests/data/fake_mod_installer.py), its output shown,
its question asked on the page, Cancel honoured.
"""
import json
import os
import sys

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from iemod_fetch import api  # noqa: E402
from iemod_fetch.errors import ConfigError  # noqa: E402
from iemod_fetch.toolchain import Found, Pin  # noqa: E402
from iemod_fetch_gui.pages.install import InstallPage, Services  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
FAKE = os.path.join(DATA, "fake_mod_installer.py")
CHOSEN = [("ub/setup-ub.tp2", 0)]
PIN = Pin("weidu", "25100", "https://github.com/WeiDUorg/weidu/releases/download/v251.00/x.zip",
          "0" * 64, "x/weidu", "0" * 64)


@pytest.fixture
def world(tmp_path):
    """A BG2:EE game, its mods, a stand-in mod_installer and the page's services."""
    game = tmp_path / "bg2ee"
    game.mkdir()
    (game / "chitin.key").write_text("")
    mods = tmp_path / "mods"
    (mods / "ub").mkdir(parents=True)
    if os.name == "nt":
        program = tmp_path / "mod_installer.cmd"
        program.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        program = tmp_path / "mod_installer"
        program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        program.chmod(0o755)
    state = {"backups": [], "downloads": [], "plans": [], "find": [], "weidu": True}

    def find(mod_installer=None, weidu=None):
        state["find"].append((mod_installer, weidu))
        tools = {"mod_installer": Found("mod_installer", str(program), "16.0.0", "bundled")}
        tools["weidu"] = (Found("weidu", str(program), "25100", "downloaded") if state["weidu"]
                          else Found("weidu", problem="no weidu given, none on PATH"))
        return tools

    def download(tool, progress=None, cancel=None):
        state["downloads"].append(tool)
        progress(500, 1000)
        state["weidu"] = True
        return Found("weidu", str(program), "25100", "downloaded")

    def backup(folder, on_event=None, cancel=None):
        on_event({"event": "backup_started", "files": 1, "bytes": 10})
        state["backups"].append({"path": f"{folder}-backup", "created": "2026-10-24T09:00",
                                 "files": 1})
        return f"{folder}-backup"

    def plan(game_name, chosen, labels, folder):
        state["plans"].append((game_name, list(chosen)))
        plan_dir = tmp_path / "install-plan"
        plan_dir.mkdir(exist_ok=True)
        (plan_dir / "WeiDU.log").write_text(
            "// Log of Currently Installed WeiDU Mods\n"
            "~UB/SETUP-UB.TP2~ #0 #0 // Restorations: v30\n")
        return {"plan_dir": str(plan_dir), "logs": [], "languages": ["languages: en_US"]}

    services = Services(find=find, pin=lambda tool: PIN, download=download,
                        backups=lambda folder: list(state["backups"]), backup=backup,
                        plan=plan, games=lambda project: {"BG2EE": str(game)},
                        mods_dir=lambda project: str(mods),
                        timing={"quiet_s": 0.3, "grace_s": 1.0})
    return {"services": services, "state": state, "game": game, "tmp": tmp_path}


def page_of(qtbot, world, answers=()):
    page = InstallPage(str(world["tmp"]), world["services"])
    qtbot.addWidget(page)
    asked = []
    page.confirm = lambda title, text: asked.append((title, text)) or (
        answers[len(asked) - 1] if len(asked) <= len(answers) else True)
    page.confirmed = asked
    page.prepare("BG2EE", CHOSEN, {})
    return page


def run_to_end(qtbot, page):
    with qtbot.waitSignal(page.finished, timeout=30000):
        page.install()


# ------------------------------------------------------------ the programs
def test_a_missing_program_is_said_in_its_own_words_and_stops_the_install(qtbot, world):
    world["state"]["weidu"] = False
    page = page_of(qtbot, world)
    assert page.tool_state["weidu"].text() == "no weidu given, none on PATH"
    assert "16.0.0 (bundled)" in page.tool_state["mod_installer"].text()
    assert not page.install_button.isEnabled()
    assert "WeiDU: no weidu given, none on PATH" in page.needs.text()
    assert not page.download_weidu.isHidden()             # offered, since it is missing


def test_weidu_is_downloaded_only_once_its_licence_and_source_were_shown(qtbot, world):
    world["state"]["weidu"] = False
    page = page_of(qtbot, world, answers=(False,))
    page.offer_weidu()                                   # the player says no
    assert world["state"]["downloads"] == []
    title, text = page.confirmed[0]
    assert title == "Download WeiDU"
    assert PIN.url in text and "GPL-2.0" in text and "github.com/WeiDUorg/weidu" in text
    with qtbot.waitSignal(page.finished, timeout=10000):
        page.offer_weidu()                               # and now yes
    assert world["state"]["downloads"] == ["weidu"]
    assert page.found["weidu"].ok and "WeiDU downloaded" in page.summary.text()


def test_a_program_chosen_by_hand_is_the_one_looked_at(qtbot, world):
    page = page_of(qtbot, world)
    assert page.download_weidu.isHidden()                 # WeiDU found: nothing to offer
    page.use("weidu", "/my/weidu")
    assert world["state"]["find"][-1] == (None, "/my/weidu")


# ------------------------------------------------------------ the backups
def test_no_backup_no_install_and_one_made_here_counts(qtbot, world):
    page = page_of(qtbot, world)
    folder = str(world["game"])
    assert "no backup yet" in page.backup_state[folder].text()
    assert not page.install_button.isEnabled()
    assert f"no backup of {folder} yet" in page.needs.text()
    with qtbot.waitSignal(page.finished, timeout=10000):
        page.back_up(folder)
    assert page.backed_up[folder] == f"{folder}-backup"
    assert "backed up 2026-10-24T09:00" in page.backup_state[folder].text()
    assert page.install_button.isEnabled() and page.needs.text() == ""


# ------------------------------------------------------------ the install
def backed_up(world):
    folder = str(world["game"])
    world["state"]["backups"].append({"path": f"{folder}-backup",
                                      "created": "2026-10-24T08:00", "files": 1})


def test_the_install_asks_first_then_runs_and_shows_mod_installer(qtbot, world):
    backed_up(world)
    page = page_of(qtbot, world, answers=(False,))
    page.install()                                       # the player says no
    assert world["state"]["plans"] == [] and not page.running()
    title, text = page.confirmed[0]
    assert title == "Install" and str(world["game"]) in text and "-backup" in text
    run_to_end(qtbot, page)
    assert world["state"]["plans"] == [("BG2EE", CHOSEN)]
    assert page.outcome.ok and page.is_complete()
    shown = page.output.toPlainText()
    assert "Beginning normal install process" in shown and "== setup-ub.tp2 #0" in shown
    assert "languages: en_US" in shown
    assert "Installed." in page.summary.text()
    assert "SETUP-UB.TP2" in (world["game"] / "WeiDU.log").read_text()


def test_a_question_is_asked_on_the_page_and_its_answer_goes_back(qtbot, world, monkeypatch):
    backed_up(world)
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps({"setup-ub.tp2#0": ["Which portraits?"]}))
    monkeypatch.setenv("FAKE_TRANSCRIPT", str(world["tmp"] / "answers.txt"))
    page = page_of(qtbot, world)
    questions = []
    page.ask_player = lambda question: questions.append(question) or "2"
    run_to_end(qtbot, page)
    assert questions == ["Which portraits?"] and page.outcome.ok
    assert (world["tmp"] / "answers.txt").read_text().split() == ["2"]
    assert "-> 2  (player)" in page.output.toPlainText()


def test_cancelling_a_question_stops_the_install_and_says_how_to_start_again(qtbot, world,
                                                                            monkeypatch):
    backed_up(world)
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps({"setup-ub.tp2#0": ["Which portraits?"]}))
    page = page_of(qtbot, world)
    page.ask_player = lambda question: None
    run_to_end(qtbot, page)
    assert page.outcome.cancelled and not page.is_complete()
    assert "restore the backup" in page.summary.text()


def test_cancel_while_it_runs(qtbot, world, monkeypatch):
    backed_up(world)
    monkeypatch.setenv("FAKE_SLOW", "20")
    page = page_of(qtbot, world)
    with qtbot.waitSignal(page.finished, timeout=30000):
        page.install()
        qtbot.waitUntil(lambda: "Beginning normal" in page.output.toPlainText(),
                        timeout=10000)
        assert page.running() and page.cancel_button.isEnabled()
        assert not page.install_button.isEnabled()
        page.stop()
    assert page.outcome.cancelled


def test_what_stops_it_before_it_starts_is_said(qtbot, world):
    backed_up(world)

    def refuse(*_args, **_kwargs):
        raise ConfigError("BG2EE: /x already has mods installed (WeiDU.log)")
    world["services"].start = refuse
    page = page_of(qtbot, world)
    run_to_end(qtbot, page)
    assert page.summary.text() == "BG2EE: /x already has mods installed (WeiDU.log)"
    assert page.outcome is None


def test_the_window_installs_last_and_keeps_back_locked_while_it_runs(qtbot, world,
                                                                     monkeypatch):
    from iemod_fetch_gui.window import MainWindow
    backed_up(world)
    monkeypatch.setenv("FAKE_SLOW", "20")
    main = MainWindow(str(world["tmp"]), load=lambda game, project: [],
                      install=world["services"])
    qtbot.addWidget(main)
    main.install.confirm = lambda title, text: True
    main.install.prepare("BG2EE", CHOSEN, {})
    main.stack.setCurrentIndex(4)
    main._refresh()
    with qtbot.waitSignal(main.install.finished, timeout=30000):
        main.install.install()
        qtbot.waitUntil(lambda: not main.back.isEnabled(), timeout=5000)
        main.go_back()
        assert main.current == 4                         # Back does nothing meanwhile
        main.install.stop()
    qtbot.waitUntil(lambda: main.back.isEnabled(), timeout=5000)


def test_the_real_plan_writer_names_the_project_folder(tmp_path, monkeypatch):
    """Services' default plan writer is the api's, over the project folder."""
    from iemod_fetch_gui.pages import install
    seen = {}
    monkeypatch.setattr(api, "write_install_plan",
                        lambda *args, **kwargs: seen.update(args=args, kwargs=kwargs) or {})
    install._plan("EET", CHOSEN, {}, str(tmp_path))
    assert seen["kwargs"]["folder"] == str(tmp_path) and seen["kwargs"]["fetch_metadata"]
