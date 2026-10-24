"""
Running the install: mod_installer, as a child of this program (GUI-AUDIT M4
item 22, ADR-0045, amending ADR-0022).

The command line still only writes the scripts; this is what the wizard's
Installation phase runs, once the player has said so. It starts the same
mod_installer command the scripts start, after the checks the scripts make
(a game folder, a game with no mods yet, mixed-case mod folders on Linux),
reads its output line by line and passes each one on, and answers WeiDU's
questions: EET's question for the BG:EE folder with that folder, then the
answers the planned log records for the batch being installed
(`// @wlb-inputs:`), and anything else by asking the player. Nothing it
downloaded is started by this program: mod_installer starts WeiDU, and
WeiDU runs the mods' tp2s - which is what installing them means.

Cancelling stops mod_installer and everything it started - WeiDU above all,
which would otherwise go on writing into the game folder: mod_installer runs
in a process group of its own (a session on POSIX, a new process group on
Windows), which is terminated, then killed after a grace period (POSIX:
killpg; Windows: `taskkill /T /F`). The WeiDU.log in the game folder says
what was installed: resuming from it is item 23.
"""
import contextlib
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .childenv import child_env
from .errors import ConfigError
from .prompts import EET_FOLDER_QUESTION, Answers, Event, OutputReader, recorded_answers

# What the planned logs are called (ordering.PRE_EET_LOG, EET_LOG)
PRE_EET_LOG, EET_LOG = "WeiDU-BGEE.log", "WeiDU.log"
QUIET_S = 0.5            # no output for this long after a question: it is complete
GRACE_S = 10.0           # terminate, then kill after this long


@dataclass
class Answered:
    question: str
    answer: str
    source: str           # "EET" | "recorded" | "player"


@dataclass
class Outcome:
    returncode: int | None
    cancelled: bool = False
    answered: list[Answered] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.cancelled


