"""
The phase-5 questionnaire's answers (ADR-0049 points 2 and 5): which
questions can be answered before the install, the answers kept in the
project, and written into the planned logs as `// @wlb-inputs:` - only where
the order of the questions makes them land on the right one.
"""
import pytest

from iemod_fetch import api, prompts

TP2 = """BACKUP ~mymod/backup~
LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~
BEGIN @10 DESIGNATED 0
  PRINT @1
  ACTION_READLN portraits
  PRINT @3
  ACTION_READLN size
BEGIN @11 DESIGNATED 10
  PRINT @1
  ACTION_READLN first
  ACTION_IF NOT FILE_EXISTS ~mymod/prefs.txt~ BEGIN
    PRINT @2
    ACTION_READLN chance
  END
  PRINT @3
  ACTION_READLN after
BEGIN @12 DESIGNATED 20
  OUTER_SET ok = 0
  OUTER_WHILE ok = 0 BEGIN
    PRINT @2
    ACTION_READLN chance
    OUTER_SET ok = 1
  END
  PRINT @3
  ACTION_READLN size
BEGIN @13 DESIGNATED 30
  OUTER_SPRINT p @1
  PRINT ~%p%~
  ACTION_READLN other
  PRINT @3
  ACTION_READLN size
BEGIN @14 DESIGNATED 40
  COPY_EXISTING ~sw1h01.itm~ ~override~
"""


def project(tmp_path, log_lines):
    mods = tmp_path / "Mods" / "mymod"
    (mods / "tra" / "english").mkdir(parents=True)
    (mods / "setup-mymod.tp2").write_text(TP2, encoding="utf-8")
    (mods / "tra" / "english" / "setup.tra").write_text(
        "@1 = ~Which portraits?~\n@2 = ~A percentage:~\n@3 = ~How big?~\n", encoding="utf-8")
    plan = tmp_path / "install-plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    + "".join(line + "\n" for line in log_lines),
                                    encoding="utf-8")
    return str(plan), str(tmp_path / "Mods")


ALL = [f"~MYMOD/SETUP-MYMOD.TP2~ #0 #{n} // c{n}" for n in (0, 10, 20, 30, 40)]


def by_number(found):
    return {c["number"]: c for c in found["components"]}


def ahead(component):
    return [q["beforehand"] for q in component["questions"]]


def test_which_questions_can_be_answered_beforehand(tmp_path):
    found = by_number(api.install_questions(*project(tmp_path, ALL)))
    assert ahead(found[0]) == [True, True]                 # both surely asked, in order
    # under a condition: if it were not asked, its answer would go to the next
    assert ahead(found[10]) == [True, False, False]
    # asked until valid: answered, but nothing after it (a refused answer would
    # go to the next question)
    assert ahead(found[20]) == [True, False]
    # unknown text (status unknown): nothing beforehand
    assert found[30]["status"] == "unknown" and ahead(found[30]) == [False, False]
    assert found[40]["questions"] == []


def test_answers_are_kept_in_the_project(tmp_path):
    assert api.load_install_answers(str(tmp_path)) == {}
    api.save_install_answers(str(tmp_path), {"setup-mymod.tp2#0": {"@1": "2", "@3": ""}})
    assert api.load_install_answers(str(tmp_path)) == {"setup-mymod.tp2#0": {"@1": "2", "@3": ""}}
    (tmp_path / api.INSTALL_ANSWERS_FILE).write_text("not json")
    assert api.load_install_answers(str(tmp_path)) == {}       # unreadable: none


def test_answers_go_into_the_planned_log_in_order(tmp_path):
    plan, mods = project(tmp_path, ALL)
    answers = {"setup-mymod.tp2#0": {"@1": "2", "@3": ""},           # Enter is an answer
               "setup-mymod.tp2#10": {"@1": "y", "@2": "50", "@3": "big"},
               "setup-mymod.tp2#20": {"@2": "30", "@3": "small"}}
    found = by_number(api.write_install_answers(plan, mods, answers))
    log = (tmp_path / "install-plan" / "WeiDU.log").read_text(encoding="utf-8")
    assert "#0 // c0 // @wlb-inputs: 2,\n" in log
    # only the answer before the condition: the others are asked during the install
    assert "#10 // c10 // @wlb-inputs: y\n" in log
    assert "#20 // c20 // @wlb-inputs: 30\n" in log
    assert "#40 // c40\n" in log and "#30 // c30\n" in log
    assert found[0]["status"] == "answered"
    assert found[10]["status"] == "partial" and found[20]["status"] == "partial"


def test_a_missing_answer_ends_the_row_and_a_rewrite_replaces_the_old_one(tmp_path):
    plan, mods = project(tmp_path, ALL)
    api.write_install_answers(plan, mods, {"setup-mymod.tp2#0": {"@1": "2", "@3": "x"}})
    api.write_install_answers(plan, mods, {"setup-mymod.tp2#0": {"@3": "x"}})
    log = (tmp_path / "install-plan" / "WeiDU.log").read_text(encoding="utf-8")
    # the first question has no answer now: nothing is written (the line as planned
    # keeps the earlier answers - a plan is written afresh before each install)
    assert log.count("@wlb-inputs") == 1


def test_an_answer_with_a_comma_cannot_be_written():
    log = "~A/SETUP-A.TP2~ #0 #0 // a\n"
    with pytest.raises(ValueError, match="comma"):
        prompts.set_inputs(log, {("setup-a.tp2", 0): ["1,2"]})


def test_set_inputs_keeps_every_other_line():
    log = ("// Log of Currently Installed WeiDU Mods\n"
           "~A/SETUP-A.TP2~ #0 #0 // a // @wlb-inputs: old\n"
           "~B/SETUP-B.TP2~ #0 #5 // b\n")
    out = prompts.set_inputs(log, {("setup-a.tp2", 0): ["n", ""], ("setup-b.tp2", 5): ["y"]})
    assert out == ("// Log of Currently Installed WeiDU Mods\n"
                   "~A/SETUP-A.TP2~ #0 #0 // a // @wlb-inputs: n,\n"
                   "~B/SETUP-B.TP2~ #0 #5 // b // @wlb-inputs: y\n")
    assert prompts.recorded_answers(out) == {("setup-a.tp2", 0): ["n", ""],
                                             ("setup-b.tp2", 5): ["y"]}
    assert prompts.set_inputs(out, {("setup-a.tp2", 0): []}).splitlines()[1] == \
        "~A/SETUP-A.TP2~ #0 #0 // a"
