"""
Phase 2's conflicts panel, driven like a player drives it (M3, GUI-AUDIT
item 16, ADR-0033). The checker is injected: it answers the way
api.selection_conflicts answers, from the selection it is given, so the tests
need no rules and no community data (test_selection_conflicts.py checks the
real one against the command line).
"""
import json

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QInputDialog, QLabel, QMessageBox  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch_gui.pages.mods import ModsPage  # noqa: E402

UB = "bg1ub/setup-bg1ub.tp2"
TW = "cdtweaks/setup-cdtweaks.tp2"
NEED = "needed/setup-needed.tp2"


def component(number, name):
    return {"number": number, "name": name, "subgroup": "", "exclusive": "",
            "groups": [], "requires": [], "forced": False}


def mod(key, tp2, numbers, category="Tweaks"):
    return {"key": key, "name": key, "games": ["EET"], "categories": [category],
            "status": [], "advisories": [],
            "tp2s": [{"tp2": tp2, "origin": "krion64",
                      "components": [component(n, f"{key} {n}") for n in numbers]}]}


MODS = [mod("bg1ub", UB, [0, 10]), mod("cdtweaks", TW, [100, 200]),
        mod("needed", NEED, [0]), mod("bystander", "bystander/b.tp2", [1])]


def option(oid, action, key, components, chosen=(), text=""):
    return {"id": oid, "action": action, "mod": key, "key": key,
            "components": list(components), "whole_mod": False, "cost": len(components),
            "applicable": action != "install", "recommended": False,
            "description": text or f"{action} {key}", "chosen": [list(c) for c in chosen]}


def side(key, numbers, chosen):
    return {"mod": key, "components": list(numbers), "whole_mod": False, "key": key,
            "chosen": [list(c) for c in chosen]}


class Checker:
    """api.selection_conflicts' answers for this little catalogue."""

    def __init__(self):
        self.calls = 0

    def __call__(self, game, chosen, labels, project_dir):
        self.calls += 1
        decided = api.load_decisions(project_dir)
        findings = []
        if (UB, 10) in chosen and (TW, 200) in chosen:
            findings.append({
                "id": "conflict-0000000000000001", "kind": "incompatible",
                "severity": "error", "fixed_by_plan": None, "evidence": "",
                "reason": "<b>both</b> patch the same file", "workaround": "",
                "left": side("bg1ub", [10], [(UB, 10)]),
                "right": side("cdtweaks", [200], [(TW, 200)]),
                "options": [option("option-000000000000000a", "deselect", "cdtweaks",
                                   [200], [(TW, 200)]),
                            option("option-000000000000000b", "deselect", "bg1ub",
                                   [10], [(UB, 10)])]})
        if (TW, 100) in chosen:
            findings.append({
                "id": "conflict-0000000000000002", "kind": "depends",
                "severity": "error", "fixed_by_plan": None, "evidence": "",
                "reason": "needs it", "workaround": "",
                "left": side("cdtweaks", [100], [(TW, 100)]),
                "right": side("needed", [0], []),
                "options": [option("option-000000000000000c", "install", "needed", [0]),
                            option("option-000000000000000d", "install", "absent", [5]),
                            option("option-000000000000000e", "reorder", "cdtweaks", [],
                                   text="install needed before cdtweaks")]})
        for finding in findings:
            fid = finding["id"]
            finding["decision"] = ({"choose": decided["choose"][fid]}
                                   if fid in decided["choose"] else
                                   {"accept": decided["accept"][fid]}
                                   if fid in decided["accept"] else None)
        return {"findings": findings, "stale": [], "rules_checked": 2, "planned": True,
                "problem": decided["problem"]}


def page(qtbot, folder, checker=None):
    checker = checker or Checker()
    widget = ModsPage(str(folder), load=lambda game, project: json.loads(json.dumps(MODS)),
                      check=checker)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.start("EET")
    return widget, checker


