"""
The main window: BWS-NG's layout - the phases down the left, the current one
on the right, Back and Next below. A phase is entered only when the one
before it is complete; leaving it saves what it decided.
"""
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from iemod_fetch import api

from .pages.game import GamePage
from .pages.pending import PendingPage

# BWS-NG's order (ADR-0031). Pages arrive phase by phase during M3.
PHASES = ["Game and folders", "Mod selection", "Install order", "Download",
          "Extraction"]


class MainWindow(QMainWindow):
    def __init__(self, project_dir: str) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.setWindowTitle(f"iemod-fetch {api.__version__} - {project_dir}")
        self.resize(960, 640)

        self.phases = QListWidget()
        self.phases.setFixedWidth(200)
        for number, name in enumerate(PHASES, start=1):
            self.phases.addItem(QListWidgetItem(f"{number}  {name}"))
        self.phases.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.phases.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.game = GamePage(project_dir)
        self.pages: List[QWidget] = [self.game] + [
            PendingPage(name, self.game) for name in PHASES[1:]]
        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)

        self.back = QPushButton("< Back")
        self.next = QPushButton("Next >")
        self.back.clicked.connect(self.go_back)
        self.next.clicked.connect(self.go_next)
        self.game.completeChanged.connect(lambda _complete: self._refresh())

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        right = QVBoxLayout()
        right.addWidget(self.stack, 1)
        right.addLayout(buttons)
        body = QHBoxLayout()
        body.addWidget(self.phases)
        body.addLayout(right, 1)
        central = QWidget()
        central.setLayout(body)
        self.setCentralWidget(central)
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self._refresh()

    @property
    def current(self) -> int:
        return int(self.stack.currentIndex())

    def go_next(self) -> None:
        if self.current == 0:
            if not self.game.check()["ok"]:      # what is typed now, not before
                self._refresh()
                return
            try:
                path = self.game.save()
            except Exception as exc:     # an unwritable folder, a bad value
                QMessageBox.critical(self, "Cannot save the project", str(exc))
                return
            self.status.setText(f"saved {path}")
        if self.current + 1 < len(self.pages):
            self.stack.setCurrentIndex(self.current + 1)
        self._refresh()

    def go_back(self) -> None:
        if self.current > 0:
            self.stack.setCurrentIndex(self.current - 1)
        self._refresh()

    def _refresh(self) -> None:
        page = self.pages[self.current]
        complete = getattr(page, "is_complete", lambda: True)()
        self.back.setEnabled(self.current > 0)
        self.next.setEnabled(complete and self.current + 1 < len(self.pages))
        for row in range(self.phases.count()):
            item = self.phases.item(row)
            reachable = row <= self.current
            item.setFlags(Qt.ItemFlag.ItemIsEnabled if reachable else Qt.ItemFlag.NoItemFlags)
            font = item.font()
            font.setBold(row == self.current)
            item.setFont(font)
