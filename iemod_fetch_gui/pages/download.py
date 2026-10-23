"""
Phase 4 - download and extraction (GUI-AUDIT item 18, ADR-0039).

The project's selection fetched by the run the command line makes in the
project (api.download_selection): each mod downloaded, its checksum checked,
its archive unpacked and checked for the tp2 it must contain, then staged in
the target. The two are one step per mod in the engine, so they are one page:
a row per mod says which it is at.

Nothing starts until the player asks: it is the network and the disk. Cancel
stops the downloads at their next chunk; what finished stays. Running again
resumes - a mod already there and verified is skipped - and "Retry the failed"
runs only those. A mod from somewhere else than GitHub whose GitHub release is
newer gets a box in "Newer release" (GUI-AUDIT item 59): nothing is replaced
until the player ticks it and asks, as --take-newer does on the command line. The run's events come from its worker threads; they reach the
page through a queued signal, and a mod's byte count at most ten times a
second, so the window stays responsive however fast the network is.
"""
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from iemod_fetch import api

from .mods import _in_thread

# (folder, on_event, cancel, only) - and take_newer=[...] when the player asks
Downloader = Callable[..., dict]
PROGRESS_EVERY_S = 0.1
DETAIL, NEWER = 3, 4                            # the table's columns
DONE = ("ok", "skipped")
STATES = {"ok": "Done", "skipped": "Already there", "failed": "Failed",
          "manual": "No download found", "conflict": "Not installed (conflict)",
          "cancelled": "Cancelled", "planned": "Planned"}


def download_project(folder: str, on_event: Callable[[dict], None],
                     cancel: threading.Event, only: list[str],
                     take_newer: list[str] | None = None) -> dict:
    """The real downloader: the run the command line makes in the project."""
    return api.download_selection(folder, on_event=on_event, cancel=cancel, only=only,
                                  take_newer=take_newer or ())


def _size(count: int) -> str:
    value = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return ""                                   # not reached


class _Bridge(QObject):
    """Carries an event from a worker thread to the page's own thread."""
    event = Signal(object)