def _has_mods(game_dir: str) -> str:
    """The WeiDU.log of a game that already has mods installed, else ''."""
    for name in ("WeiDU.log", "weidu.log"):
        path = os.path.join(game_dir, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                if any(line.startswith("~") for line in fh):
                    return path
        except OSError:
            continue
    return ""


def preflight(games: dict[str, str], mods_dir: str, mod_installer: str, weidu: str,
              allow_existing: bool = False) -> list[str]:
    """What stops the install before it starts, in words; [] when nothing."""
    problems = []
    for name, folder in games.items():
        if not os.path.isdir(folder):
            problems.append(f"{name}: {folder} is not a folder")
        elif not os.path.isfile(os.path.join(folder, "chitin.key")):
            problems.append(f"{name}: no chitin.key in {folder} - not a game folder")
        elif not allow_existing and _has_mods(folder):
            problems.append(f"{name}: {folder} already has mods installed "
                            f"({_has_mods(folder)}); the plan is for a fresh game - "
                            "restore its backup first")
    if not os.path.isdir(mods_dir):
        problems.append(f"the mods folder {mods_dir} does not exist - download first")
    elif sys.platform.startswith("linux"):
        # mod_installer hands WeiDU lower-cased paths (ADR-0022)
        mixed = next((entry for entry in sorted(os.listdir(mods_dir))
                      if entry != entry.lower() and not entry.startswith(".")), None)
        if mixed:
            problems.append(f"mods must be lower-case on Linux: {mixed} in {mods_dir}")
    for name, path in (("mod_installer", mod_installer), ("WeiDU", weidu)):
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            problems.append(f"{name} is not a program here: {path}")
    return problems


def command(plan_dir: str, games: dict[str, str], mods_dir: str, mod_installer: str,
            weidu: str, language: str = "en_US") -> list[str]:
    """mod_installer's command for a planned install, as the scripts write it.
    `games` is {"BGEE": ..., "EET": ...} for EET, else one game."""
    tail = ["--mod-directories", mods_dir, "--weidu-binary", weidu, "--language", language]
    if "EET" in games and "BGEE" in games:
        return [mod_installer, "eet",
                "--bg1-game-directory", games["BGEE"],
                "--bg1-log-file", os.path.join(plan_dir, PRE_EET_LOG),
                "--bg2-game-directory", games["EET"],
                "--bg2-log-file", os.path.join(plan_dir, EET_LOG), *tail]
    (game, folder), = games.items()
    log = PRE_EET_LOG if game == "BGEE" and not os.path.isfile(
        os.path.join(plan_dir, EET_LOG)) else EET_LOG
    return [mod_installer, "normal", "--game-directory", folder,
            "--log-file", os.path.join(plan_dir, log), *tail]


class InstallRun:
    """
    One run of mod_installer. `on_event` gets every line, batch and answer;
    `ask(question, batch)` is called for a question nothing recorded answers,
    from the thread that called run(), and returns the answer - None cancels.
    """

    def __init__(self, argv: list[str], logs: list[str], cwd: str,
                 ask: Callable[[str, tuple], str | None],
                 on_event: Callable[[Event], None] = lambda _event: None,
                 bgee_dir: str | None = None, quiet_s: float = QUIET_S,
                 grace_s: float = GRACE_S) -> None:
        recorded: dict = {}
        for path in logs:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    recorded.update(recorded_answers(fh.read()))
            except OSError:
                continue
        self.argv, self.cwd, self.ask, self.on_event = argv, cwd, ask, on_event
        self.bgee_dir = bgee_dir
        self.answers = Answers(recorded)
        self.quiet_s, self.grace_s = quiet_s, grace_s
        self._cancel = threading.Event()
        self._process: subprocess.Popen | None = None

    def cancel(self) -> None:
        """Stop the install, from any thread."""
        self._cancel.set()

    def run(self) -> Outcome:
        outcome = Outcome(None)
        # the pipes close with the block, whatever ends it
        # its own process group, so that cancelling reaches WeiDU too
        group: dict = {"start_new_session": True}
        if sys.platform == "win32":
            group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        process = subprocess.Popen(  # noqa: S603 (the player's own mod_installer)
            self.argv, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, env=child_env({"RUST_LOG": "info"}),
            text=True, encoding="utf-8", errors="replace", bufsize=1, **group)
        self._process = process
        try:
            self._pump(process, outcome)
        finally:
            # Only standard input is closed here: the output belongs to the
            # thread reading it, which closes it at its end. Closing it from
            # here while that thread waits on it would wait as long as anything
            # mod_installer started keeps it open (review of the tree kill).
            with contextlib.suppress(OSError):
                if process.stdin is not None:
                    process.stdin.close()
            outcome.returncode = process.wait()
        return outcome

    def _pump(self, process: subprocess.Popen, outcome: Outcome) -> None:
        """Read the output until it ends, answering and cancelling as it goes."""
        lines: queue.Queue[str | None] = queue.Queue()

        def read() -> None:
            assert process.stdout is not None
            with process.stdout:
                for line in process.stdout:
                    lines.put(line)
            lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        reader = OutputReader()
        while True:
            if self._cancel.is_set():
                self._stop(process)
                outcome.cancelled = True
                return
            try:
                line = lines.get(timeout=self.quiet_s if reader.asking
                                 else min(self.quiet_s, 0.1))
            except queue.Empty:
                question = reader.question() if reader.asking else None
                if question is not None and not self._answer(process, question, outcome):
                    self._stop(process)
                    outcome.cancelled = True
                    return
                continue
            if line is None:
                return
            for event in reader.feed(line):
                if event.kind == "batch":
                    self.answers.start(event.batch)
                self.on_event(event)

    def _answer(self, process: subprocess.Popen, question: Event, outcome: Outcome) -> bool:
        """Answer `question`; False when the player cancelled instead."""
        text = question.text
        if self.bgee_dir and EET_FOLDER_QUESTION in text.lower():
            answer, source = self.bgee_dir, "EET"
        else:
            recorded = self.answers.next()
            if recorded is not None:
                answer, source = recorded, "recorded"
            else:
                given = self.ask(text, question.batch)
                if given is None:
                    return False
                answer, source = given, "player"
        assert process.stdin is not None
        try:
            process.stdin.write(answer + "\n")
            process.stdin.flush()
        except OSError:
            return True                   # it ended meanwhile: its exit code says how
        outcome.answered.append(Answered(text, answer, source))
        self.on_event(Event("answer", f"{answer}  ({source})", question.batch))
        return True

    def _stop(self, process: subprocess.Popen) -> None:
        """Stop mod_installer and what it started: terminate, then kill."""
        if process.poll() is None:
            _signal_group(process, kill=False)
            deadline = time.monotonic() + self.grace_s
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
        # WeiDU may outlive mod_installer: the group goes, whatever is left of it
        _signal_group(process, kill=True)


def _signal_group(process: subprocess.Popen, kill: bool) -> None:
    """Terminate (or kill) the process group `process` leads."""
    if sys.platform == "win32":
        if kill:
            subprocess.run(  # noqa: S603, S607 (Windows' own taskkill)
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                env=child_env())
        elif process.poll() is None:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):   # gone already
        os.killpg(process.pid, signal.SIGKILL if kill else signal.SIGTERM)


def start(plan_dir: str, games: dict[str, str], mods_dir: str, mod_installer: str,
          weidu: str, ask: Callable[[str, tuple], str | None],
          on_event: Callable[[Event], None] = lambda _event: None,
          language: str = "en_US", allow_existing: bool = False,
          **timing) -> InstallRun:
    """An install ready to run, after the checks; ConfigError says what stops it."""
    problems = preflight(games, mods_dir, mod_installer, weidu, allow_existing)
    if problems:
        raise ConfigError("; ".join(problems))
    argv = command(plan_dir, games, mods_dir, mod_installer, weidu, language)
    logs = [os.path.join(plan_dir, name) for name in (PRE_EET_LOG, EET_LOG)]
    return InstallRun(argv, logs, cwd=mods_dir, ask=ask, on_event=on_event,
                      bgee_dir=games.get("BGEE") if "EET" in games else None, **timing)
