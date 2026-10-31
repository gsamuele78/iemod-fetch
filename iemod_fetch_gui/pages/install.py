"""
Phase 5 - installation (GUI-AUDIT M4 item 22c, ADR-0045, ADR-0046).

Three steps, each the player's:

1. The programs. mod_installer and WeiDU, found as api.find_tools finds them
   (the player's file, the bundle's, PATH, a WeiDU downloaded here before);
   what is wrong with one is said in its own words. A program can be chosen
   by hand; WeiDU can be downloaded, after a confirmation that names what is
   fetched, from where, and under which licence.
2. A backup of every game folder the install changes (ADR-0042): one made
   here, or one there already. Without it nothing installs.
3. The install. After a last confirmation, the order the order page shows is
   written as the planned logs (api.write_install_plan) and mod_installer
   runs over them (api.start_install): its output is shown as it comes, a
   question no recorded answer covers is asked here, and Cancel stops it and
   everything it started. Nothing is undone by itself: the backup is how to
   start again.

Every slow step runs in a worker thread; what it says reaches the page
through a queued signal.
"""
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from iemod_fetch import api

from .mods import _in_thread

TOOLS = (("mod_installer", "mod_installer"), ("weidu", "WeiDU"))
PROGRESS_EVERY_S = 0.1
MAX_SHOWN = 10                                  # order breaks named in the confirmation


def _plan(game: str, chosen: list, labels: dict, folder: str) -> dict:
    """The real plan writer: the order page's planner, written to the project."""
    return api.write_install_plan(game, chosen, labels, folder=folder, fetch_metadata=True)


def _mods_dir(folder: str) -> str:
    return api.project_settings(folder).target


@dataclass
class Services:
    """What the page calls: the api, or a test's stand-ins."""
    find: Callable[..., dict] = api.find_tools
    pin: Callable[[str], Any] = api.tool_download
    download: Callable[..., Any] = api.download_tool
    backups: Callable[[str], list] = api.list_backups
    backup: Callable[..., str] = api.backup_game
    plan: Callable[..., dict] = _plan
    games: Callable[[str], dict] = api.install_games
    mods_dir: Callable[[str], str] = _mods_dir
    restore_plan: Callable[[str, str], dict] = api.plan_restore
    progress: Callable[[str, dict], dict] = api.install_progress
    known_issues: Callable[[dict, str], list] = api.install_known_issues
    start: Callable[..., Any] = api.start_install
    # the phase-5 questionnaire (ADR-0049)
    questions: Callable[[str, str], dict] = api.install_questions
    load_answers: Callable[[str], dict] = api.load_install_answers
    save_answers: Callable[[str, dict], Any] = api.save_install_answers
    write_answers: Callable[..., dict] = api.write_install_answers
    timing: dict = field(default_factory=dict)    # start_install's quiet_s, grace_s...


def _size(count: int) -> str:
    value = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return ""                                   # not reached


class _Bridge(QObject):
    """Carries a message from a worker thread to the page's own thread."""
    line = Signal(str)
    status = Signal(str)
    question = Signal(object)


