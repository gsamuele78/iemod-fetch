"""
Phase 3 - install order (GUI-AUDIT item 17, ADR-0038).

The chosen components as the run will install them: planned by the same
planner as --plan-order (krion64's categories, then every order rule, the
authors' own inis included), one tab per install - for EET, BG:EE before the
conversion and EET itself. A mod a rule places is marked; one an order rule
still finds wrong is marked in red, with the rule. A mod krion64 does not
place takes its place in BWS-NG's EET sequence, marked "by BWS-NG", else the
place its kind decides, marked "by kind" with its source, or says why it has
none (items 27 and 27a, ADR-0041).

Dragging a mod writes the whole order shown as `install-order.txt` in the
project - a Project Infinity Sorting Order file, which the command line reads
with --sorting-order (the project's ini names it) - and plans again: the
player's order goes on top of the rules, and where it contradicts one the
contradiction is shown, never silently won either way. "Use the computed
order" deletes the file. "Split into components" turns the selected mod into
one row per component, so a single component can be dragged on its own (M5b
item 30); its lines are written `tp2 n`, as the command line reads them.
"""
import os
from collections.abc import Callable

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from iemod_fetch import api

from .mods import Key, _in_thread, _target

Planner = Callable[[str, list[Key], dict, str], dict]
ROLE = Qt.ItemDataRole.UserRole
RED = QColor(176, 0, 32)


def plan_selection(game: str, chosen: list[Key], labels: dict, project_dir: str) -> dict:
    """The real planner: the run's own, on the project's data and install-order.txt."""
    project = api.load_project(project_dir)
    return api.selection_plan(game, chosen, labels, folder=project_dir,
                              target=_target(project), fetch_metadata=True)


