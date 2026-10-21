"""
Component names, the way WeiDU prints them (M2e).

Every case below is a form found while measuring tra.py against WeiDU 251's
own `--list-components` on 103 real mods (docs/TESTING.md): the expected
strings are what WeiDU printed, not what seemed sensible.
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.tra import component_names, describe, languages, mod_folder, parse_tra


def reader(files):
    return lambda path: files.get(path)


# ------------------------------------------------------------------ .tra
def test_tra_entries_in_every_delimiter():
    text = ('@1 = ~tilde~\n@2 = "quote"\n@3 = %percent%\n'
            '@4 = ~~~~~has ~tildes~ inside~~~~~\n')
    assert parse_tra(text) == {1: "tilde", 2: "quote", 3: "percent",
                               4: "has ~tildes~ inside"}


def test_tra_female_text_and_sound_are_skipped():
    assert parse_tra("@1 = ~he~ ~she~ [SND01]\n@2 = ~next~") == {1: "he", 2: "next"}


def test_tra_comments_are_not_entries():
    text = "// @1 = ~no~\n/* @2 = ~no~ */\n@3 = ~yes // not a comment~\n"
    assert parse_tra(text) == {3: "yes // not a comment"}


def test_a_later_tra_entry_wins():
    assert parse_tra("@1 = ~old~\n@1 = ~new~") == {1: "new"}


def test_a_bare_word_is_a_tra_value():
    """thepicturestandard: `@30=BG1NPC`; WeiDU prints BG1NPC."""
    assert parse_tra("@30=BG1NPC\n@3000=~Vanilla~") == {30: "BG1NPC", 3000: "Vanilla"}


# ------------------------------------------------------------- LANGUAGE
def test_language_names_and_directories_may_be_bare_words():
    """SCS writes `LANGUAGE ENGLISH english ~...~`: skipping it would shift
    every later language index."""
    tp2 = ("LANGUAGE ENGLISH english ~scs/tra/english/setup.tra~\n"
           "LANGUAGE ~Italiano~ ~italian~ ~scs/tra/italian/setup.tra~\n")
    assert [(lang.name, lang.directory, lang.tra_files) for lang in languages(tp2)] == [
        ("ENGLISH", "english", ["scs/tra/english/setup.tra"]),
        ("Italiano", "italian", ["scs/tra/italian/setup.tra"])]


def test_mod_folder_is_the_backup_directory_not_the_tp2_directory():
    """LCA keeps EE/LCA.tp2 with BACKUP ~LCA/backup~: WeiDU 251 resolves
    %MOD_FOLDER% to LCA."""
    assert mod_folder("BACKUP ~LCA/backup~\n") == "LCA"
    assert mod_folder("BACKUP ~thepicturestandard\\backup~\n") == "thepicturestandard"
    assert mod_folder("AUTHOR ~x~\n") == ""


# ---------------------------------------------------------------- names
TP2 = r"""
BACKUP ~mymod/backup~
VERSION ~v3~
LANGUAGE ~English~ ~english~ ~%MOD_FOLDER%/tra/%LANGUAGE%/setup.tra~
                             ~mymod/tra/%LANGUAGE%/%WEIDU_OS%.tra~
LANGUAGE ~Italiano~ ~italian~ ~mymod/tra/italian/setup.tra~

BEGIN @1
BEGIN @2 DESIGNATED 10
SUBCOMPONENT @3
BEGIN @4
SUBCOMPONENT @3
BEGIN @99
"""
FILES = {
    "mymod/tra/english/setup.tra": "@1 = ~First~\n@2 = ~Fast~\n@3 = ~Speed~\n@4 = ~Two\nlines~",
    "mymod/tra/english/win32.tra": "@2 = ~Fast on Windows~",
    "mymod/tra/italian/setup.tra": "@1 = ~Primo~",
}


def test_names_are_printed_as_weidu_prints_them():
    names = component_names(TP2, 0, reader(FILES))
    assert [(c.number, c.name) for c in names] == [
        (0, "First: v3"),
        (10, "Speed -> Fast on Windows: v3"),       # the later .tra file wins
        (11, "Speed -> Two lines: v3"),             # a line break is a space
        (12, "UNDEFINED STRING:   @99: v3"),        # WeiDU's own words
    ]
    assert [c.resolved for c in names] == [True, True, True, False]


def test_weidu_os_selects_the_platform_tra():
    names = component_names(TP2, 0, reader(FILES), weidu_os="unix")
    assert names[1].title == "Fast"


def test_another_language_reads_its_own_tra():
    names = component_names(TP2, 1, reader(FILES))
    assert names[0].name == "Primo: v3"
    assert not names[1].resolved


def test_a_missing_tra_file_leaves_references_unresolved():
    names = component_names(TP2, 0, reader({}))
    assert not any(c.resolved for c in names[:2])


def test_describe_picks_the_first_preferred_language_offered():
    described = describe(TP2, reader(FILES), ["fr_FR", "it_IT"])
    assert described["language"] == 1
    assert described["languages"][1] == {"index": 1, "name": "Italiano",
                                         "directory": "italian"}
    assert described["components"][0] == {"number": 0, "name": "Primo: v3",
                                          "title": "Primo", "group": None,
                                          "resolved": True}


def test_describe_defaults_to_the_first_language():
    assert describe(TP2, reader(FILES))["language"] == 0


# ------------------------------------------------------- the api, on disk
def stage(root):
    mod = os.path.join(root, "MyMod")
    os.makedirs(os.path.join(mod, "TRA", "English"))
    with open(os.path.join(mod, "MyMod.tp2"), "w", encoding="utf-8") as fh:
        fh.write("BACKUP ~MyMod/backup~\nVERSION ~1.0~\n"
                 "LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~\n"
                 "BEGIN @1\nBEGIN @2\n")
    with open(os.path.join(mod, "TRA", "English", "setup.tra"), "wb") as fh:
        fh.write("@1 = ~Café~\n@2 = ~../escape~".encode("cp1252"))


def test_describe_mods_reads_staged_mods_case_insensitively(tmp_path):
    """Paths in a tp2 are matched as on Windows, and a pre-EE .tra in
    Windows-1252 still decodes."""
    stage(str(tmp_path))
    (mod,) = api.describe_mods(str(tmp_path))
    assert mod["tp2"] == "MyMod/MyMod.tp2"
    assert [c["name"] for c in mod["components"]] == ["Café: 1.0", "../escape: 1.0"]


def test_describe_mods_never_reads_outside_the_target(tmp_path):
    secret = tmp_path / "secret.tra"
    secret.write_text("@1 = ~leaked~")
    target = tmp_path / "Mods"
    (target / "x").mkdir(parents=True)
    (target / "x" / "x.tp2").write_text(
        "LANGUAGE ~English~ ~english~ ~../secret.tra~\nBEGIN @1\n")
    (mod,) = api.describe_mods(str(target))
    assert mod["components"][0]["resolved"] is False


def test_describe_mods_writes_the_versioned_document(tmp_path):
    stage(str(tmp_path / "Mods"))
    out = tmp_path / "components.json"
    outcome = api.run(api.Settings(describe_mods=str(out), target=str(tmp_path / "Mods")))
    assert outcome.exit_code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["mods"][0]["components"][0]["number"] == 0


def test_the_document_matches_its_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    stage(str(tmp_path / "Mods"))
    out = tmp_path / "components.json"
    api.run(api.Settings(describe_mods=str(out), target=str(tmp_path / "Mods")))
    schema_path = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                               "components-v1.schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        jsonschema.validate(json.loads(out.read_text(encoding="utf-8")), json.load(fh))
