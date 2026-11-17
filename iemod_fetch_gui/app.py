"""The application: arguments, the QApplication and the main window."""
import argparse
import os
import sys

from iemod_fetch import api


def default_project() -> str:
    """The current folder; in a Flatpak, a folder in the app's own data
    (~/.var/app/<id>/data/project), which the sandbox keeps: its home and
    the folder it was started from are not kept, and the mods downloaded
    into a project would vanish with the sandbox (review of #135)."""
    if api.sandbox():
        data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
            os.path.join("~", ".var", "app", os.environ.get("FLATPAK_ID", ""), "data")
            if os.environ.get("FLATPAK_ID") else "~/.local/share")
        folder = os.path.join(data, "project")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as error:
            raise SystemExit(f"iemod-fetch-gui: no project folder {folder}: {error}; "
                             f"give one with --project") from error
        return folder
    return os.getcwd()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="iemod-fetch-gui",
        description="The iemod-fetch wizard. Its project folder holds the "
                    f"{api.PROJECT_FILE} the command line reads too.")
    parser.add_argument("--project", default=None,
                        help="project folder (default: the current folder; in a "
                             "Flatpak, ~/.var/app/<id>/data/project)")
    parser.add_argument("--version", action="version",
                        version=f"iemod-fetch-gui {api.__version__}")
    parser.add_argument("--check", action="store_true",
                        help="open the window and close it at once: proves a build "
                             "starts, Qt included (exit 0, prints 'ok')")
    args = parser.parse_args(argv)
    if args.project is None:
        args.project = default_project()
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    from PySide6.QtWidgets import QApplication

    from .pages.mods import wait_for_loaders
    from .window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(os.path.abspath(args.project))
    # A download still running is cancelled first, so the wait below is short.
    app.aboutToQuit.connect(window.download.stop)
    app.aboutToQuit.connect(wait_for_loaders)
    window.show()
    if args.check:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, app.quit)
        code = int(app.exec())
        sys.stdout.write("ok\n" if code == 0 else f"exit {code}\n")
        return code
    return int(app.exec())
