"""
The public API (ADR-0029): what the command line does, as functions a GUI calls.

The claims: everything in `__all__` exists; `Settings` and the command line
mean the same thing by the same name, with the same default; `run` is silent
unless given a stream, reports progress as events, can be cancelled, and
returns what it produced instead of only an exit code.
"""
import json
import os
import threading

import pytest

from iemod_fetch import api
from iemod_fetch.cli import build_parser
from iemod_fetch.report import Status

from test_cli_end_to_end import workspace  # noqa: F401  (a pytest fixture)

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_everything_promised_in_all_exists():
    for name in api.__all__:
        assert hasattr(api, name), name


def test_settings_and_the_command_line_agree_on_names_and_defaults():
    parser = build_parser()
    defaults = api.Settings()
    for action in parser._actions:
        if action.dest in ("help", "version", "config"):
            continue
        assert hasattr(defaults, action.dest), f"--{action.dest} has no Settings field"
        expected = [] if action.default is None and isinstance(
            getattr(defaults, action.dest), list) else action.default
        assert getattr(defaults, action.dest) == expected, action.dest


def test_run_is_silent_reports_events_and_returns_what_it_made(workspace, capsys):  # noqa: F811
    tmp_path, stub = workspace
    events = []
    outcome = api.run(api.Settings(weidu_log=["WeiDU.log"], target="Mods"),
                      on_event=events.append)
    assert outcome.exit_code == 0
    assert [r.status for r in outcome.report.records] == [Status.OK, Status.OK]
    assert events[0]["event"] == "run_started" and events[-1]["event"] == "run_finished"
    assert capsys.readouterr().out == ""


def test_run_can_be_cancelled(workspace):  # noqa: F811
    tmp_path, stub = workspace
    cancel = threading.Event()
    cancel.set()
    outcome = api.run(api.Settings(weidu_log=["WeiDU.log"], target="Mods"),
                      cancel=cancel)
    assert outcome.exit_code == 130
    assert stub.downloaded == []


def test_run_leaves_the_settings_it_was_given_alone(workspace):  # noqa: F811
    tmp_path, _stub = workspace
    (tmp_path / "selection.json").write_text(json.dumps({
        "schema_version": 1, "installs": [{"game": "BG2EE", "components": [
            {"tp2": "DlcMerger/DlcMerger.tp2", "component": 3}]}]}))
    settings = api.Settings(selection="selection.json", target="Mods", check_only=True)
    api.run(settings)
    assert settings.weidu_log == []


def test_list_mods_from_a_catalogue_alone(tmp_path):
    path = tmp_path / "lcc.json"
    path.write_text(json.dumps([{"tp2": "eefixpack", "name": "EE Fixpack"}]))
    mods = api.list_mods(None, catalogues=[str(path)])
    assert [m.key for m in mods] == ["eefixpack"]


def test_a_selection_is_read_and_made_from_logs():
    selection = api.selection_of_logs([os.path.join(DATA, "WeiDUBGEE.log") + ":BGEE"])
    assert selection.installs[0].game == "BGEE"
    assert selection.installs[0].components


def test_a_bad_selection_raises_a_config_error_with_its_code(tmp_path):
    from iemod_fetch.errors import ConfigError
    path = tmp_path / "s.json"
    path.write_text("{}")
    with pytest.raises(ConfigError) as caught:
        api.load_selection(str(path))
    assert caught.value.code == "config"


def test_games_unseen_says_why_only_in_a_sandbox(tmp_path, monkeypatch):
    from iemod_fetch import gamelock
    info = tmp_path / ".flatpak-info"
    info.write_text("[Application]\n")
    monkeypatch.setattr(gamelock, "FLATPAK_INFO", str(info))
    assert "Flatpak" in (api.games_unseen() or "")
    monkeypatch.setattr(gamelock, "FLATPAK_INFO", str(tmp_path / "absent"))
    assert api.games_unseen() is None


def test_start_install_refuses_an_unseen_game_without_the_flag(tmp_path, monkeypatch):
    from iemod_fetch import gamelock, install_run
    from iemod_fetch.errors import ConfigError
    info = tmp_path / ".flatpak-info"
    info.write_text("[Application]\n")
    monkeypatch.setattr(gamelock, "FLATPAK_INFO", str(info))
    seen = []

    def preflight(*args, **kwargs):
        seen.append(kwargs.get("confirmed_closed"))
        return gamelock.problems({"BG2EE": str(tmp_path)},
                                 confirmed_closed=kwargs.get("confirmed_closed", False))
    monkeypatch.setattr(install_run, "preflight", preflight)
    with pytest.raises(ConfigError, match="confirm it is closed"):
        api.start_install(str(tmp_path), {"BG2EE": str(tmp_path)}, str(tmp_path), "mi",
                          "weidu", ask=lambda *_a: None, questions={"components": []})
    assert seen == [False]
