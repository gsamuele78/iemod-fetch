"""
Phase 3, install order, driven like a player drives it (M3, GUI-AUDIT item
17, ADR-0038). The planner is injected: it answers as api.selection_plan does,
and reads the order the page saved (test_selection_plan.py checks the real
one against the run's planner).
"""
import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QModelIndex  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch_gui.pages.order import RED, OrderPage  # noqa: E402

PHASES = {"BG:EE before the conversion": ["bg1ub"],
          "EET": ["eet", "ub", "ascension", "EET_end"]}


def unit(name, constrained=False, flagged=False):
    return {"node": f"x|{name}|0", "name": name, "tp2": f"{name}/{name}.tp2",
            "key": name.lower(), "part": 0, "split": False, "category": "SOMEWHERE",
            "components": [[f"{name}/{name}.tp2", 0, ""]],
            "constrained": constrained, "moved": False, "flagged": flagged}


class Planner:
    """Plans by the saved order when there is one, else by PHASES; EET_end
    must stay last (a rule), so moving it away is a violation."""

    def __init__(self):
        self.calls = 0

    def __call__(self, game, chosen, labels, folder):
        self.calls += 1
        order = dict(PHASES)
        path = os.path.join(folder, api.INSTALL_ORDER_FILE)
        custom = os.path.isfile(path)
        if custom:
            with open(path, encoding="utf-8") as fh:
                names = [line.split()[0] for line in fh if line.strip()
                         and not line.startswith("//")]
            order = {"BG:EE before the conversion": [n for n in names if n == "bg1ub"],
                     "EET": [n for n in names if n != "bg1ub"]}
        broken = order["EET"][-1] != "EET_end"
        return {"phases": [{"role": title, "title": title, "units": [
                    unit(n, constrained=n == "EET_end", flagged=broken and n == "EET_end")
                    for n in names]} for title, names in order.items()],
                "cycles": [], "violations": ["EET_end should be installed last"] if broken
                else [], "planned": True, "custom": custom}


def page(qtbot, folder, planner=None):
    planner = planner or Planner()
    widget = OrderPage(str(folder), plan=planner)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.start("EET", [("ub/ub.tp2", 0)], {})
    return widget, planner


def texts(widget, tab):
    view = widget.tabs.widget(tab)
    return [view.item(row).text().split("  -  ")[0] for row in range(view.count())]


def drag(qtbot, widget, tab, row, to):
    view = widget.tabs.widget(tab)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        view.model().moveRow(QModelIndex(), row, QModelIndex(), to)


def test_each_eet_phase_is_a_tab_in_the_planned_order(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    assert [widget.tabs.tabText(i) for i in range(widget.tabs.count())] == [
        "BG:EE before the conversion (1)", "EET (4)"]
    assert texts(widget, 1) == ["eet", "ub", "ascension", "EET_end"]
    assert widget.is_complete() and not widget.reset.isEnabled()


def test_a_rule_placed_mod_is_bold(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    view = widget.tabs.widget(1)
    assert view.item(3).font().bold() and not view.item(1).font().bold()


def test_a_mod_its_kind_placed_says_so_and_one_it_could_not_says_why(qtbot, tmp_path):
    """Item 27: krion64 does not place newui or tweak; newui's kind decides."""
    def planner(game, chosen, labels, folder):
        units = [unit("eet"),
                 dict(unit("newui"), category="INTERFACE",
                      placed_by="placed by kind: interface, 92% / 100% (lcc-docs)"),
                 dict(unit("tweak"), category="",
                      no_place="no place: its kind does not decide one (gameplay)")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    view = widget.tabs.widget(0)
    assert view.item(1).text() == "newui  -  INTERFACE  (by kind)"
    assert "placed by kind: interface, 92% / 100% (lcc-docs)" in view.item(1).toolTip()
    assert "does not decide one (gameplay)" in view.item(2).toolTip()
    assert "1 placed by kind" in widget.summary.text()


def test_dragging_saves_the_order_the_cli_reads_and_plans_again(qtbot, tmp_path):
    widget, planner = page(qtbot, tmp_path)
    calls = planner.calls
    drag(qtbot, widget, 1, 2, 1)                 # ascension above ub
    assert planner.calls == calls + 1
    saved = (tmp_path / api.INSTALL_ORDER_FILE).read_text()
    assert saved.index("\nascension *") < saved.index("\nub *")
    assert "sorting_order" in (tmp_path / api.PROJECT_FILE).read_text()
    assert texts(widget, 1) == ["eet", "ascension", "ub", "EET_end"]
    assert widget.reset.isEnabled() and "your own order applies" in widget.summary.text()


def test_an_order_that_breaks_a_rule_is_marked_red_with_the_rule(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    drag(qtbot, widget, 1, 3, 0)                 # EET_end first
    view = widget.tabs.widget(1)
    flagged = next(view.item(r) for r in range(view.count()) if "EET_end" in view.item(r).text())
    assert flagged.foreground().color() == RED
    assert "EET_end should be installed last" in widget.problems.text()


def test_the_computed_order_can_be_used_again(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    drag(qtbot, widget, 1, 2, 1)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.reset.click()
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()
    assert texts(widget, 1) == ["eet", "ub", "ascension", "EET_end"]


def test_without_krion64s_data_the_phase_says_so_and_lets_you_go_on(qtbot, tmp_path):
    def unplanned(*_args):
        return {"phases": [], "cycles": [], "violations": [], "planned": False,
                "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner=unplanned)
    assert "krion64's data is not here yet" in widget.summary.text()
    assert widget.is_complete() and widget.tabs.count() == 0


def test_a_failing_plan_is_said_and_blocks_next(qtbot, tmp_path):
    def broken(*_args):
        raise RuntimeError("no rules")
    widget, _planner = page(qtbot, tmp_path, planner=broken)
    assert "no rules" in widget.summary.text() and not widget.is_complete()


def test_an_order_that_cannot_be_saved_is_said(qtbot, tmp_path, monkeypatch):
    widget, planner = page(qtbot, tmp_path)
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: shown.append(a[1]))
    monkeypatch.setattr(api, "save_install_order",
                        lambda *a: (_ for _ in ()).throw(OSError("read-only")))
    calls = planner.calls
    widget.tabs.widget(1).model().moveRow(QModelIndex(), 2, QModelIndex(), 1)
    assert shown == ["Cannot save the install order"] and planner.calls == calls


def test_a_plan_for_a_previous_selection_never_lands(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    old = widget._generation
    widget.start("EET", [("ub/ub.tp2", 0), ("ascension/ascension.tp2", 0)], {})
    widget._done((old, {"phases": [], "planned": True, "cycles": [], "violations": [],
                        "custom": False}, ""))
    qtbot.waitUntil(lambda: widget._planning is None, timeout=5000)
    assert widget.tabs.count() == 2
