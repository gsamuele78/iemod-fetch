"""
Phase 3 - install order (GUI-AUDIT item 17, ADR-0038).

The chosen components as the run will install them: planned by the same
planner as --plan-order (krion64's categories, then every order rule, the
authors' own inis included), one tab per install - for EET, BG:EE before the
conversion and EET itself. A mod a rule places is marked; one an order rule
still finds wrong is marked in red, with the rule.

Dragging a mod writes the whole order shown as `install-order.txt` in the
project - a Project Infinity Sorting Order file, which the command line reads
with --sorting-order (the project's ini names it) - and plans again: the
player's order goes on top of the rules, and where it contradicts one the
contradiction is shown, never silently won either way. "Use the computed
order" deletes the file.
"""
import os
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from iemod_fetch import api

from .mods import Key, _in_thread, _target

Planner = Callable[[str, List[Key], dict, str], dict]
ROLE = Qt.ItemDataRole.UserRole
RED = QColor(176, 0, 32)


def plan_selection(game: str, chosen: List[Key], labels: dict, project_dir: str) -> dict:
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
        self.wanted: Optional[Tuple[str, List[Key], dict]] = None
        self._planning: Optional[QThread] = None
        self._again = False
        self._generation = 0

        self.tabs = QTabWidget()
        self.summary = _plain("The order is planned once the mods are chosen.")
        self.problems = _plain("")
        self.problems.setStyleSheet("color: #b00020")
        self.reset = QPushButton("Use the computed order")
        self.reset.setToolTip(f"Forget the order set by hand ({api.INSTALL_ORDER_FILE})")
        self.reset.clicked.connect(self._reset)
        bar = QHBoxLayout()
        bar.addWidget(self.summary, 1)
        bar.addWidget(self.reset)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>3. Install order</h2>"))
        layout.addWidget(_plain(
            "Drag a mod to change where it is installed. Bold: a rule places it. "
            "Red: a rule says it is in the wrong place. Your order is kept in "
            f"{api.INSTALL_ORDER_FILE}, which the command line uses too."))
        layout.addLayout(bar)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.problems)

    # ----------------------------------------------------------- planning
    def start(self, game: str, chosen: List[Key], labels: dict) -> None:
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
        if self._again:
            self._plan()
            return
        self.completeChanged.emit(self.is_complete())   # the window refreshes Next
        self.planned.emit()

    def show_result(self, result: dict) -> None:
        self.result = result
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
        parts = [f"{len(units)} mod(s) in order",
                 f"{sum(u['constrained'] for u in units)} placed by a rule",
                 f"{sum(u['moved'] for u in units)} moved from where they were chosen"]
        if result.get("custom"):
            parts.append("your own order applies")
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
            text = unit["name"] + (f"  -  {unit['category']}" if unit["category"] else "")
            item = QListWidgetItem(text)
            item.setData(ROLE, unit)
            components = ", ".join(f"#{c[1]}" for c in unit["components"][:12])
            tips = [f"Components: {components}"]
            if unit["constrained"]:
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
                tips.append("A rule places it relative to another mod.")
            if unit["moved"]:
                tips.append("Moved from where it was chosen, by the rules.")
            if unit["flagged"]:
                item.setForeground(QBrush(RED))
                tips.append("An order rule says it is in the wrong place (see below).")
            item.setToolTip("\n".join(tips))
            widget.addItem(item)
        widget.model().rowsMoved.connect(lambda *_args: self._reordered())
        return widget

    # ---------------------------------------------------------- reordering
    def phases(self) -> List[List[dict]]:
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

    def _reset(self) -> None:
        try:
            api.reset_install_order(self.project_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot reset the install order", str(exc))
        self._generation += 1
        self._plan()

    def is_complete(self) -> bool:
        return bool(self.result) and self._planning is None

    def order_file(self) -> Optional[str]:
        path = os.path.join(self.project_dir, api.INSTALL_ORDER_FILE)
        return path if os.path.isfile(path) else None
