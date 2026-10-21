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
"""
import html
import os
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QSplitter, QTextBrowser, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from iemod_fetch import api

Loader = Callable[[str, dict], List[dict]]
Key = Tuple[str, int]                     # (tp2, component number)
ROLE = Qt.ItemDataRole.UserRole
ALL = "All categories"
FILTERS = ["All mods", "Chosen only", "Updates available"]
KRION_NOTE = ("Components from krion64's records: the mod is not downloaded yet. "
              "Its own tp2 decides once it is, and the choice is checked again then.")


def load_choices(game: str, project: dict) -> List[dict]:
    """The real loader: refresh the community data (offline keeps the last good
    copy), then every mod for `game` with its components."""
    api.update_data(api.Settings(quiet=True))
    # The CLI's --target, resolved as the CLI resolves it when run in the project.
    folder = os.path.dirname(project["path"])
    target = os.path.join(folder, project.get("target") or "Mods")
    return api.mod_choices(game, target=target,
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
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, load: Loader, game: str, project: dict) -> None:
        super().__init__()
        self.load, self.game, self.project = load, game, project

    def run(self) -> None:
        try:
            self.done.emit(self.load(self.game, self.project))
        except Exception as exc:          # shown on the page, never a crash
            self.failed.emit(str(exc))


class ModsPage(QWidget):
    completeChanged = Signal(bool)
    loaded = Signal()

    def __init__(self, project_dir: str, load: Loader = load_choices) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.load = load
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
        split.addWidget(self.details)
        split.setSizes([160, 560, 260])
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
        self.game = game
        self.status.setText(f"Loading the mods for {game}...")
        project = api.load_project(self.project_dir)
        thread = QThread()                          # no parent: see _RUNNING
        worker = _Worker(self.load, game, project)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._fill)
        worker.failed.connect(self._failed)
        for signal in (worker.done, worker.failed):
            signal.connect(thread.quit)
        thread.finished.connect(self._finished)
        thread.finished.connect(lambda: _RUNNING.discard(thread))
        thread.finished.connect(worker.deleteLater)
        _RUNNING.add(thread)
        self._worker = worker
        self._thread = thread
        thread.start()

    def _finished(self) -> None:
        self._thread = None
        if self.wanted and self.wanted != self.game:
            self.start(self.wanted)     # the game changed while this list loaded
            return
        self.loaded.emit()              # the thread has ended: safe to close the page

    def _failed(self, message: str) -> None:
        self.status.setText(f"The mod list could not be loaded: {message}")

    def _fill(self, mods: list) -> None:
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
        return {(c.tp2, c.component) for install in selection.installs
                if install.game.upper() == self.game.upper() for c in install.components}

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

    def is_complete(self) -> bool:
        return bool(self.chosen())

    def save(self) -> str:
        labels = {key: item.data(0, ROLE)[2]["name"] for key, item in self.items.items()}
        return api.save_selection(self.project_dir, self.game, self.chosen(), labels)

    # ---------------------------------------------------------- filtering
    def apply_filter(self) -> None:
        current = self.categories.currentItem()
        category = current.data(ROLE) if current is not None else None
        words = self.search.text().strip().lower().split()
        mode = self.filter.currentText()
        by_key = {m["key"]: m for m in self.mods}
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            mod = by_key.get(item.data(0, ROLE)[1], {})
            text = " ".join([item.text(0), *(item.child(i).text(0)
                                              for i in range(item.childCount()))]).lower()
            visible = (not category or category in (mod.get("categories") or ["(none)"]))
            visible = visible and all(word in text for word in words)
            if mode == "Chosen only":
                visible = visible and item.checkState(0) != Qt.CheckState.Unchecked
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
