"""The application: arguments, the QApplication and the main window."""
import argparse
import os
import sys
from typing import List, Optional

from iemod_fetch import api


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="iemod-fetch-gui",
        description="The iemod-fetch wizard. Its project folder holds the "
                    f"{api.PROJECT_FILE} the command line reads too.")
    parser.add_argument("--project", default=os.getcwd(),
                        help="project folder (default: the current folder)")
    parser.add_argument("--version", action="version",
                        version=f"iemod-fetch-gui {api.__version__}")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    from PySide6.QtWidgets import QApplication

    from .window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(os.path.abspath(args.project))
    window.show()
    return int(app.exec())