class _Question:
    """A question from the install's thread, answered on the page's."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.answer: str | None = None
        self.ready = threading.Event()

    def give(self, answer: str | None) -> None:
        self.answer = answer
        self.ready.set()


class InstallPage(QWidget):
    completeChanged = Signal(bool)
    finished = Signal()                         # a backup, download or install ended

    def __init__(self, project_dir: str, services: Services | None = None) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.services = services or Services()
        self.wanted: tuple[str, list, dict] | None = None
        self.given: dict[str, str | None] = {tool: None for tool, _name in TOOLS}
        self.found: dict[str, Any] = {}
        self.games: dict[str, str] = {}
        self.backed_up: dict[str, str] = {}     # game folder -> its newest backup
        self.progress: dict = {"state": "fresh"}    # how far an earlier install went
        self.outcome: Any = None
        # the components a Cancel stopped inside: said again when resuming, a
        # net under the uninstall-record check (review of #89)
        self.cancelled_in: str | None = None
        self._running_batch: str | None = None
        self._thread: QThread | None = None
        self._cancel = threading.Event()
        self._install: Any = None
        self._asking: _Question | None = None
        self._plan_written: dict | None = None
        self._checking: QThread | None = None
        self._check_round = 0
        self._last = 0.0
        self._bridge = _Bridge()
        self._bridge.line.connect(self._append)
        self._bridge.status.connect(self._say)
        self._bridge.question.connect(self._ask)

        # 1. the programs
        self.tool_state: dict[str, QLabel] = {}
        self.choose: dict[str, QPushButton] = {}
        tools = QGridLayout()
        for row, (tool, name) in enumerate(TOOLS):
            state = _plain("")
            choose = QPushButton("Choose...")
            choose.setAccessibleName(f"Choose {name}")
            choose.clicked.connect(lambda _checked=False, t=tool: self._choose(t))
            self.tool_state[tool], self.choose[tool] = state, choose
            tools.addWidget(QLabel(f"<b>{name}</b>"), row, 0)
            tools.addWidget(state, row, 1)
            tools.addWidget(choose, row, 2)
        self.download_weidu = QPushButton("Download WeiDU...")
        self.download_weidu.clicked.connect(self.offer_weidu)
        tools.addWidget(self.download_weidu, 1, 3)
        tools.setColumnStretch(1, 1)
        programs = QGroupBox("1. The programs")
        programs.setLayout(tools)

        # 2. the backups
        self.backup_rows = QGridLayout()
        self.backup_rows.setColumnStretch(1, 1)
        self.backup_state: dict[str, QLabel] = {}
        self.backup_button: dict[str, QPushButton] = {}
        backups = QGroupBox("2. A backup of each game folder")
        backups.setLayout(self.backup_rows)

        # 3. the install
        self.install_button = QPushButton("Install")
        self.cancel_button = QPushButton("Cancel")
        self.install_button.clicked.connect(self.install)
        self.cancel_button.clicked.connect(self.stop)
        self.summary = _plain("")
        self.needs = _plain("")
        self.resume_state = _plain("")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.output.setAccessibleName("mod_installer's output")
        self.output.setMaximumBlockCount(20000)
        buttons = QHBoxLayout()
        buttons.addWidget(self.install_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        run = QVBoxLayout()
        run.addLayout(buttons)
        run.addWidget(self.resume_state)
        run.addWidget(self.needs)
        run.addWidget(self.summary)
        run.addWidget(self.output, 1)
        installing = QGroupBox("3. The install")
        installing.setLayout(run)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>5. Installation</h2>"))
        layout.addWidget(_plain(
            "mod_installer installs the order planned on the order page, with WeiDU, "
            "into the game folders. It changes them: a backup of each comes first, "
            "and is how to start again if anything goes wrong."))
        layout.addWidget(programs)
        layout.addWidget(backups)
        layout.addWidget(installing, 1)
        self._buttons()

    # ------------------------------------------------------------ entering
    def prepare(self, game: str, chosen: list, labels: dict) -> None:
        """Entered with the selection to install: what it needs, looked at again."""
        if self.running():
            return
        self.wanted = (game, list(chosen), dict(labels))
        self.refresh()

    def refresh(self) -> None:
        self._refresh_tools()
        self._refresh_backups()
        self._refresh_progress()
        self._buttons()

    def plan_dir(self) -> str:
        return os.path.join(self.project_dir, api.INSTALL_PLAN_DIR)

    def _refresh_progress(self) -> None:
        """How far the last install went (item 23): the games' WeiDU.logs
        against the plan last written here."""
        try:
            self.progress = (self.services.progress(self.plan_dir(), self.games)
                             if self.games else {"state": "fresh"})
        except Exception as exc:          # an unreadable log: said, not a crash
            self.progress = {"state": "mismatch", "problem": str(exc)}
        self.resume_state.setText(_progress_text(self.progress))

    def _refresh_tools(self) -> None:
        self.found = self.services.find(self.given["mod_installer"], self.given["weidu"])
        for tool, _name in TOOLS:
            found = self.found[tool]
            if found.ok:
                text = f"{found.path} - version {found.version} ({found.source})"
                if found.note:
                    text += f"\n{found.note}"
            else:
                text = found.problem or "not found"
            self.tool_state[tool].setText(text)
        weidu = self.found["weidu"]
        self.download_weidu.setVisible(not weidu.ok and self.services.pin("weidu") is not None)

    def _refresh_backups(self) -> None:
        try:
            self.games = self.services.games(self.project_dir)
        except Exception as exc:          # no game chosen: said, not a crash
            self.games = {}
            self._say(str(exc))
        while self.backup_rows.count():
            item = self.backup_rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.backup_state.clear()
        self.backup_button.clear()
        self.backed_up.clear()
        to_check: dict[str, dict] = {}
        for row, (name, folder) in enumerate(self.games.items()):
            state = _plain("")
            button = QPushButton("Back up now")
            button.setAccessibleName(f"Back up {name}")
            button.clicked.connect(lambda _checked=False, f=folder: self.back_up(f))
            self.backup_state[folder], self.backup_button[folder] = state, button
            self.backup_rows.addWidget(QLabel(f"<b>{name}</b>"), row, 0)
            self.backup_rows.addWidget(state, row, 1)
            self.backup_rows.addWidget(button, row, 2)
            newest = self._show_backup(folder)
            if newest is not None:
                to_check[folder] = newest
        if to_check:
            self._check_backups(to_check)

    def _show_backup(self, folder: str) -> dict | None:
        """The newest backup of this very folder, said; None when there is none."""
        try:
            listed = self.services.backups(folder) if folder else []
        except Exception as exc:          # an unreadable backups folder
            self.backup_state[folder].setText(f"{folder}: {exc}")
            return None
        # only a backup of this very folder counts (review of #87): the
        # backups folder may hold another's, e.g. a game folder moved
        found = [b for b in listed if _same(b.get("game_dir", folder), folder)]
        if listed and not found:
            self.backup_state[folder].setText(
                f"{folder}\nthe backups beside it are of another folder "
                f"({listed[0].get('game_dir')}): they do not count")
            return None
        if not found:
            self.backup_state[folder].setText(f"{folder}\nno backup yet")
            return None
        newest = found[0]
        self.backup_state[folder].setText(
            f"{folder}\nbacked up {newest['created']}: {newest['path']} - checking that "
            f"the game is still as it was then...")
        return dict(newest)

    def _check_backups(self, newest: dict[str, dict]) -> None:
        """
        A backup counts only if restoring it would change nothing: the game is
        as it was when it was made (review of #87). plan_restore hashes the
        game's files against it, so it runs in a thread of its own.
        """
        self._check_round += 1
        round_, restore_plan = self._check_round, self.services.restore_plan

        def check() -> dict:
            out: dict = {}
            for folder, backup in newest.items():
                try:
                    out[folder] = restore_plan(backup["path"], folder)
                except Exception as exc:  # unreadable: said, and not counted
                    out[folder] = {"error": str(exc)}
            return out

        # the check has ended once its result is shown: the thread's finished
        # signal may arrive before its result does (it is not queued behind it)
        def done(results: dict) -> None:
            if round_ == self._check_round:
                self._checked(newest, results)
                self._checking = None
                self._buttons()

        def failed(_message: str) -> None:
            if round_ == self._check_round:
                self._checking = None
                self._buttons()

        self._checking = _in_thread(check, done, failed, lambda: None, owner=self)

    def _checked(self, newest: dict[str, dict], results: dict) -> None:
        for folder, result in results.items():
            backup = newest[folder]
            label = self.backup_state.get(folder)
            if label is None:
                continue
            changed = (len(result.get("put_back", [])) + len(result.get("displace", []))
                       + len(result.get("cannot_restore", [])))
            if result.get("error"):
                label.setText(f"{folder}\nthe backup {backup['path']} cannot be checked: "
                              f"{result['error']}")
            elif changed and self.progress.get("state") == "partial":
                # what changed is the install that stopped: the backup is from
                # before it, and is what to restore to start from scratch
                self.backed_up[folder] = backup["path"]
                label.setText(
                    f"{folder}\nbacked up {backup['created']}: {backup['path']} - before "
                    f"the install that stopped ({changed} file(s) changed since); "
                    f"restoring it goes back to before that install")
            elif changed:
                label.setText(
                    f"{folder}\nthe game changed after the backup of {backup['created']} "
                    f"({changed} file(s) differ): restoring it would lose that - make a "
                    f"new backup")
            else:
                self.backed_up[folder] = backup["path"]
                label.setText(f"{folder}\nbacked up {backup['created']}: {backup['path']} "
                              f"({backup['files']} files) - the game is as it was then")
        self._buttons()

    # ------------------------------------------------------------ the programs
    def _choose(self, tool: str) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, f"Where is {tool}?")
        if path:
            self.use(tool, path)

    def use(self, tool: str, path: str | None) -> None:
        """The program the player chose (None: find it again)."""
        self.given[tool] = path or None
        self.refresh()

    def confirm(self, title: str, text: str) -> bool:
        """Yes or no, asked of the player (a test answers instead)."""
        answer = QMessageBox.question(self, title, text)
        return bool(answer == QMessageBox.StandardButton.Yes)

    def offer_weidu(self) -> None:
        """Download WeiDU, once the player has read what and from where."""
        pin = self.services.pin("weidu")
        if pin is None or self.running():
            return
        text = (f"Download WeiDU {pin.version} for this system?\n\n"
                f"From: {pin.url}\n"
                f"Licence: {pin.licence} - {pin.home}\n"
                f"Checked against its sha256 before it is unpacked, then kept in "
                f"{api.default_tools_dir()} and used for the install.")
        if not self.confirm("Download WeiDU", text):
            return
        self._cancel = threading.Event()
        cancel, download, bridge = self._cancel, self.services.download, self._bridge

        def progress(done: int, total: int | None) -> None:
            now = time.monotonic()
            if now - self._last >= PROGRESS_EVERY_S or done == total:
                self._last = now
                bridge.status.emit(f"Downloading WeiDU: {_size(done)}"
                                   + (f" of {_size(total)}" if total else ""))

        self._say("Downloading WeiDU...")
        self._run(lambda: download("weidu", progress=progress, cancel=cancel),
                  self._downloaded)

    def _downloaded(self, found: Any) -> None:
        self._say(f"WeiDU downloaded: {found.path}" if found.ok
                  else f"WeiDU was downloaded but cannot be used: {found.problem}")

    # ------------------------------------------------------------ the backups
    def back_up(self, folder: str) -> None:
        if self.running():
            return
        self._cancel = threading.Event()
        cancel, backup, bridge = self._cancel, self.services.backup, self._bridge

        def on_event(event: dict) -> None:
            kind = event.get("event")
            now = time.monotonic()
            if kind == "backup_progress" and now - self._last < PROGRESS_EVERY_S:
                return
            self._last = now
            if kind == "backup_started":
                bridge.status.emit(f"Backing up {folder}: {event.get('files', 0)} files, "
                                   f"{_size(int(event.get('bytes') or 0))}")
            elif kind == "backup_progress":
                bridge.status.emit(f"Backing up {folder}: "
                                   f"{_size(int(event.get('bytes') or 0))} of "
                                   f"{_size(int(event.get('total') or 0))}")

        self._say(f"Backing up {folder}...")
        self._run(lambda: backup(folder, on_event=on_event, cancel=cancel),
                  lambda path: self._say(f"Backed up {folder} to {path}"))

    # ------------------------------------------------------------ the install
    def ready(self) -> list[str]:
        """What still stops the install, in words; [] when nothing does."""
        missing = []
        if self.wanted is None:
            missing.append("no selection: go through the earlier phases first")
        for tool, name in TOOLS:
            found = self.found.get(tool)
            if found is None or not found.ok:
                missing.append(f"{name}: {found.problem if found else 'not looked for'}")
        if not self.games:
            missing.append("no game folders: set them on the first page")
        if self.progress.get("state") == "mismatch":
            missing.append(f"the install cannot resume: {self.progress.get('problem')}")
        for folder in self.games.values():
            if folder not in self.backed_up:
                missing.append(f"no backup of {folder or 'a game folder'} as it is now"
                               + (" (checking...)" if self._checking is not None else ""))
        return missing

    def install(self) -> None:
        """
        Write the plan from the selection as it is now (never an earlier
        one: review of #87), then ask - naming the folders, the backups and
        what the order still breaks - and only then run mod_installer.
        """
        if self.running() or self.ready() or self.wanted is None:
            return
        game, chosen, labels = self.wanted
        services, folder = self.services, self.project_dir
        self._cancel = threading.Event()
        self.output.clear()
        self.outcome = None
        self._say("Writing the install order...")
        self._run(lambda: _plan_and_questions(services, game, chosen, labels, folder),
                  self._planned)

    def _planned(self, plan: dict) -> None:
        """The plan is written: ask, then install (after _finished has run)."""
        self._plan_written = plan
        for note in plan.get("languages", []):
            self._append(note)

    def _confirm_and_run(self, plan: dict) -> None:
        game, chosen, _labels = self.wanted or ("", [], {})
        progress = self.services.progress(plan["plan_dir"], self.games)
        state = progress.get("state")
        if state == "mismatch":
            self._say(f"Not installed: {progress.get('problem')}. Restore the backup "
                      f"to start again.")
            return
        if state == "finished":
            self._say("Nothing to install: every planned component is already in the games.")
            return
        resuming = state == "partial"
        coverage = self._questionnaire(plan)
        if coverage is None:
            return
        folders = "\n".join(f"  {name}: {folder}" for name, folder in self.games.items())
        backups = "\n".join(f"  {path}" for path in self.backed_up.values())
        broken = list(plan.get("violations", [])) + [
            "a cycle: " + " -> ".join(cycle) for cycle in plan.get("cycles", [])]
        shown = [f"  - {b}" for b in broken[:MAX_SHOWN]]
        if len(broken) > MAX_SHOWN:
            shown.append(f"  ... and {len(broken) - MAX_SHOWN} more (the order page lists them)")
        warning = ("" if not broken else
                   f"The order still breaks {len(broken)} rule(s) - in red on the order "
                   f"page. Going on installs it as it is:\n" + "\n".join(shown) + "\n\n")
        what = (f"Resume the install that stopped: {progress['done']} of "
                f"{progress['total']} component(s) are already in; the other "
                f"{progress['total'] - progress['done']} install now, into:"
                if resuming else f"Install {len(chosen)} component(s) into:")
        title = ("Resume anyway" if resuming else "Install anyway") if broken else \
            ("Resume" if resuming else "Install")
        try:                              # what is known to go wrong (item 65)
            issues = self.services.known_issues(dict(self.games),
                                                self.services.mods_dir(self.project_dir))
        except Exception:                 # a check that cannot run says nothing
            issues = []
        known = ("" if not issues else
                 "Known issue(s) this install will meet:\n"
                 + "\n".join(f"  - {issue}" for issue in issues) + "\n\n")
        if issues:
            title = ("Resume" if resuming else "Install") + (" anyway," if broken else "") \
                + " despite a known issue"
        asking = _questions_text(coverage)
        stopped = ("" if not (resuming and self.cancelled_in) else
                   f"The last run was cancelled while it installed {self.cancelled_in}: "
                   f"if that left files in the game, restoring the backup is the safe "
                   f"way.\n\n")
        if not self.confirm(title, (
                f"{what}\n{folders}\n\n{stopped}{known}{warning}{asking}"
                f"mod_installer and WeiDU change these folders. Nothing is undone by "
                f"itself: to start again, restore the backup -\n{backups}\n\nGo on?")):
            self._say("Not installed: the plan is written in "
                      f"{plan['plan_dir']}, nothing else was done.")
            return
        services, folder, games = self.services, self.project_dir, dict(self.games)
        tools = {tool: self.found[tool].path for tool, _name in TOOLS}
        cancel, bridge = self._cancel, self._bridge

        def on_event(event: Any) -> None:
            text = event.text
            if event.kind == "batch":
                names = ", ".join(f"{tp2} #{number}" for tp2, number in event.batch)
                self._running_batch, text = names, "== " + names
            elif event.kind == "answer":
                text = f"-> {text}"
            bridge.line.emit(text)

        def run() -> Any:
            if cancel.is_set():
                return "cancelled"
            install = services.start(plan["plan_dir"], games, services.mods_dir(folder),
                                     tools["mod_installer"], tools["weidu"],
                                     ask=self._from_install, on_event=on_event,
                                     resume=resuming, **services.timing)
            self._install = install
            if cancel.is_set():                 # Cancel while it was being set up
                install.cancel()
            bridge.status.emit("Installing...")
            return install.run()

        self._say("Resuming..." if resuming else "Installing...")
        self._run(run, self._installed)

    def _questionnaire(self, plan: dict) -> dict | None:
        """
        The questions the install will meet, answered before it starts
        (ADR-0049): those that can be answered beforehand and have no answer
        kept yet are put to the player in one dialog; the answers are kept
        in the project and written into the planned logs. Returns what the
        install will still ask ({} when that could not be read); None when
        the player cancelled - nothing is installed.
        """
        services, folder = self.services, self.project_dir
        mods = services.mods_dir(folder)
        coverage = plan.get("questions") or {}
        if not coverage:                  # could not be read: nothing to say
            return {}
        kept = services.load_answers(folder)
        open_ = [c for c in coverage["components"]
                 if any(q["beforehand"] and q["key"] not in kept.get(api.answer_key(c), {})
                        for q in c["questions"])]
        if open_:
            given = self.answer_questions(
                [c for c in coverage["components"]
                 if any(q["beforehand"] for q in c["questions"])], kept)
            if given is None:
                self._say("Not installed: the questions were not answered. The plan is "
                          f"written in {plan['plan_dir']}, nothing else was done.")
                return None
            kept = given
            try:
                services.save_answers(folder, kept)
            except OSError as exc:
                self._append(f"The answers could not be kept in the project: {exc}")
        try:
            return services.write_answers(plan["plan_dir"], mods, kept, coverage=coverage)
        except (OSError, ValueError) as exc:
            self._say(f"Not installed: the answers could not be written - {exc}")
            return None

    def answer_questions(self, components: list, kept: dict) -> dict | None:
        """The player's answers to the questions that can be answered before
        the install, from those kept; None cancels (a test answers instead)."""
        dialog = _Questionnaire(self, components, kept)
        return dialog.answers() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def _from_install(self, question: str, _batch: tuple) -> str | None:
        """Called on the install's thread: ask on the page's, wait for the answer."""
        asked = _Question(question)
        self._bridge.question.emit(asked)
        asked.ready.wait()
        return asked.answer

    def _ask(self, asked: _Question) -> None:
        self._asking = asked
        self._append(asked.text)
        answer = self.ask_player(asked.text)
        if self._asking is asked:               # not answered by Cancel meanwhile
            self._asking = None
            asked.give(answer)

    def ask_player(self, question: str) -> str | None:
        """The player's answer to WeiDU's question; None cancels the install."""
        text, ok = QInputDialog.getText(
            self, "WeiDU asks", question + "\n\n(Cancel stops the install.)")
        return text if ok else None

    def stop(self) -> None:
        """Cancel what runs: the install and everything it started."""
        self._cancel.set()
        if self._install is not None:
            self._install.cancel()
        if self._asking is not None:
            asked, self._asking = self._asking, None
            asked.give(None)
        if self.running():
            self._say("Stopping...")

    def _installed(self, outcome: Any) -> None:
        if outcome == "cancelled":
            self._say("Cancelled before mod_installer started: nothing was changed.")
            return
        self.outcome = outcome
        self.cancelled_in = self._running_batch if getattr(outcome, "cancelled", False) else None
        self._running_batch = None
        backups = ", ".join(self.backed_up.values())
        if outcome.ok:
            self._say("Installed. Each game's WeiDU.log lists what went in.")
            return
        # where it stopped decides what is said: a component stopped inside
        # cannot be resumed (resume.half_way), only restored
        self._refresh_progress()
        state, restore = self.progress.get("state"), f"restore the backup ({backups})"
        if state == "mismatch":
            then = (f"It cannot resume - {self.progress.get('problem')}: {restore} to start "
                    f"again.")
        elif state == "partial":
            then = f"Install resumes from there, or {restore} to start again."
        else:
            then = f"Install starts it again, or {restore} if the game changed."
        if outcome.cancelled:
            self._say(f"Cancelled. What was installed until then stays. {then}")
        else:
            self._say(f"mod_installer stopped with exit status {outcome.returncode}: "
                      f"the output above says where; once it is fixed: {then}")

    # ------------------------------------------------------------ plumbing
    def running(self) -> bool:
        return self._thread is not None

    def _run(self, call: Callable[[], Any], done: Callable[[Any], None]) -> None:
        self._thread = _in_thread(call, done, self._failed, self._finished, owner=self)
        self._buttons()
        self.completeChanged.emit(False)

    def _failed(self, message: str) -> None:
        self._say(message)

    def _finished(self) -> None:
        self._thread = None
        self._install = None
        self._asking = None
        plan, self._plan_written = self._plan_written, None
        if plan is not None and not self._cancel.is_set():
            # asked on what was checked before the plan was written: looking
            # again first would empty the backups until their check ends
            self._confirm_and_run(plan)         # its own run, or nothing if refused
            if self.running():
                return
        self.refresh()
        self.completeChanged.emit(self.is_complete())
        self.finished.emit()

    def _append(self, text: str) -> None:
        self.output.appendPlainText(text)

    def _say(self, text: str) -> None:
        self.summary.setText(text)

    def _buttons(self) -> None:
        busy = self.running()
        missing = self.ready()
        self.install_button.setEnabled(not busy and not missing)
        self.install_button.setToolTip("\n".join(missing) if missing else
                                       "Install the planned order into the game folders")
        self.cancel_button.setEnabled(busy)
        self.download_weidu.setEnabled(not busy)
        for button in (*self.choose.values(), *self.backup_button.values()):
            button.setEnabled(not busy)
        self.needs.setText("" if busy or not missing else
                           "Before installing:\n" + "\n".join(f"- {m}" for m in missing))

    def is_complete(self) -> bool:
        """The install ran to its end without an error."""
        return bool(self.outcome is not None and getattr(self.outcome, "ok", False))


def _plan_and_questions(services: Services, game: str, chosen: list, labels: dict,
                        folder: str) -> dict:
    """On a worker thread: write the plan, then read the questions its mods
    will ask - every mod's files, too slow for the window's thread (review
    of #107). A reading that fails says nothing: {}."""
    plan = services.plan(game, chosen, labels, folder)
    try:
        plan["questions"] = services.questions(plan["plan_dir"], services.mods_dir(folder))
    except Exception:
        plan["questions"] = {}
    return plan


class _Questionnaire(QDialog):
    """Every question that can be answered before the install, one field
    each, under its component; what is kept is filled in (ADR-0049)."""

    def __init__(self, parent: QWidget, components: list, kept: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Questions the mods will ask")
        self.kept = {name: dict(given) for name, given in kept.items()}
        self.fields: list[tuple[str, str, QLineEdit]] = []
        form = QFormLayout()
        for component in components:
            name = api.answer_key(component)
            form.addRow(_plain(f"{component['tp2']} #{component['number']}"))
            for question in component["questions"]:
                if not question["beforehand"]:
                    continue
                edit = QLineEdit(self.kept.get(name, {}).get(question["key"], ""))
                edit.setAccessibleName(question["text"])
                hint = " (asked until the answer is valid)" if question["repeats"] else ""
                form.addRow(_plain(question["text"] + hint), edit)
                self.fields.append((name, question["key"], edit))
        inner = QWidget()
        inner.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        self.problem = _plain("")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(_plain(
            "These questions come during the install. Answered here, the install "
            "gives the answers itself; an empty field is an Enter. Questions that "
            "depend on a condition or on what happens while installing are asked "
            "then, as before."))
        layout.addWidget(scroll)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        bad = [edit.accessibleName() for _name, _key, edit in self.fields
               if not api.writable_answer(edit.text())]
        if bad:
            self.problem.setText("An answer cannot hold a comma or a line break: "
                                 + "; ".join(bad))
            return
        self.accept()

    def answers(self) -> dict:
        for name, key, edit in self.fields:
            self.kept.setdefault(name, {})[key] = edit.text().strip()
        return self.kept


def _questions_text(coverage: dict) -> str:
    """What the confirmation says of the questions still to come."""
    components = coverage.get("components", [])
    if not components:
        return ""
    still = [c for c in components if c["status"] not in ("none", "answered")]
    if not still:
        return ("Every question found is answered: the install should not stop to ask "
                "(read from the mods' files - what they decide while installing is not "
                "known before).\n\n")
    words = {"unknown": "could not be read in full - it may ask",
             "maybe": "may ask a question that depends on a condition",
             "partial": "will ask questions not answered beforehand",
             "unanswered": "will ask"}
    shown = [f"  - {c['tp2']} #{c['number']}: {words.get(c['status'], c['status'])}"
             for c in still[:MAX_SHOWN]]
    if len(still) > MAX_SHOWN:
        shown.append(f"  ... and {len(still) - MAX_SHOWN} more")
    return (f"{len(still)} component(s) may stop the install to ask - answer them in "
            f"this window when they do:\n" + "\n".join(shown) + "\n\n")


def _progress_text(progress: dict) -> str:
    state = progress.get("state")
    if state == "partial":
        nexts = [p["next"] for p in progress.get("phases", []) if p.get("next")]
        return (f"An install stopped here: {progress['done']} of {progress['total']} "
                f"component(s) are in" + (f", next {nexts[0]}" if nexts else "")
                + ". Install resumes from there; nothing in is installed again.")
    if state == "finished":
        return "Every planned component is in the games."
    if state == "mismatch":
        return (f"The install cannot resume - {progress.get('problem')}. Restore the "
                f"backup to start again.")
    return ""


def _same(one: str, other: str) -> bool:
    return os.path.normcase(os.path.abspath(one)) == os.path.normcase(os.path.abspath(other))


def _plain(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label