def _plain(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class OrderPage(QWidget):
    completeChanged = Signal(bool)
    planned = Signal()

    def __init__(self, project_dir: str, plan: Planner = plan_selection) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.plan = plan
        self.result: dict = {}
        self.wanted: tuple[str, list[Key], dict] | None = None
        self._planning: QThread | None = None
        self._again = False
        self._generation = 0

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(lambda _index: self._can_split())
        self.summary = _plain("The order is planned once the mods are chosen.")
        self.problems = _plain("")
        self.problems.setStyleSheet("color: #b00020")
        self.reset = QPushButton("Use the computed order")
        self.reset.setToolTip(f"Forget the order set by hand ({api.INSTALL_ORDER_FILE})")
        self.reset.clicked.connect(self._reset)
        self.split = QPushButton("Split into components")
        self.split.setToolTip("One row per component of the selected mod, to move "
                              "one of them on its own")
        self.split.setEnabled(False)
        self.split.clicked.connect(self._split)
        self.join = QPushButton("Join the parts")
        self.join.setToolTip("The selected mod's parts in this tab as one row again")
        self.join.setEnabled(False)
        self.join.clicked.connect(self._join)
        bar = QHBoxLayout()
        bar.addWidget(self.summary, 1)
        bar.addWidget(self.split)
        bar.addWidget(self.join)
        bar.addWidget(self.reset)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>3. Install order</h2>"))
        layout.addWidget(_plain(
            "Drag a mod - or, split, one of its components - to change where it is "
            "installed. Bold: a rule places it. "
            "Red: a rule says it is in the wrong place. Your order is kept in "
            f"{api.INSTALL_ORDER_FILE}, which the command line uses too."))
        layout.addLayout(bar)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.problems)

    # ----------------------------------------------------------- planning
    def start(self, game: str, chosen: list[Key], labels: dict) -> None:
        """Plan `chosen` for `game`, in a worker thread."""
        self.wanted = (game, list(chosen), dict(labels))
        self._generation += 1
        self.result = {}
        self.completeChanged.emit(False)
        self._plan()

    def _plan(self) -> None:
        if self.wanted is None:
            return
        if self._planning is not None:
            self._again = True
            return
        self._again = False
        self.summary.setText("Planning the install order...")
        self.split.setEnabled(False)
        self.join.setEnabled(False)
        self.completeChanged.emit(False)        # Next waits for this plan
        plan, (game, chosen, labels) = self.plan, self.wanted
        generation, folder = self._generation, self.project_dir

        def run():
            try:
                return generation, plan(game, chosen, labels, folder), ""
            except Exception as exc:        # shown on the page, never a crash
                return generation, None, str(exc)
        self._planning = _in_thread(run, self._done, self._failed, self._finished)

    def _failed(self, message: str) -> None:
        self.summary.setText(f"The install order could not be planned: {message}")

    def _done(self, outcome: tuple) -> None:
        generation, result, problem = outcome
        if generation != self._generation:
            return                          # planned a selection no longer wanted
        if result is None:
            self.result = {}
            self.tabs.clear()
            self._failed(problem)
            self.completeChanged.emit(False)
            return
        self.show_result(result)

    def _finished(self) -> None:
        self._planning = None
        self._can_split()
        if self._again:
            self._plan()
            return
        self.completeChanged.emit(self.is_complete())   # the window refreshes Next
        self.planned.emit()

    def show_result(self, result: dict) -> None:
        self.result = result
        self.split.setEnabled(False)            # the rows it would split are gone
        self.join.setEnabled(False)
        current = self.tabs.currentIndex()
        self.tabs.clear()
        if not result.get("planned"):
            self.summary.setText("No install order to plan against: krion64's data is "
                                 "not here yet. The run will keep the order chosen.")
            self.problems.setText("")
            self.completeChanged.emit(True)
            return
        for phase in result["phases"]:
            self.tabs.addTab(self._list(phase), f"{phase['title']} "
                                                f"({len(phase['units'])})")
        self.tabs.setCurrentIndex(max(0, min(current, self.tabs.count() - 1)))
        units = [u for p in result["phases"] for u in p["units"]]
        parts = [f"{len({u['key'] for u in units})} mod(s) in order",
                 f"{sum(u['constrained'] for u in units)} placed by a rule",
                 f"{sum(u['moved'] for u in units)} moved from where they were chosen"]
        # a split mod is one mod placed by its kind, not one per part
        placed = {u["key"]: u.get("placed_from") for u in units if u.get("placed_by")}
        by_bws = sum(source == "BWS-NG" for source in placed.values())
        if result.get("custom"):
            parts.append("your own order applies")    # over every kind's place
        else:
            if len(placed) - by_bws:
                parts.insert(2, f"{len(placed) - by_bws} placed by kind")
            if by_bws:
                parts.insert(2, f"{by_bws} placed by BWS-NG's sequence")
        self.summary.setText("; ".join(parts) + ".")
        self.reset.setEnabled(bool(result.get("custom")))
        lines = list(result.get("violations") or [])
        lines += ["These rules contradict each other, one was set aside: "
                  + " -> ".join(cycle) for cycle in result.get("cycles") or []]
        self.problems.setText("\n".join(lines))
        self.completeChanged.emit(True)

    def _list(self, phase: dict) -> QListWidget:
        widget = QListWidget()
        widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for unit in phase["units"]:
            widget.addItem(self._item(unit))
        widget.model().rowsMoved.connect(lambda *_args: self._reordered())
        widget.currentItemChanged.connect(lambda *_args: self._can_split())
        return widget

    def _item(self, unit: dict) -> QListWidgetItem:
        custom = bool(self.result and self.result.get("custom"))
        text = unit["name"] + (f"  -  {unit['category']}" if unit["category"] else "")
        if unit.get("placed_by") and not custom:
            text += ("  (by BWS-NG)" if unit.get("placed_from") == "BWS-NG"
                     else "  (by kind)")
        item = QListWidgetItem(text)
        item.setData(ROLE, unit)
        components = ", ".join(f"#{c[1]}" for c in unit["components"][:12])
        tips = [f"Components: {components}"]
        if unit["constrained"]:
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
            tips.append("A rule places it relative to another mod.")
        if unit.get("placed_by") and custom:
            tips.append("krion64 does not place it; its kind would ("
                        + unit["placed_by"] + "), but your own order applies.")
        elif unit.get("placed_by"):
            tips.append("krion64 does not place it: " + unit["placed_by"] + ".")
        elif unit.get("no_place"):
            tips.append("krion64 does not place it, and it stays where it was "
                        "chosen - " + unit["no_place"] + ".")
        if unit["moved"]:
            tips.append("Moved from where it was chosen, by the rules.")
        if unit["flagged"]:
            item.setForeground(QBrush(RED))
            tips.append("An order rule says it is in the wrong place (see below).")
        item.setToolTip("\n".join(tips))
        return item

    # ---------------------------------------------------------- reordering
    def phases(self) -> list[list[dict]]:
        """Each tab's units, in the order shown."""
        out = []
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            out.append([widget.item(row).data(ROLE) for row in range(widget.count())])
        return out

    def _reordered(self) -> None:
        try:
            api.save_install_order(self.project_dir, self.phases())
        except Exception as exc:
            QMessageBox.critical(self, "Cannot save the install order", str(exc))
        # Planned again either way: the list must show what is saved, not
        # the drag that could not be.
        self._generation += 1
        self._plan()

    def _selected(self) -> tuple[QListWidget | None, int]:
        widget = self.tabs.currentWidget()
        if not isinstance(widget, QListWidget) or widget.currentRow() < 0:
            return None, -1
        return widget, widget.currentRow()

    def _can_split(self) -> None:
        """Split and Join act on the rows shown, and only once they are the
        plan's: while a plan is under way they wait (review of #74)."""
        widget, row = self._selected()
        unit = widget.item(row).data(ROLE) if widget is not None else None
        if widget is None or self._planning is not None or not isinstance(unit, dict):
            self.split.setEnabled(False)
            self.join.setEnabled(False)
            return
        self.split.setEnabled(len(unit["components"]) > 1)
        self.join.setEnabled(bool(unit.get("split"))
                             and len(self._parts(widget, unit["key"])) > 1)

    @staticmethod
    def _parts(widget: QListWidget, key: str) -> list[int]:
        """The rows of `widget` that are split parts of the mod `key`."""
        return [row for row in range(widget.count())
                if widget.item(row).data(ROLE)["key"] == key
                and widget.item(row).data(ROLE).get("split")]

    def _split(self) -> None:
        """The selected mod as one row per component, in its order - put in
        the list first and saved from it, as a drag is, so a drag or another
        split before the plan comes back keeps it (review of #74)."""
        widget, row = self._selected()
        if widget is None:
            return
        unit = widget.item(row).data(ROLE)
        if len(unit["components"]) < 2:
            return
        widget.takeItem(row)
        for offset, component in enumerate(unit["components"]):
            widget.insertItem(row + offset,
                              self._item(dict(unit, components=[component], split=True)))
        self._reordered()

    def _join(self) -> None:
        """The selected mod's parts in this tab as one row again, where its
        first part is, components in the order shown; the other mods stay."""
        widget, row = self._selected()
        if widget is None:
            return
        unit = widget.item(row).data(ROLE)
        rows = self._parts(widget, unit["key"])
        if len(rows) < 2:
            return
        parts = [widget.item(r).data(ROLE) for r in rows]
        for r in reversed(rows):
            widget.takeItem(r)
        whole = dict(parts[0], split=False,
                     components=[c for part in parts for c in part["components"]])
        widget.insertItem(rows[0], self._item(whole))
        self._reordered()

    def _reset(self) -> None:
        try:
            api.reset_install_order(self.project_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot reset the install order", str(exc))
        self._generation += 1
        self._plan()

    def is_complete(self) -> bool:
        return bool(self.result) and self._planning is None

    def order_file(self) -> str | None:
        path = os.path.join(self.project_dir, api.INSTALL_ORDER_FILE)
        return path if os.path.isfile(path) else None