def choose(qtbot, widget, *keys, on=True):
    with qtbot.waitSignal(widget.checked, timeout=5000):
        for key in keys:
            widget.items[key].setCheckState(
                0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def click(qtbot, widget, button_id):
    button = widget.panel.buttons[button_id]
    assert button.isEnabled()
    with qtbot.waitSignal(widget.checked, timeout=5000):
        button.click()


def open_ids(widget):
    return [f["id"] for f in widget.conflicts["findings"] if not f["decision"]]


def test_a_burst_of_choices_is_checked_once_after_it_ends(qtbot, tmp_path):
    widget, checker = page(qtbot, tmp_path)
    before = checker.calls
    choose(qtbot, widget, (UB, 10), (TW, 200))
    assert checker.calls == before + 1
    assert open_ids(widget) == ["conflict-0000000000000001"]
    assert widget.tabs.tabText(1) == "Conflicts (1)"


def test_deselecting_a_side_unchooses_it_and_clears_the_conflict(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    click(qtbot, widget, "option-000000000000000a")
    assert widget.chosen() == [(UB, 10)] and open_ids(widget) == []
    assert widget.tabs.tabText(1) == "Conflicts"


def test_a_missing_prerequisite_is_chosen_when_the_list_knows_it(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    assert not widget.panel.buttons["option-000000000000000d"].isEnabled()   # not listed
    click(qtbot, widget, "option-000000000000000c")
    assert (NEED, 0) in widget.chosen()


def test_a_reorder_is_written_to_decisions_json_and_can_be_undone(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    click(qtbot, widget, "option-000000000000000e")
    assert api.load_decisions(str(tmp_path))["choose"] == {
        "conflict-0000000000000002": "option-000000000000000e"}
    assert open_ids(widget) == []
    assert "1 decided" in widget.panel.summary.text()
    undo = next(b for b in widget.panel.findChildren(type(widget.panel.again))
                if b.text() == "Undo")
    with qtbot.waitSignal(widget.checked, timeout=5000):
        undo.click()
    assert api.load_decisions(str(tmp_path))["choose"] == {}
    assert open_ids(widget) == ["conflict-0000000000000002"]


def test_accepting_asks_why_and_keeps_the_reason(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("tested it", True))
    click(qtbot, widget, "accept:conflict-0000000000000002")
    assert api.load_decisions(str(tmp_path))["accept"] == {
        "conflict-0000000000000002": "tested it"}


def test_an_unreadable_decisions_file_is_never_overwritten(qtbot, tmp_path, monkeypatch):
    (tmp_path / api.DECISIONS_FILE).write_text("{ hand-edited")
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    assert "could not be read" in " ".join(
        label.text() for label in widget.panel.findChildren(QLabel))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: shown.append(a[1]))
    widget.panel.buttons["option-000000000000000e"].click()
    assert shown == ["decisions.json cannot be read"]
    assert (tmp_path / api.DECISIONS_FILE).read_text() == "{ hand-edited"


def test_conflicts_only_shows_the_mods_still_to_decide(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    widget.filter.setCurrentText("Conflicts only")
    shown = [widget.tree.topLevelItem(i).text(0) for i in range(widget.tree.topLevelItemCount())
             if not widget.tree.topLevelItem(i).isHidden()]
    assert shown == ["bg1ub", "cdtweaks"]


def test_rule_text_is_shown_as_text_never_as_markup(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    labels = [label for label in widget.panel.findChildren(QLabel)
              if "patch the same file" in label.text()]
    assert labels and labels[0].textFormat() == Qt.TextFormat.PlainText
    assert labels[0].text() == "<b>both</b> patch the same file"


def test_a_failing_check_is_said_on_the_panel(qtbot, tmp_path):
    def broken(*_args):
        raise RuntimeError("rules unreadable")
    widget, _checker = page(qtbot, tmp_path, checker=broken)
    assert "rules unreadable" in widget.panel.summary.text()
