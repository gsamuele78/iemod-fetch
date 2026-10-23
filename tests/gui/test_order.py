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
from iemod_fetch_gui.pages.order import RED, ROLE, OrderPage  # noqa: E402

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


def test_a_mod_bws_ngs_sequence_placed_says_so(qtbot, tmp_path):
    """Decision 2a: BWS-NG's EET sequence placed it, before any kind."""
    def planner(game, chosen, labels, folder):
        units = [unit("eet"), dict(unit("allison"), category="NEW NPC MODS",
                                   placed_by="placed by BWS-NG's EET sequence: after alassa #0",
                                   placed_from="BWS-NG")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    assert widget.tabs.widget(0).item(1).text() == "allison  -  NEW NPC MODS  (by BWS-NG)"
    assert "1 placed by BWS-NG's sequence" in widget.summary.text()
    assert "placed by kind" not in widget.summary.text()


def test_the_players_own_order_supersedes_a_place_by_kind(qtbot, tmp_path):
    """Review of #67 (L1): with install-order.txt the kind places nothing."""
    def planner(game, chosen, labels, folder):
        units = [unit("eet"), dict(unit("newui"), category="INTERFACE",
                                   placed_by="placed by kind: interface, 92% / 100%")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": True}
    widget, _planner = page(qtbot, tmp_path, planner)
    item = widget.tabs.widget(0).item(1)
    assert "(by kind)" not in item.text()
    assert "your own order applies" in item.toolTip()
    assert "placed by kind" not in widget.summary.text()


def test_a_mod_split_into_components_is_saved_one_line_each(qtbot, tmp_path):
    """M5b item 30: split a mod, then each component is a row of its own."""
    calls = []

    def planner(game, chosen, labels, folder):
        calls.append(1)
        tweaks = dict(unit("cdtweaks"), components=[["cdtweaks/cdtweaks.tp2", n, ""]
                                                     for n in (10, 20, 30)])
        return {"phases": [{"role": "EET", "title": "EET",
                            "units": [unit("eet"), tweaks, unit("stratagems")]}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    view = widget.tabs.widget(0)
    view.setCurrentRow(0)
    assert not widget.split.isEnabled()              # one component: nothing to split
    view.setCurrentRow(1)
    assert widget.split.isEnabled()
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.split.click()
    lines = (tmp_path / api.INSTALL_ORDER_FILE).read_text().splitlines()
    assert [line for line in lines if not line.startswith("//")] == [
        "eet *", "cdtweaks 10", "cdtweaks 20", "cdtweaks 30", "stratagems *"]
    assert len(calls) == 2                           # planned again


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


# --------------------------------------------- review follow-ups (#74)
def lines_of(folder):
    return [line for line in (folder / api.INSTALL_ORDER_FILE).read_text().splitlines()
            if not line.startswith("//")]


class Slow:
    """A planner that answers from the saved order, and waits for `gate`
    once it is set - as a plan fetching metadata may, for seconds."""

    def __init__(self):
        import threading
        self.gate = None
        self.event = threading.Event

    def __call__(self, game, chosen, labels, folder):
        if self.gate is not None:
            self.gate.wait(5)
        units = [unit("eet"),
                 dict(unit("cdtweaks"), components=[["cdtweaks/cdtweaks.tp2", n, ""]
                                                    for n in (10, 20, 30)]),
                 unit("stratagems")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}


def test_a_drag_while_the_plan_is_made_keeps_the_split(qtbot, tmp_path):
    """Review of #74 (blocking): the split is in the list at once, so a drag
    before the plan comes back saves it rather than the mod whole."""
    planner = Slow()
    widget, _planner = page(qtbot, tmp_path, planner)
    planner.gate = planner.event()
    view = widget.tabs.widget(0)
    view.setCurrentRow(1)
    widget.split.click()                             # the plan now waits on the gate
    assert [view.item(r).data(ROLE)["components"][0][1] for r in (1, 2, 3)] == [10, 20, 30]
    assert not widget.split.isEnabled() and not widget.join.isEnabled()
    view.model().moveRow(QModelIndex(), 4, QModelIndex(), 0)       # stratagems to the top
    assert lines_of(tmp_path) == ["stratagems *", "eet *", "cdtweaks 10", "cdtweaks 20",
                                  "cdtweaks 30"]
    with qtbot.waitSignal(widget.planned, timeout=5000):
        planner.gate.set()


def test_the_parts_of_a_split_mod_are_joined_again(qtbot, tmp_path):
    """Review of #74: one split undone, the other moves kept."""
    widget, _planner = page(qtbot, tmp_path, Slow())
    view = widget.tabs.widget(0)
    view.setCurrentRow(1)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.split.click()
    assert lines_of(tmp_path)[1:4] == ["cdtweaks 10", "cdtweaks 20", "cdtweaks 30"]
    # the Slow planner answers the mod whole again; put the parts back on screen
    view = widget.tabs.widget(0)                     # the plan rebuilt the tab
    view.takeItem(1)
    for offset, number in enumerate((10, 20, 30)):
        view.insertItem(1 + offset, widget._item(dict(
            unit("cdtweaks"), split=True, components=[["cdtweaks/cdtweaks.tp2", number, ""]])))
    view.setCurrentRow(0)
    view.setCurrentRow(2)
    assert widget.join.isEnabled()
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.join.click()
    assert lines_of(tmp_path) == ["eet *", "cdtweaks *", "stratagems *"]


def test_split_and_drag_on_the_real_planner_agree_with_the_command_line(qtbot, tmp_path):
    """Review of #74 (acceptance on the real path): the run's own planner,
    Split on eefixpack, its #1 dragged just after the EET core, then
    --plan-order with the same selection and order - row for row."""
    here = os.path.join(os.path.dirname(__file__), os.pardir)
    mock = os.path.join(here, "data", "eetmock")
    krion = os.path.join(here, "data", "krion")
    from test_selection_plan import CHOSEN

    def real(game, chosen, labels, folder):
        return api.selection_plan(game, chosen, labels, folder=folder,
                                  order_catalogue=krion, rules=[os.path.join(mock, "rules")],
                                  target=os.path.join(mock, "Mods"),
                                  data_dir=os.path.join(folder, "no-cache"))
    widget = OrderPage(str(tmp_path), plan=real)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.start("EET", CHOSEN, {})
    widget.tabs.setCurrentIndex(1)
    view = widget.tabs.widget(1)
    rows = lambda: [view.item(r).data(ROLE) for r in range(view.count())]  # noqa: E731
    view.setCurrentRow(next(r for r, u in enumerate(rows()) if u["key"] == "eefixpack"))
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.split.click()
    view = widget.tabs.widget(1)
    source = next(r for r, u in enumerate(rows()) if u["key"] == "eefixpack"
                  and u["components"][0][1] == 1)
    core = next(r for r, u in enumerate(rows()) if u["key"] == "eet")
    with qtbot.waitSignal(widget.planned, timeout=10000):
        view.model().moveRow(QModelIndex(), source, QModelIndex(), core + 1)
    view = widget.tabs.widget(1)
    page_order = [(c[0].split("/")[0].lower(), c[1]) for u in rows() for c in u["components"]]
    assert page_order.index(("eefixpack", 1)) == page_order.index(("eet", 0)) + 1

    api.save_selection(str(tmp_path), "EET", CHOSEN, order_catalogue=krion)
    api.run(api.Settings(
        selection=str(tmp_path / api.SELECTION_FILE),
        sorting_order=str(tmp_path / api.INSTALL_ORDER_FILE),
        check_only=True, quiet=True, manifest=os.path.join(here, "data", "mod_downloads.json"),
        target=os.path.join(mock, "Mods"), rules=[os.path.join(mock, "rules")],
        order_catalogue=krion, plan_order=str(tmp_path / "plan"),
        data_dir=str(tmp_path / "no-cache"), no_update_data=True, no_default_data=True))
    written = [(line[1:].split("\\")[0].lower(), int(line.split("#")[2].split()[0]))
               for line in (tmp_path / "plan" / "WeiDU.log").read_text().splitlines()
               if line.startswith("~")]
    assert written == page_order


# ---------------------------------------- the check after a drop (item 31)
def test_a_drop_is_checked_at_once_before_the_plan_comes_back(qtbot, tmp_path):
    """M5b item 31: dragging stratagems above cdtweaks, which a rule puts
    first, marks both red at once - the plan is still being made."""
    import threading
    gate = threading.Event()
    calls = []

    def planner(game, chosen, labels, folder):
        if calls:
            gate.wait(5)
        calls.append(1)
        units = [unit("eet"), unit("cdtweaks"),
                 dict(unit("stratagems"), after=["x|cdtweaks|0"])]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    view = widget.tabs.widget(0)
    assert view.item(2).foreground().color() != RED
    view.model().moveRow(QModelIndex(), 2, QModelIndex(), 1)      # stratagems up one
    assert [view.item(r).data(ROLE)["name"] for r in range(3)] == [
        "eet", "stratagems", "cdtweaks"]
    assert view.item(1).foreground().color() == RED
    assert view.item(2).foreground().color() == RED
    assert view.item(0).foreground().color() != RED
    assert "1 rule(s) broken" in widget.problems.text()
    assert widget.last_check_ms < 100
    with qtbot.waitSignal(widget.planned, timeout=5000):
        gate.set()


def test_a_drop_downward_marks_the_row_it_moved(qtbot, tmp_path):
    """Review of #75: a row dropped lower lands one above the row Qt names,
    and that is the row checked - cdtweaks below stratagems breaks the rule."""
    import threading
    gate = threading.Event()
    calls = []

    def planner(game, chosen, labels, folder):
        if calls:
            gate.wait(5)
        calls.append(1)
        units = [unit("eet"), unit("cdtweaks"),
                 dict(unit("stratagems"), after=["x|cdtweaks|0"]), unit("eet_end")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    view = widget.tabs.widget(0)
    view.model().moveRow(QModelIndex(), 1, QModelIndex(), 3)      # cdtweaks down one
    assert [view.item(r).data(ROLE)["name"] for r in range(4)] == [
        "eet", "stratagems", "cdtweaks", "eet_end"]
    assert [view.item(r).foreground().color() == RED for r in range(4)] == [
        False, True, True, False]
    assert "1 rule(s) broken" in widget.problems.text()
    with qtbot.waitSignal(widget.planned, timeout=5000):
        gate.set()


def test_a_drag_after_a_split_leaves_the_marks_to_the_plan(qtbot, tmp_path):
    """Review of #75: until the plan comes back, a split mod's parts share
    its node, so a drop is not checked at once - no row is marked by a
    guess, and the plan that follows marks them."""
    planner = Slow()
    widget, _planner = page(qtbot, tmp_path, planner)
    planner.gate = planner.event()
    view = widget.tabs.widget(0)
    view.setCurrentRow(1)
    widget.split.click()
    view.model().moveRow(QModelIndex(), 1, QModelIndex(), 5)       # a part to the end
    assert widget.problems.text() == "Checked when the plan comes back."
    assert not any(view.item(r).foreground().color() == RED for r in range(view.count()))
    with qtbot.waitSignal(widget.planned, timeout=5000):
        planner.gate.set()
