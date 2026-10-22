"""
Phase 2 - mod selection (GUI-AUDIT item 16, ADR-0031/0035).

BWS-NG's screen as an idea: categories down the left, a search box and a
filter above a mod -> component tree, details on the right. A mod's box is
tri-state; components that share a SUBCOMPONENT exclude each other (choosing
one clears the others), and choosing a component also chooses the same-mod
components it needs. The catalogue loads in a worker thread, so the window
never waits on the network or the disk. Leaving the phase writes the
project's selection.json, which the CLI reads with --selection.

A mod whose components are not known yet - not staged, and krion64 has no
record of it - cannot be chosen here: a selection names components, and
guessing them is what this tool does not do. It says so in its row.

The conflicts tab checks the selection against the rules a run uses, shortly
after each change and in a worker thread too (api.selection_conflicts, ADR-0033);
its buttons change the tree or write decisions.json. "Conflicts only" shows the
mods in a conflict still to decide.
"""
import html
import os
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QSplitter, QTabWidget,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from iemod_fetch import api

from .conflicts import ConflictsPanel, open_findings

Loader = Callable[[str, dict], List[dict]]
Key = Tuple[str, int]                     # (tp2, component number)
Checker = Callable[[str, List[Key], dict, str], dict]
ROLE = Qt.ItemDataRole.UserRole
ALL = "All categories"
FILTERS = ["All mods", "Chosen only", "Conflicts only", "Updates available"]
CHECK_DELAY_MS = 700      # a burst of clicks is checked once, after it ends
KRION_NOTE = ("Components from krion64's records: the mod is not downloaded yet. "
              "Its own tp2 decides once it is, and the choice is checked again then.")


def _target(project: dict) -> str:
    """The CLI's --target, resolved as the CLI resolves it when run in the project."""
    folder = os.path.dirname(project["path"])
    return os.path.join(folder, project.get("target") or "Mods")


def find_conflicts(game: str, chosen: List[Key], labels: dict, project_dir: str) -> dict:
    """The real checker: the selection's conflicts and the project's decisions."""
    project = api.load_project(project_dir)
    # The authors' own install order is fetched for what is chosen (ADR-0037):
    # one small file per mod, once a week at most, kept in the data cache.
    # The order set by hand in phase 3 is part of what the run judges too.
    order = os.path.join(project_dir, api.INSTALL_ORDER_FILE)
    return api.selection_conflicts(game, chosen, labels, folder=project_dir,
                                   target=_target(project), fetch_metadata=True,
                                   sorting_order=order if os.path.isfile(order) else None)


def load_choices(game: str, project: dict) -> List[dict]:
    """The real loader: refresh the community data (offline keeps the last good
    copy), then every mod for `game` with its components."""
    api.update_data(api.Settings(quiet=True))
    return api.mod_choices(game, target=_target(project),
                           preferences=project.get("language_preference") or ())


# Threads outlive the page that started them: closing the window while the
# catalogue loads must not destroy a running QThread (Qt aborts). Each is kept
# here until it has finished; the application waits for them on quit.
_RUNNING: Set[QThread] = set()


def wait_for_loaders(timeout_ms: int = 60000) -> None:
    """Let every catalogue load still running end (QApplication.aboutToQuit)."""
    for thread in list(_RUNNING):
        thread.wait(timeout_ms)


class _Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, call: Callable[[], Any]) -> None:
        super().__init__()
        self.call = call

    def run(self) -> None:
        try:
            self.done.emit(self.call())
        except Exception as exc:          # shown on the page, never a crash
            self.failed.emit(str(exc))


def _in_thread(call: Callable[[], Any], done: Callable, failed: Callable,
               finished: Callable) -> QThread:
    """Run `call` in a worker thread kept in _RUNNING until it ends."""
    thread = QThread()                          # no parent: see _RUNNING
    worker = _Worker(call)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(done)
    worker.failed.connect(failed)
    for signal in (worker.done, worker.failed):
        signal.connect(thread.quit)
    thread.finished.connect(finished)
    def ended(held: _Worker = worker) -> None:     # holds the worker until the end
        _RUNNING.discard(thread)
        held.deleteLater()

    thread.finished.connect(ended)
    _RUNNING.add(thread)
    thread.start()
    return thread


