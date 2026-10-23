"""
The main window: BWS-NG's layout - the phases down the left, the current one
on the right, Back and Next below. A phase is entered only when the one
before it is complete; leaving it saves what it decided.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from iemod_fetch import api

from .pages.download import DownloadPage, Downloader, download_project
from .pages.game import GamePage
from .pages.mods import Checker, Loader, ModsPage, find_conflicts, load_choices
from .pages.order import OrderPage, Planner, plan_selection
from .pages.pending import PendingPage

# BWS-NG's order (ADR-0031). Its download and extraction are one step per mod
# in the engine, so one page here (ADR-0039); installing comes with M4.
PHASES = ["Game and folders", "Mod selection", "Install order",
          "Download and extraction", "Installation"]


class MainWindow(QMainWindow):
    def __init__(self, project_dir: str, load: Loader = load_choices,
                 check: Checker = find_conflicts, plan: Planner = plan_selection,
                 download: Downloader = download_project) -> None:
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
        self.mods = ModsPage(project_dir, load, check)
        self.order = OrderPage(project_dir, plan)
        self.download = DownloadPage(project_dir, download)
        self.pages: list[QWidget] = [self.game, self.mods, self.order, self.download,
                                     PendingPage(PHASES[4], self.game, "M4")]
        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)

        self.back = QPushButton("< Back")
        self.next = QPushButton("Next >")
        self.back.clicked.connect(self.go_back)
        self.next.clicked.connect(self.go_next)
        self.game.completeChanged.connect(lambda _complete: self._refresh())
        self.mods.completeChanged.connect(lambda _complete: self._refresh())
        self.order.completeChanged.connect(lambda _complete: self._refresh())
        self.download.completeChanged.connect(lambda _complete: self._refresh())

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
            self.mods.start(self.game.game() or "EET")
        elif self.current == 1:
            try:
                path = self.mods.save()
            except Exception as exc:     # refused by selection.json's own checks
                QMessageBox.critical(self, "Cannot save the selection", str(exc))
                return
            self.status.setText(f"saved {path}")
            self.order.start(self.mods.game, self.mods.chosen(), self.mods.labels())
        elif self.current == 2:
            self.download.prepare((self.mods.game, tuple(self.mods.chosen())))
        if self.current + 1 < len(self.pages):
            self.stack.setCurrentIndex(self.current + 1)
        self._refresh()

    def go_back(self) -> None:
        if self.current > 0 and not self.download.running():
            self.stack.setCurrentIndex(self.current - 1)
        self._refresh()

    def _refresh(self) -> None:
        page = self.pages[self.current]
        complete = getattr(page, "is_complete", lambda: True)()
        # the selection must not change under a running download
        self.back.setEnabled(self.current > 0 and not self.download.running())
        self.next.setEnabled(complete and self.current + 1 < len(self.pages))
        for row in range(self.phases.count()):
            item = self.phases.item(row)
            reachable = row <= self.current
            item.setFlags(Qt.ItemFlag.ItemIsEnabled if reachable else Qt.ItemFlag.NoItemFlags)
            font = item.font()
            font.setBold(row == self.current)
            item.setFont(font)
