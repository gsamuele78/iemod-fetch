"""
WeiDU's prompts in an install mod_installer runs (GUI-AUDIT M4 item 22,
ADR-0045): what it asks, and the answers recorded for it.

mod_installer (dark0dave, GPL-3.0, read at 16.0.0) installs a WeiDU.log in
batches of consecutive components of one mod, logging each batch before it
starts:

    [2026-10-24T00:00:00Z INFO  mod_installer::installers] Installing mod
    WeiduBatchedComponents([WeiduComponent { tp_file: "EET.TP2", name: "EET",
    lang: "0", component: "0", ... }])

When WeiDU waits for an answer it logs `User Input required`, `Question is`
and the question, then reads one line from its own standard input and gives
it to WeiDU. Only EET's question for the BG:EE folder is answered by
mod_installer itself, and only on Linux.

The answers a player recorded ride on the component's line of the WeiDU.log,
as Born2BSalty's Infinity Orchestrator writes them (GPL-3.0; the format read
at 33800cc, no code copied):

    ~SOMEMOD\\SETUP-SOMEMOD.TP2~ #0 #10 // Confirm install: v1.0 // @wlb-inputs: y,,c

left to right, `,,` an empty answer (Enter). An answer cannot hold a comma.

This module only reads: the log's answers, and mod_installer's output, line
by line, into events. Running mod_installer is install_run.py's.
"""
import re
from collections import deque
from dataclasses import dataclass, field

TAG = "// @wlb-inputs:"
# What EET asks for the BG:EE folder (mod_installer's own `eet_auto_fill`).
EET_FOLDER_QUESTION = "enter the full path to your bg:ee+sod installation"

_LOG_LINE = re.compile(r"^\s*~(?P<path>[^~]+)~\s+#(?P<lang>\d+)\s+#(?P<number>\d+)")
_RECORD = re.compile(r"^\[\S+\s+(?P<level>[A-Z]+)\s+(?P<target>[\w:]+)\]\s?(?P<text>.*)$")
_COMPONENT = re.compile(r'WeiduComponent \{ tp_file: "(?P<tp2>[^"]*)", name: "[^"]*", '
                        r'lang: "[^"]*", component: "(?P<number>\d+)"')
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

Key = tuple[str, int]          # (tp2 file name, lower-cased; component number)


def tp2_name(path: str) -> str:
    """`EET\\EET.TP2`, `eet/eet.tp2` -> `eet.tp2`: how both sides name a tp2."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def wlb_inputs(line: str) -> list[str] | None:
    """The answers a WeiDU.log component line records, None if it has none."""
    at = line.find(TAG)
    if at < 0:
        return None
    return [answer.strip() for answer in line[at + len(TAG):].strip().split(",")]


def recorded_answers(log_text: str) -> dict[Key, list[str]]:
    """Every component line's recorded answers in a WeiDU.log, by component."""
    out: dict[Key, list[str]] = {}
    for line in log_text.splitlines():
        match = _LOG_LINE.match(line)
        answers = wlb_inputs(line) if match else None
        if match and answers is not None:
            out[(tp2_name(match["path"]), int(match["number"]))] = answers
    return out


@dataclass
class Event:
    kind: str                  # "line" | "batch" | "question"
    text: str = ""
    batch: tuple[Key, ...] = ()


@dataclass
class OutputReader:
    """
    mod_installer's output, one line at a time, as events. A question has
    no end of its own - mod_installer logs it and waits - so it is collected
    until `question()` is called, when the output has gone quiet.
    """
    _asking: list[str] | None = None        # a question's lines, once announced
    _announced: bool = False                # "User Input required" seen
    batch: tuple[Key, ...] = ()

    def feed(self, raw: str) -> list[Event]:
        line = _ANSI.sub("", raw).rstrip("\r\n")
        events = [Event("line", line)]
        record = _RECORD.match(line)
        if record is None:
            if self._asking is not None:
                self._asking.append(line)          # the question goes on
            return events
        if self._asking is not None and self._asking:
            # a new record after a question: WeiDU answered it itself
            self._asking = None
        text = record["text"]
        if text.startswith("Installing mod "):
            self.batch = tuple((tp2_name(m["tp2"]), int(m["number"]))
                               for m in _COMPONENT.finditer(text))
            events.append(Event("batch", text, self.batch))
        elif text == "User Input required":
            self._announced = True
        elif text == "Question is" and self._announced:
            self._announced = False
            self._asking = []
        elif self._asking is not None:
            self._asking.append(text)
        return events

    @property
    def asking(self) -> bool:
        """A question is being collected."""
        return self._asking is not None

    def question(self) -> Event | None:
        """The question collected so far, once the output went quiet."""
        if self._asking is None:
            return None
        text = "\n".join(self._asking).strip("\n")
        self._asking = None
        return Event("question", text, self.batch)


@dataclass
class Answers:
    """The recorded answers of a log, handed out batch by batch, in order."""
    recorded: dict[Key, list[str]]
    _queue: deque = field(default_factory=deque)
    _batch: tuple[Key, ...] = ()

    def start(self, batch: tuple[Key, ...]) -> None:
        """A batch starts: its components' answers, in the batch's order."""
        self._batch = batch
        self._queue = deque(answer for key in batch for answer in self.recorded.get(key, ()))

    def next(self) -> str | None:
        """The next recorded answer of the batch, None when there is none."""
        return self._queue.popleft() if self._queue else None
