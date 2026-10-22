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
runs only those. The run's events come from its worker threads; they reach the
page through a queued signal, and a mod's byte count at most ten times a
second, so the window stays responsive however fast the network is.
"""
import threading
import time
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from iemod_fetch import api

from .mods import _in_thread

Downloader = Callable[[str, Callable[[dict], None], threading.Event, List[str]], dict]
PROGRESS_EVERY_S = 0.1
DONE = ("ok", "skipped")
STATES = {"ok": "Done", "skipped": "Already there", "failed": "Failed",
          "manual": "No download found", "conflict": "Not installed (conflict)",
          "cancelled": "Cancelled", "planned": "Planned"}


def download_project(folder: str, on_event: Callable[[dict], None],
                     cancel: threading.Event, only: List[str]) -> dict:
    """The real downloader: the run the command line makes in the project."""
    return api.download_selection(folder, on_event=on_event, cancel=cancel, only=only)


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
        self.rows: Dict[str, QTreeWidgetItem] = {}
        self._thread: Optional[QThread] = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._last: Dict[str, float] = {}
        self._bridge = _Bridge()
        self._bridge.event.connect(self._on_event)

        self.summary = QLabel("Nothing downloaded yet.")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.start_button = QPushButton("Download")
        self.cancel_button = QPushButton("Cancel")
        self.retry_button = QPushButton("Retry the failed")
        self.start_button.clicked.connect(self._start_all)
        self.cancel_button.clicked.connect(self.stop)
        self.retry_button.clicked.connect(self.retry)
        self.cancel_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(["Mod", "State", "Downloaded", "Detail"])
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 140)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.retry_button)
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
    def running(self) -> bool:
        return self._thread is not None

    def start(self, only: Optional[List[str]] = None) -> None:
        """Download the selection (or only the mods `only` names) in a worker thread."""
        if self.running():
            return
        self._cancel = threading.Event()
        self._last.clear()
        only = list(only or [])
        if not only:
            self.rows.clear()
            self.table.clear()
        self.result = {}
        self.summary.setText("Downloading...")
        self._buttons()
        self.completeChanged.emit(False)
        download, folder, cancel = self.download, self.project_dir, self._cancel
        forward = self._forward

        def run():
            try:
                return download(folder, forward, cancel, only), ""
            except Exception as exc:        # shown on the page, never a crash
                return None, str(exc)
        self._thread = _in_thread(run, self._done, self._failed, self._finished)
        self._buttons()

    def _start_all(self) -> None:
        self.start()                    # clicked() passes a bool: not an `only`

    def retry(self) -> None:
        failed = [folder for folder, item in self.rows.items()
                  if item.data(0, Qt.ItemDataRole.UserRole) not in DONE]
        if failed:
            self.start(failed)

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
            item = QTreeWidgetItem([folder, "Waiting", "", ""])
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
        item.setText(3, detail)
        item.setToolTip(3, detail)

    def _done(self, outcome: tuple) -> None:
        result, problem = outcome
        if result is None:
            self.summary.setText(f"The download could not start: {problem}")
            return
        for record in result["records"]:            # the report is the authority
            item = self._row(record["folder"])
            self._finish_row(item, record["status"], record["detail"])
            if record.get("bytes"):
                item.setText(2, _size(int(record["bytes"])))
        self.result = result
        counts = {status: n for status, n in result["counts"].items() if n}
        parts = [f"{n} {STATES.get(status, status).lower()}"
                 for status, n in sorted(counts.items())]
        text = ", ".join(parts) if parts else "nothing to download"
        if result.get("cancelled"):
            text = "Cancelled: " + text
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

    def is_complete(self) -> bool:
        """Every mod of the selection is there: downloaded now or before."""
        return (not self.running() and bool(self.rows) and all(
            item.data(0, Qt.ItemDataRole.UserRole) in DONE for item in self.rows.values()))
