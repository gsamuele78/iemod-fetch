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
DRAIN_S = 2.0            # its output still open this long after it ended: stop the rest


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


def _program(path: str) -> bool:
    """A file this system runs: executable on POSIX; on Windows, where every
    file reads as executable, by its extension (PATHEXT)."""
    if not os.path.isfile(path):
        return False
    if sys.platform == "win32":
        known = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(";")
        return os.path.splitext(path)[1].lower() in known
    return os.access(path, os.X_OK)


def _windows() -> bool:
    return sys.platform == "win32"


def preflight(games: dict[str, str], mods_dir: str, mod_installer: str, weidu: str,
              allow_existing: bool = False) -> list[str]:
    """What stops the install before it starts, in words; [] when nothing."""
    problems = []
    for name, folder in games.items():
        if not os.path.isdir(folder):
            problems.append(f"{name}: {folder} is not a folder")
        elif not os.path.isfile(os.path.join(folder, "chitin.key")):
            problems.append(f"{name}: no chitin.key in {folder} - not a game folder")
        elif not allow_existing and (installed := _has_mods(folder)):
            problems.append(f"{name}: {folder} already has mods installed "
                            f"({installed}); the plan is for a fresh game - "
                            "restore its backup first")
    if not os.path.isdir(mods_dir):
        problems.append(f"the mods folder {mods_dir} does not exist - download first")
    elif sys.platform.startswith("linux"):
        # mod_installer hands WeiDU lower-cased paths (ADR-0022)
        mixed = next((entry for entry in sorted(os.listdir(mods_dir))
                      if entry != entry.lower() and not entry.startswith(".")), None)
        if mixed:
            problems.append(f"mods must be lower-case on Linux: {mixed} in {mods_dir}")
    bgee = games.get("BGEE", "") if "EET" in games else ""
    if _windows() and not bgee.isascii():
        # EET asks for this folder and mod_installer passes the answer to
        # WeiDU as UTF-8 - the only encoding it reads its own input in. How
        # WeiDU on Windows opens a path given so is not measured (ADR-0045):
        # refused rather than guessed.
        problems.append(f"BGEE: {bgee} has letters outside plain ASCII; EET is told this "
                        "folder through WeiDU's input, which on Windows is not known to "
                        "take them - rename the folder (or its parents) first")
    for name, path in (("mod_installer", mod_installer), ("WeiDU", weidu)):
        if not _program(path):
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
                 grace_s: float = GRACE_S, drain_s: float = DRAIN_S) -> None:
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
        self.quiet_s, self.grace_s, self.drain_s = quiet_s, grace_s, drain_s
        self._cancel = threading.Event()
        self._process: subprocess.Popen | None = None
        self._job = _Job()

    def cancel(self) -> None:
        """Stop the install, from any thread."""
        self._cancel.set()

    def run(self) -> Outcome:
        outcome = Outcome(None)
        # Its own process group (POSIX) or job (Windows): cancelling, or its
        # end, must reach WeiDU and whatever else it started too.
        group: dict = {"start_new_session": True}
        if sys.platform == "win32":
            group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        process = subprocess.Popen(  # noqa: S603 (the player's own mod_installer)
            self.argv, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, env=child_env({"RUST_LOG": "info"}),
            text=True, encoding="utf-8", errors="replace", bufsize=1, **group)
        self._process = process
        self._job = _Job.holding(process)
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
            self._job.close()
        return outcome

    def _pump(self, process: subprocess.Popen, outcome: Outcome) -> None:
        """Read the output until it ends, answering and cancelling as it goes."""
        lines: queue.Queue[str | None] = queue.Queue()
        stdout = process.stdout

        def read() -> None:
            if stdout is not None:
                with stdout:
                    for line in stdout:
                        lines.put(line)
            lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        reader = OutputReader()
        exited_at: float | None = None
        while True:
            if self._cancel.is_set():
                self._stop(process)
                outcome.cancelled = True
                return
            if exited_at is None and process.poll() is not None:
                exited_at = time.monotonic()
            if exited_at is not None and time.monotonic() - exited_at > self.drain_s:
                # mod_installer has ended and something it started still holds
                # its output (review of #83): what is left would go on writing
                # into the game folder, alone - it is stopped, and said so.
                self._stop(process)
                self.on_event(Event("line", "mod_installer ended, but what it started "
                                            "was still running: stopped"))
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
        try:
            if process.stdin is None:
                raise OSError("no standard input")
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
            self._signal(process, kill=False)
            deadline = time.monotonic() + self.grace_s
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
        # WeiDU may outlive mod_installer: the group goes, whatever is left of it
        self._signal(process, kill=True)

    def _signal(self, process: subprocess.Popen, kill: bool) -> None:
        """Terminate (or kill) mod_installer's process group, or its job."""
        if sys.platform == "win32":
            if kill:
                # the job holds every process it started, living parent or not
                self._job.terminate()
            elif process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):   # gone already
            os.killpg(process.pid, signal.SIGKILL if kill else signal.SIGTERM)


class _Job:
    """
    Windows: a Job Object holding mod_installer and every process it starts
    (they inherit it), killed together whatever order they die in - taskkill
    /T walks the tree from a living parent, and finds nothing once
    mod_installer is gone (review of #83). It is also killed when this
    program ends (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE). Elsewhere it does
    nothing: the process group does this.
    """

    def __init__(self, handle: int | None = None) -> None:
        self.handle = handle

    @classmethod
    def holding(cls, process: subprocess.Popen) -> _Job:
        return cls(_new_job(process)) if sys.platform == "win32" else cls()

    def terminate(self) -> None:
        if self.handle and sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            ctypes.WinDLL("kernel32").TerminateJobObject(wintypes.HANDLE(self.handle), 1)

    def close(self) -> None:
        if self.handle and sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(self.handle))
        self.handle = None


def _new_job(process: subprocess.Popen) -> int:
    """A kill-on-close Job Object, `process` in it (Windows only)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic),
                        ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000   # KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        ok = ok and kernel32.AssignProcessToJobObject(
            wintypes.HANDLE(job), wintypes.HANDLE(int(process._handle)))  # noqa: SLF001
        if not ok:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(wintypes.HANDLE(job))
            process.kill()
            raise OSError(error, "mod_installer could not be put in a job")
        return job
    raise OSError("Job Objects are Windows'")


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