class DownloadPage(QWidget):
    completeChanged = Signal(bool)
    finished = Signal()                         # a run has ended

    def __init__(self, project_dir: str, download: Downloader = download_project) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.download = download
        self.result: dict = {}
        self.rows: dict[str, QTreeWidgetItem] = {}
        self._thread: QThread | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        self._only: list[str] = []
        self._selection: object = None
        self._bridge = _Bridge()
        self._bridge.event.connect(self._on_event)

        self.summary = QLabel("Nothing downloaded yet.")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.start_button = QPushButton("Download")
        self.cancel_button = QPushButton("Cancel")
        self.retry_button = QPushButton("Retry the failed")
        self.newer_button = QPushButton("Install the ticked newer releases")
        self.start_button.clicked.connect(self._start_all)
        self.cancel_button.clicked.connect(self.stop)
        self.retry_button.clicked.connect(self.retry)
        self.newer_button.clicked.connect(self.take_newer)
        self.cancel_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.newer_button.setEnabled(False)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(["Mod", "State", "Downloaded", "Detail",
                                    "Newer release"])
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(DETAIL, 320)
        self.table.itemChanged.connect(lambda *_: self._buttons())

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.retry_button)
        buttons.addWidget(self.newer_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>4. Download and extraction</h2>"))
        intro = QLabel(
            "Each mod of the selection is downloaded, its archive unpacked and "
            "checked for the mod it must contain, then put in the project's mod "
            "folder. A mod already there and verified is not downloaded again, so "
            "you can stop and carry on later - here or with the command line.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addLayout(buttons)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------ running
    def prepare(self, selection: object) -> None:
        """
        Entered with `selection` (anything comparable): what an earlier run
        showed of another selection no longer holds - a new mod was never
        downloaded, a dropped one is no longer the player's to retry.
        """
        if selection == self._selection or self.running():
            return
        self._selection = selection
        self.rows.clear()
        self.table.clear()
        self.result = {}
        self.summary.setText("Nothing downloaded yet.")
        self._buttons()
        self.completeChanged.emit(False)

    def running(self) -> bool:
        return self._thread is not None

    def start(self, only: list[str] | None = None,
              take_newer: list[str] | None = None) -> None:
        """
        Download the selection (or only the mods `only` names) in a worker
        thread; `take_newer` names mods whose offered GitHub release replaces
        the copy there.
        """
        if self.running():
            return
        self._cancel = threading.Event()
        self._last.clear()
        only = list(only or [])
        self._only = only
        if not only:
            self.rows.clear()
            self.table.clear()
        self.result = {}
        self.summary.setText("Downloading...")
        download, folder, cancel = self.download, self.project_dir, self._cancel
        forward = self._forward

        asked = {"take_newer": list(take_newer)} if take_newer else {}

        def run():
            try:
                return download(folder, forward, cancel, only, **asked), ""
            except Exception as exc:        # shown on the page, never a crash
                return None, str(exc)
        self._thread = _in_thread(run, self._done, self._failed, self._finished)
        self._buttons()
        self.completeChanged.emit(False)    # running now: the window locks Back

    def _start_all(self) -> None:
        self.start()                    # clicked() passes a bool: not an `only`

    def retry(self) -> None:
        failed = [folder for folder, item in self.rows.items()
                  if item.data(0, Qt.ItemDataRole.UserRole) not in DONE]
        if failed:
            self.start(failed)

    def ticked(self) -> list[str]:
        """The mods whose newer GitHub release the player ticked."""
        return [folder for folder, item in self.rows.items()
                if item.data(NEWER, Qt.ItemDataRole.CheckStateRole) is not None
                and item.checkState(NEWER) == Qt.CheckState.Checked]

    def take_newer(self) -> None:
        """Install the ticked mods' newer releases, over their copies (kept aside)."""
        ticked = self.ticked()
        if ticked:
            self.start(ticked, take_newer=ticked)

    def stop(self) -> None:
        """Cancel the run: the downloads stop at their next chunk."""
        self._cancel.set()
        if self.running():
            self.summary.setText("Stopping...")

    def _forward(self, event: dict) -> None:
        """Called from the run's threads: pass the event on, progress at most 10/s a mod."""
        if event.get("event") == "download_progress":
            now = time.monotonic()
            folder = event.get("folder", "")
            with self._lock:
                last = self._last.get(folder, 0.0)
                if now - last < PROGRESS_EVERY_S and event.get("bytes") != event.get("total"):
                    return
                self._last[folder] = now
        self._bridge.event.emit(dict(event))

    # ------------------------------------------------------------ results
    def _row(self, folder: str) -> QTreeWidgetItem:
        item = self.rows.get(folder)
        if item is None:
            item = QTreeWidgetItem([folder, "Waiting", "", "", ""])
            self.rows[folder] = item
            self.table.addTopLevelItem(item)
        return item

    def _on_event(self, event: dict) -> None:
        kind, folder = event.get("event"), event.get("folder")
        if kind == "run_started":
            self.summary.setText(f"Downloading {event.get('mods', 0)} mod(s)...")
        if not folder:
            return
        item = self._row(folder)
        if kind == "mod_started":
            item.setText(1, "Downloading")
            item.setData(0, Qt.ItemDataRole.UserRole, None)
        elif kind == "download_progress":
            total = event.get("total")
            done = _size(int(event.get("bytes") or 0))
            item.setText(2, f"{done} of {_size(int(total))}" if total else done)
        elif kind == "mod_extracting":
            item.setText(1, "Extracting")
        elif kind == "mod_finished":
            self._finish_row(item, event.get("status", ""), event.get("detail", ""))

    def _finish_row(self, item: QTreeWidgetItem, status: str, detail: str) -> None:
        item.setData(0, Qt.ItemDataRole.UserRole, status)
        item.setText(1, STATES.get(status, status))
        item.setText(DETAIL, detail)
        item.setToolTip(DETAIL, detail)

    def _offer(self, item: QTreeWidgetItem, newer: dict | None) -> None:
        """A box to tick for a newer GitHub release, or none."""
        self.table.blockSignals(True)
        if newer:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(NEWER, Qt.CheckState.Unchecked)
            item.setText(NEWER, f"{newer.get('version')} ({newer.get('repo')})")
            item.setToolTip(NEWER, f"GitHub has {newer.get('version')} "
                                   f"({newer.get('date') or 'no date'}); this copy "
                                   f"declares {newer.get('installed')}. Tick it and "
                                   f"install to replace the copy, which is kept aside.")
        else:
            item.setData(NEWER, Qt.ItemDataRole.CheckStateRole, None)
            item.setText(NEWER, "")
            item.setToolTip(NEWER, "")
        self.table.blockSignals(False)

    def _done(self, outcome: tuple) -> None:
        result, problem = outcome
        if result is None:
            self.summary.setText(f"The download could not start: {problem}")
            return
        reported = {record["folder"] for record in result["records"]}
        for folder in self._only:
            if folder not in reported and folder in self.rows:
                # retried but not in the selection's plan any more: not the player's
                self.table.takeTopLevelItem(self.table.indexOfTopLevelItem(self.rows[folder]))
                del self.rows[folder]
        for record in result["records"]:            # the report is the authority
            item = self._row(record["folder"])
            self._finish_row(item, record["status"], record["detail"])
            self._offer(item, record.get("newer"))
            if record.get("bytes"):
                item.setText(2, _size(int(record["bytes"])))
        self.result = result
        counts = {status: n for status, n in result["counts"].items() if n}
        parts = [f"{n} {STATES.get(status, status).lower()}"
                 for status, n in sorted(counts.items())]
        text = ", ".join(parts) if parts else "nothing to download"
        if result.get("cancelled"):
            text = "Cancelled: " + text
        offers = sum(1 for record in result["records"] if record.get("newer"))
        if offers:
            text += (f". {offers} mod(s) came from elsewhere and GitHub has a newer "
                     f"release: tick it under \"Newer release\" to install it")
        self.summary.setText(text + ".")

    def _failed(self, message: str) -> None:
        self.summary.setText(f"The download could not start: {message}")

    def _finished(self) -> None:
        self._thread = None
        self._buttons()
        self.completeChanged.emit(self.is_complete())
        self.finished.emit()

    def _buttons(self) -> None:
        busy = self.running()
        self.start_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.retry_button.setEnabled(not busy and any(
            item.data(0, Qt.ItemDataRole.UserRole) not in DONE for item in self.rows.values()))
        self.newer_button.setEnabled(not busy and bool(self.ticked()))

    def is_complete(self) -> bool:
        """Every mod of the selection is there: downloaded now or before."""
        return (not self.running() and bool(self.rows) and all(
            item.data(0, Qt.ItemDataRole.UserRole) in DONE for item in self.rows.values()))
