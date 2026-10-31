"""
The questions a planned install will meet, before it starts (GUI-AUDIT item
48, ADR-0049): api.install_questions reads the planned WeiDU logs, scans each
component's mod in the log's language, and says which are answered.
"""
from iemod_fetch import api

TP2 = """BACKUP ~mymod/backup~
LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~
LANGUAGE ~Italiano~ ~italian~ ~mymod/tra/italian/setup.tra~
BEGIN @10 DESIGNATED 0
  PRINT @1
  ACTION_READLN portraits
BEGIN @11 DESIGNATED 10
  COPY_EXISTING ~sw1h01.itm~ ~override~
BEGIN @12 DESIGNATED 20
  ACTION_IF NOT FILE_EXISTS ~mymod/prefs.txt~ BEGIN
    PRINT @2
    ACTION_READLN chance
  END
BEGIN @13 DESIGNATED 30
  OUTER_SPRINT p @1
  PRINT ~%p%~
  ACTION_READLN other
"""


def project(tmp_path, log_lines):
    mods = tmp_path / "Mods" / "mymod"
    (mods / "tra" / "english").mkdir(parents=True)
    (mods / "tra" / "italian").mkdir(parents=True)
    (mods / "setup-mymod.tp2").write_text(TP2, encoding="utf-8")
    (mods / "tra" / "english" / "setup.tra").write_text(
        "@1 = ~Which portraits?~\n@2 = ~A percentage:~\n", encoding="utf-8")
    (mods / "tra" / "italian" / "setup.tra").write_text(
        "@1 = ~Quali ritratti?~\n@2 = ~Una percentuale:~\n", encoding="utf-8")
    plan = tmp_path / "install-plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    + "".join(line + "\n" for line in log_lines),
                                    encoding="utf-8")
    return str(plan), str(tmp_path / "Mods")


def by_number(found):
    return {c["number"]: c for c in found["components"]}


def test_each_component_says_what_it_asks_and_whether_it_is_answered(tmp_path):
    plan, mods = project(tmp_path, [
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // Portraits // @wlb-inputs: 2",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #10 // Swords",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #20 // Chance",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #30 // Other // @wlb-inputs: y"])
    found = by_number(api.install_questions(plan, mods))
    assert found[0]["status"] == "answered" and found[0]["recorded"] == ["2"]
    assert [q["text"] for q in found[0]["questions"]] == ["Which portraits?"]
    assert found[10]["status"] == "none" and found[10]["questions"] == []
    # asked only when a file is missing: no recorded answer is "unanswered",
    # never guessed either way
    assert found[20]["status"] == "unanswered"
    assert found[20]["questions"][0]["conditional"]
    # its text is set elsewhere: unknown, even with an answer recorded
    assert found[30]["status"] == "unknown" and not found[30]["questions"][0]["known"]


def test_the_questions_are_read_in_the_logs_language(tmp_path):
    plan, mods = project(tmp_path, ["~MYMOD/SETUP-MYMOD.TP2~ #1 #0 // Ritratti"])
    [component] = api.install_questions(plan, mods)["components"]
    assert component["questions"][0]["text"] == "Quali ritratti?"
    assert component["questions"][0]["key"] == "@1"


def test_unattended_only_when_nothing_is_left_to_ask(tmp_path):
    plan, mods = project(tmp_path, [
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // Portraits // @wlb-inputs: 1",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #10 // Swords"])
    found = api.install_questions(plan, mods)
    assert found["unattended"] and found["counts"] == {"answered": 1, "none": 1}
    plan, mods = project(tmp_path / "b", [
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // Portraits"])
    assert not api.install_questions(plan, mods)["unattended"]


def test_a_mod_missing_from_the_mods_folder_is_said_so(tmp_path):
    plan, mods = project(tmp_path, ["~OTHER/SETUP-OTHER.TP2~ #0 #0 // Missing"])
    [component] = api.install_questions(plan, mods)["components"]
    assert component["status"] == "unknown"
    assert component["unread"] == ["OTHER/SETUP-OTHER.TP2 (not given)"]
