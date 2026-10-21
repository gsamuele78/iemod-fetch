"""A phase not built yet: says so, and how to go on from the command line."""
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from iemod_fetch import api


class PendingPage(QWidget):
    def __init__(self, name: str, game_page) -> None:
        super().__init__()
        self.game_page = game_page
        self.text = QLabel()
        self.text.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<h2>{name}</h2>"))
        layout.addWidget(self.text)
        layout.addStretch(1)
        self.text.setText(
            f"This phase arrives in a later update of the wizard (milestone M3). "
            f"The project is saved in {api.PROJECT_FILE} in the project folder: "
            f"iemod-fetch run there uses the same game folders and languages, so "
            f"the command line can carry on from here.")