class ModsPage(QWidget):
    completeChanged = Signal(bool)
    loaded = Signal()
    checked = Signal()

    def __init__(self, project_dir: str, load: Loader = load_choices,
                 check: Checker = find_conflicts) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.load = load
        self.check = check
        self.conflicts: dict = {}
        self._checking: Optional[QThread] = None
        self._recheck = False
        self._generation = 0      # a check's result is shown only for the list it checked
        self._loading = False     # a list is on its way: the one shown is not checked
        self.game = ""              # the game the shown list is for
        self.wanted = ""            # the game asked for last
        self.mods: List[dict] = []
        self.items: Dict[Key, QTreeWidgetItem] = {}
        self.exclusive: Dict[Tuple[str, str], List[QTreeWidgetItem]] = {}
        self._thread: Optional[QThread] = None
        self._updating = False

        self.categories = QListWidget()
        self.categories.currentTextChanged.connect(lambda _text: self.apply_filter())
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods and components")
        self.search.textChanged.connect(lambda _text: self.apply_filter())
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.filter.currentIndexChanged.connect(lambda _index: self.apply_filter())

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Mod / component", "Version", "Components from"])
        self.tree.setColumnWidth(0, 420)
        self.tree.itemChanged.connect(self._changed)
        self.tree.currentItemChanged.connect(lambda item, _old: self._show(item))
        self.details = QTextBrowser()
        self.details.setOpenLinks(False)          # catalogue text is third-party
        self.panel = ConflictsPanel()
        self.panel.can_choose = self._can_choose
        self.panel.deselect.connect(self._deselect)
        self.panel.choose.connect(self._choose_in)
        self.panel.decide.connect(self._decide)
        self.panel.undo.connect(self._undo)
        self.panel.check.connect(self.check_conflicts)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.details, "Details")
        self.tabs.addTab(self.panel, "Conflicts")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(CHECK_DELAY_MS)
        self.timer.timeout.connect(self.check_conflicts)
        self.status = QLabel("Loading the mod list...")
        self.status.setTextFormat(Qt.TextFormat.PlainText)

        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.filter)
        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.addLayout(bar)
        middle_layout.addWidget(self.tree, 1)
        split = QSplitter()
        split.addWidget(self.categories)
        split.addWidget(middle)
        split.addWidget(self.tabs)
        split.setSizes([160, 520, 320])
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>2. Mod selection</h2>"))
        layout.addWidget(split, 1)
        layout.addWidget(self.status)

    # ------------------------------------------------------------ loading
    def start(self, game: str) -> None:
        """Load the catalogue for `game` in a worker thread."""
        self.wanted = game
        if self._thread is not None:          # loading: _finished loads again if needed
            return
        if game == self.game and self.mods:
            return
        # What was checked was the old list: no result for it may land on the new one.
        self.timer.stop()
        self._generation += 1
        self._loading = True
        self._set_conflicts({})
        self.game = game
        self.status.setText(f"Loading the mods for {game}...")
        project = api.load_project(self.project_dir)
        load = self.load
        self._thread = _in_thread(lambda: load(game, project), self._fill, self._failed,
                                  self._finished)

    def _finished(self) -> None:
        self._thread = None
        if self.wanted and self.wanted != self.game:
            self.start(self.wanted)     # the game changed while this list loaded
            return
        self.loaded.emit()              # the thread has ended: safe to close the page

    def _failed(self, message: str) -> None:
        self._loading = False
        self.status.setText(f"The mod list could not be loaded: {message}")

    def _fill(self, mods: list) -> None:
        self._loading = False
        self._generation += 1           # nothing checked before this list applies to it
        self._updating = True
        self.mods = mods
        self.tree.clear()
        self.items.clear()
        self.exclusive.clear()
        saved = self._saved_selection()
        counts: Dict[str, int] = {}
        for mod in mods:
            for category in mod.get("categories") or ["(none)"]:
                counts[category] = counts.get(category, 0) + 1
            self.tree.addTopLevelItem(self._mod_item(mod, saved))
        self.categories.clear()
        self.categories.addItem(QListWidgetItem(f"{ALL} ({len(mods)})"))
        for category in sorted(counts):
            item = QListWidgetItem(f"{category} ({counts[category]})")
            item.setData(ROLE, category)
            self.categories.addItem(item)
        self.categories.setCurrentRow(0)
        self._updating = False
        self.apply_filter()
        self._count()
        self.check_conflicts()

    def _mod_item(self, mod: dict, saved: Set[Key]) -> QTreeWidgetItem:
        latest = mod.get("latest") or {}
        version = mod.get("version") or ""
        if mod.get("update_available"):
            version = f"{mod.get('installed') or version} -> {latest.get('version', '?')}"
        tp2s = mod.get("tp2s") or []
        origin = ", ".join(sorted({t["origin"] for t in tp2s})) or "not known yet"
        item = QTreeWidgetItem([mod.get("name") or mod["key"], version, origin])
        item.setData(0, ROLE, ("mod", mod["key"]))
        if not any(t["components"] and not t.get("refused") for t in tp2s):
            item.setDisabled(True)
            item.setToolTip(0, "Its components are not known until it is downloaded: "
                               "nothing to choose yet.")
            return item
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                      | Qt.ItemFlag.ItemIsAutoTristate)
        for tp2 in tp2s:
            parent = item
            if len(tp2s) > 1:                       # EET: EET.tp2 and EET_end.tp2
                parent = QTreeWidgetItem([tp2["tp2"].rsplit("/", 1)[-1], "", tp2["origin"]])
                parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable
                                | Qt.ItemFlag.ItemIsAutoTristate)
                item.addChild(parent)
            for component in tp2["components"]:
                key = (tp2["tp2"], component["number"])
                if key in self.items:               # listed twice: one box, not two
                    continue
                name = component["name"]
                if component["subgroup"]:
                    name = f"{component['subgroup']} -> {name}"
                child = QTreeWidgetItem([f"#{component['number']}  {name}", "", ""])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setData(0, ROLE, ("component", key, component))
                if tp2.get("refused"):
                    child.setDisabled(True)
                    child.setToolTip(0, tp2["refused"])
                    parent.addChild(child)
                    continue
                child.setCheckState(0, Qt.CheckState.Checked if key in saved
                                    else Qt.CheckState.Unchecked)
                parent.addChild(child)
                self.items[key] = child
                if component["exclusive"]:
                    self.exclusive.setdefault((tp2["tp2"], component["exclusive"]),
                                              []).append(child)
        return item

    def _saved_selection(self) -> Set[Key]:
        path = os.path.join(self.project_dir, api.SELECTION_FILE)
        if not os.path.isfile(path):
            return set()
        try:
            selection = api.load_selection(path)
        except Exception:        # a hand-edited file the CLI would refuse: start empty
            return set()
        # An EET build is saved as two installs, the BG:EE phase and EET; a
        # BG:EE install alone is a BG:EE build, not EET's first phase.
        saved = {install.game.upper() for install in selection.installs}
        games = ({"EET", "BGEE"} if self.game.upper() == "EET" and "EET" in saved
                 else {self.game.upper()})
        return {(c.tp2, c.component) for install in selection.installs
                if install.game.upper() in games for c in install.components}

    # ---------------------------------------------------------- choosing
    def _changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        data = item.data(0, ROLE)
        if not data or data[0] != "component":
            self._count()
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self._updating = True
            try:
                self._choose(item, set())
            finally:
                self._updating = False
        self._count()

    def _choose(self, item: QTreeWidgetItem, seen: Set[Key]) -> None:
        """Choose `item`: clear the rest of its SUBCOMPONENT, then choose - the
        same way - every component it needs."""
        _kind, (tp2, number), component = item.data(0, ROLE)
        if (tp2, number) in seen:
            return
        seen.add((tp2, number))
        item.setCheckState(0, Qt.CheckState.Checked)
        for other in self.exclusive.get((tp2, component["exclusive"]), []):
            if other is not item:
                other.setCheckState(0, Qt.CheckState.Unchecked)
        for needed in component["requires"]:
            needed_item = self.items.get((tp2, needed))
            if needed_item is not None and not needed_item.isDisabled():
                self._choose(needed_item, seen)

    def chosen(self) -> List[Key]:
        """(tp2, number) of every chosen component, in catalogue order."""
        return [key for key, item in self.items.items()
                if item.checkState(0) == Qt.CheckState.Checked]

    def _count(self) -> None:
        chosen = self.chosen()
        mods = {tp2.split("/")[0].lower() for tp2, _number in chosen}
        self.status.setText(f"{len(chosen)} component(s) chosen in {len(mods)} mod(s), "
                            f"of {len(self.mods)} mods for {self.game}.")
        self.completeChanged.emit(self.is_complete())
        if self.mods:
            self.timer.start()                    # what was checked no longer holds

    def is_complete(self) -> bool:
        return bool(self.chosen())

    def labels(self) -> Dict[Key, str]:
        return {key: item.data(0, ROLE)[2]["name"] for key, item in self.items.items()}

    def save(self) -> str:
        return api.save_selection(self.project_dir, self.game, self.chosen(), self.labels())

    # ---------------------------------------------------------- conflicts
    def check_conflicts(self) -> None:
        """Check the selection now, in a worker thread; a check asked for while
        one runs is made once that one ends."""
        self.timer.stop()
        if self._loading:
            return                      # the list arriving is checked when it is shown
        if self._checking is not None:
            self._recheck = True
            return
        self._recheck = False
        self.panel.busy()
        check, args = self.check, (self.game, self.chosen(), self.labels(),
                                   self.project_dir)
        generation = self._generation

        def run() -> Tuple[int, Optional[dict], str]:
            # The generation travels with the result: the slots below are the
            # page's own methods, so Qt runs them on the window's thread (a
            # lambda slot would run on the worker's).
            try:
                return generation, check(*args), ""
            except Exception as exc:      # shown on the panel, never a crash
                return generation, None, str(exc)
        self._checking = _in_thread(run, self._check_done, self.panel.failed,
                                    self._check_finished)

    def _check_done(self, outcome: tuple) -> None:
        generation, result, problem = outcome
        if generation != self._generation:
            return                      # checked a list this page no longer shows
        if result is None:
            self._set_conflicts({})
            self.panel.failed(problem)
            return
        self._set_conflicts(result)

    def _set_conflicts(self, result: dict) -> None:
        """Show `result` ({} for none): the panel, the tab's count, the filter."""
        self.conflicts = result
        if result:
            self.panel.show_result(result)
        else:
            self.panel.clear()
        waiting = len(open_findings(result))
        self.tabs.setTabText(1, f"Conflicts ({waiting})" if waiting else "Conflicts")
        if self.filter.currentText() == "Conflicts only":
            self.apply_filter()

    def _check_finished(self) -> None:
        self._checking = None
        if self._recheck and not self._loading:
            self.check_conflicts()
            return
        self.checked.emit()

    def _deselect(self, pairs: list) -> None:
        for tp2, number in pairs:
            item = self.items.get((tp2, number))
            if item is not None:
                item.setCheckState(0, Qt.CheckState.Unchecked)

    def _mod_items(self, key: str, numbers: List[int]) -> Dict[int, QTreeWidgetItem]:
        """
        The choosable components `numbers` of the tp2 an option's key names,
        as the plan names it: `eet` is EET.tp2, not EET_end.tp2 in the same
        folder; a mod's own key only when no tp2 has that key.
        """
        tp2s = [t for m in self.mods for t in m.get("tp2s") or [] if t.get("key") == key]
        if not tp2s:
            mod = next((m for m in self.mods if m["key"] == key), None)
            tp2s = (mod or {}).get("tp2s") or []
            if len(tp2s) != 1:
                return {}               # which of its tp2s is meant is not known
        found: Dict[int, QTreeWidgetItem] = {}
        for tp2 in tp2s:
            for number in numbers:
                item = self.items.get((tp2["tp2"], number))
                if item is not None and not item.isDisabled():
                    found.setdefault(number, item)
        return found

    def _can_choose(self, key: str, numbers: List[int]) -> bool:
        return bool(numbers) and set(numbers) <= set(self._mod_items(key, numbers))

    def _choose_in(self, key: str, numbers: list) -> None:
        for item in self._mod_items(key, numbers).values():
            item.setCheckState(0, Qt.CheckState.Checked)

    def _decide(self, finding: str, option: str, why: str) -> None:
        self._write_decisions(lambda choose, accept: (
            choose.__setitem__(finding, option) if option else accept.__setitem__(finding, why)))

    def _undo(self, finding: str) -> None:
        self._write_decisions(lambda choose, accept: (choose.pop(finding, None),
                                                      accept.pop(finding, None)))

    def _write_decisions(self, change: Callable[[dict, dict], Any]) -> None:
        current = api.load_decisions(self.project_dir)
        if current["problem"]:
            # Never overwrite a file that could not be read: it may hold answers.
            QMessageBox.critical(self, "decisions.json cannot be read",
                                 f"{current['problem']}\n\nFix or remove it first.")
            return
        change(current["choose"], current["accept"])
        try:
            api.save_decisions(self.project_dir, current["choose"], current["accept"])
        except Exception as exc:
            QMessageBox.critical(self, "Cannot save the decision", str(exc))
            return
        self.check_conflicts()

    def _in_conflict(self) -> Set[str]:
        """Keys of the mods in a conflict still to decide."""
        tp2s = {tp2 for finding in open_findings(self.conflicts)
                for side in (finding["left"], finding.get("right")) if side
                for tp2, _number in side.get("chosen") or []}
        return {mod["key"] for mod in self.mods
                if any(t["tp2"] in tp2s for t in mod.get("tp2s") or [])}

    # ---------------------------------------------------------- filtering
    def apply_filter(self) -> None:
        current = self.categories.currentItem()
        category = current.data(ROLE) if current is not None else None
        words = self.search.text().strip().lower().split()
        mode = self.filter.currentText()
        by_key = {m["key"]: m for m in self.mods}
        in_conflict = self._in_conflict() if mode == "Conflicts only" else set()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            mod = by_key.get(item.data(0, ROLE)[1], {})
            text = " ".join([item.text(0), *(item.child(i).text(0)
                                              for i in range(item.childCount()))]).lower()
            visible = (not category or category in (mod.get("categories") or ["(none)"]))
            visible = visible and all(word in text for word in words)
            if mode == "Chosen only":
                visible = visible and item.checkState(0) != Qt.CheckState.Unchecked
            elif mode == "Conflicts only":
                visible = visible and mod.get("key") in in_conflict
            elif mode == "Updates available":
                visible = visible and bool(mod.get("update_available"))
            item.setHidden(not visible)

    def _show(self, item: Optional[QTreeWidgetItem]) -> None:
        if item is None:
            return
        while item.parent() is not None:
            item = item.parent()
        mod = next((m for m in self.mods if m["key"] == item.data(0, ROLE)[1]), None)
        if mod is None:
            return
        e = html.escape                       # every value here is catalogue text
        lines = [f"<h3>{e(str(mod.get('name') or mod['key']))}</h3>",
                 f"<b>Games:</b> {e(', '.join(mod.get('games') or []) or 'not stated')}",
                 f"<b>Categories:</b> {e(', '.join(mod.get('categories') or []) or '-')}",
                 f"<b>Status:</b> {e(', '.join(mod.get('status') or []) or '-')}"]
        latest = mod.get("latest") or {}
        if latest:
            lines.append(f"<b>Newest version:</b> {e(str(latest.get('version')))} "
                         f"({e(str(latest.get('origin')))}, "
                         f"{e(str(latest.get('date') or 'no date'))})")
        lines += [f"<b>Warning:</b> {e(str(text))}" for text in mod.get("advisories") or []]
        lines += [f"<b>Cannot be chosen:</b> {e(t['refused'])}"
                  for t in mod.get("tp2s") or [] if t.get("refused")]
        if any(t["origin"] == "krion64" for t in mod.get("tp2s") or []):
            lines.append(f"<i>{KRION_NOTE}</i>")
        self.details.setHtml("<br>".join(lines))
