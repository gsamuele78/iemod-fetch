"""ADR-0057: mod_installer's parser config for one install."""
import os
import sys
import tomllib
from pathlib import Path

import pytest

from iemod_fetch import mi_parser

# What the real mod_installer 16.0.0 writes as its defaults (built from the
# release's source, run once with an empty XDG_CONFIG_HOME)
REFERENCE = Path(__file__).parent / "data" / "mod_installer-16.0.0-parser.toml"


def test_the_defaults_are_mod_installers_own():
    ours = tomllib.loads(mi_parser.toml([]))
    real = tomllib.loads(REFERENCE.read_text())
    assert ours.keys() == real.keys()
    for key in real:
        if key != "metadata":
            assert ours[key] == real[key], key
    assert ours["metadata"]["mod_installer_version"] == "16.0.0"
    assert ours["metadata"]["created"].keys() == real["metadata"]["created"].keys()


def test_extra_phrases_are_added_once_and_sorted():
    data = tomllib.loads(mi_parser.toml(["zz top question", "do you want"]))
    real = tomllib.loads(REFERENCE.read_text())
    assert data["choice_phrase"] == sorted({*real["choice_phrase"], "zz top question"})


@pytest.mark.parametrize(("text", "phrase"), [
    ("How many extra kits should be installed?", "how many extra kits should be installed?"),
    # the last line is the one WeiDU prints just before it reads
    ("Kits\nHow many extra kits should be added?", "how many extra kits should be added?"),
    # a variable: the longest literal piece of the line
    ("Type the number for %name% kit portraits", "type the number for"),
    ("Pick your kit: 1, 2 or 3", "pick your kit: 1, 2 or 3"),
    ("Do you want the new portraits?", None),             # asked already
    ("Installing the extra kits, how many?", None),       # a progress word: never a question
    ("Short one?", None),                                 # too short to tell apart
    ("%a% and %b%", None),
    ("", None),
])
def test_the_phrase_of_a_question(text, phrase):
    assert mi_parser.phrase(text) == phrase


def test_the_phrase_is_lowercased_as_rust_does_ascii_only():
    """to_ascii_lowercase leaves É as it is: the phrase must too, or it never
    matches the line mod_installer compares."""
    assert mi_parser.phrase("ÉCRIVEZ LE NOMBRE DE KITS") == "Écrivez le nombre de kits"


def test_phrases_of_an_install():
    expected = {("a.tp2", 0): [("q1", "How many extra kits should be installed?"),
                               ("q2", "Do you want it?")],
                ("b.tp2", 1): [("q1", "How many extra kits should be installed?"),
                               ("q3", "")]}
    assert mi_parser.phrases(expected) == ["how many extra kits should be installed?"]


def test_toml_strings_are_escaped():
    data = tomllib.loads(mi_parser.toml(['say "yes" \\ now\tplease']))
    assert 'say "yes" \\ now\tplease' in data["choice_phrase"]


@pytest.mark.parametrize(("platform", "variable", "parts"), [
    ("linux", "XDG_CONFIG_HOME", ("mod_installer", "parser.toml")),
    ("darwin", "XDG_CONFIG_HOME", ("mod_installer", "parser.toml")),
    ("win32", "APPDATA", ("mod_installer", "config", "parser.toml")),
])
def test_where_mod_installer_looks(tmp_path, platform, variable, parts):
    env, extra = mi_parser.write(str(tmp_path), {("a.tp2", 0): [("q", "How many extra kits?? ok")]},
                                 platform=platform)
    assert env == {variable: str(tmp_path)}
    path = tmp_path.joinpath(*parts)
    assert path.is_file()
    assert tomllib.loads(path.read_text())["metadata"]["mod_installer_version"] == "16.0.0"
    assert extra == ["how many extra kits?? ok"]


def test_the_install_points_mod_installer_at_its_own_config(tmp_path, monkeypatch):
    """The variable is set only in the child's environment, to a folder
    beside the plan - never the player's own."""
    from iemod_fetch.install_run import InstallRun
    variable = "APPDATA" if sys.platform == "win32" else "XDG_CONFIG_HOME"
    monkeypatch.setenv(variable, str(tmp_path / "players-own"))
    code = f"import os; print(os.environ['{variable}'])"
    lines = []
    run = InstallRun([sys.executable, "-c", code], [], cwd=str(tmp_path), ask=lambda q, b: None,
                     on_event=lambda e: lines.append(e.text),
                     parser_dir=str(tmp_path / "plan" / "mod_installer-config"),
                     expected={("a.tp2", 0): [("q", "How many extra kits should be installed?")]})
    assert run.run().returncode == 0
    assert str(tmp_path / "plan" / "mod_installer-config") in lines
    assert run.parser_phrases == ["how many extra kits should be installed?"]
    assert os.environ[variable] == str(tmp_path / "players-own")
    assert not (tmp_path / "players-own").exists()
