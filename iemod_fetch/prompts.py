"""
WeiDU's prompts in an install mod_installer runs (GUI-AUDIT M4 item 22,
ADR-0045): what it asks, and the answers recorded for it.

mod_installer (dark0dave, GPL-3.0, read at 16.0.0 and 12.1.1) installs a
WeiDU.log in batches of consecutive components of one mod (12.1.1: one
component at a time), logging each before it starts:

    [2026-10-24T00:00:00Z INFO  mod_installer::installers] Installing mod
    WeiduBatchedComponents([WeiduComponent { tp_file: "EET.TP2", name: "EET",
    lang: "0", component: "0", ... }])

When WeiDU waits for an answer it logs `User Input required`, `Question is`
and the question, then reads one line from its own standard input and gives
it to WeiDU. Only EET's question for the BG:EE folder is answered by
mod_installer itself, and only 16.0.0 on Linux.

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
# 16.0.0: `WeiduBatchedComponents([WeiduComponent { ... }, ...])`, a batch;
# 12.1.1: `Component { ... }`, one component at a time
_COMPONENT = re.compile(r'(?:Weidu)?Component \{ tp_file: "(?P<tp2>[^"]*)", name: "[^"]*", '
                        r'lang: "[^"]*", component: "(?P<number>\d+)"')
# 12.1.1 logs a growing row of dots while WeiDU works, one record a tick
_TICK = re.compile(r"\.*")
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
        if _TICK.fullmatch(text):
            return []                              # waiting, nothing said
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


# What a question offers, when it says so (GUI-AUDIT M8 item 63): "[y]es or
# [n]o", "(y/n)"; after select/choose/pick/enter/type, a list with "or"
# ("1 or 2", "1, 2 or 3"), a range ("1-3") or "between 1 and 100". Anything
# else - a path, a free number, "Press Enter" - offers nothing said.
_YES_NO = re.compile(r"\[y\]es\s+or\s+\[n\]o|\(y/n\)|\[y/n\]|\by/n\b", re.IGNORECASE)
_VERB = r"\b(?:select|choose|pick|enter|type)\b"
_LIST = re.compile(_VERB + r"[^.?!\n]*?\b(\d{1,3}(?:\s*(?:,|or)\s*\d{1,3})*\s*or\s*\d{1,3})\b",
                   re.IGNORECASE)
_RANGE = re.compile(_VERB + r"[^.?!\n]*?(?:\b(\d{1,3})\s*-\s*(\d{1,3})\b"
                    r"|\bbetween\s+(\d{1,3})\s+and\s+(\d{1,3})\b)", re.IGNORECASE)


def offered(question: str) -> set[str] | None:
    """The answers `question` says it takes, lower-case; None when it does not
    say (then any answer may be right)."""
    if _YES_NO.search(question):
        return {"y", "n", "yes", "no"}
    match = _RANGE.search(question)
    if match:
        low, high = (int(n) for n in (match[1] or match[3], match[2] or match[4]))
        if low <= high <= low + 200:
            return {str(n) for n in range(low, high + 1)}
    match = _LIST.search(question)
    if match:
        return set(re.findall(r"\d{1,3}", match[1]))
    return None


def fits(question: str, answer: str) -> bool:
    """Whether a recorded answer is one `question` offers (or it offers none)."""
    choices = offered(question)
    return choices is None or answer.strip().lower() in choices


def same_question(one: str, other: str) -> bool:
    """Two askings of one question: the same words, spacing and case aside."""
    return " ".join(one.lower().split()) == " ".join(other.lower().split())


@dataclass
class Answers:
    """
    The recorded answers of a log, handed out batch by batch, in order - each
    only for a question it fits (item 63): one the question offers, and, when
    an earlier install asked this component's question here, that question.
    After one does not fit, the batch's other recorded answers are not used:
    answers that shifted against a mod's changed prompts would go on wrong.
    """
    recorded: dict[Key, list[str]]
    asked_before: dict[Key, dict[int, str]] = field(default_factory=dict)
    _queue: deque = field(default_factory=deque)
    _batch: tuple[Key, ...] = ()
    refused: str | None = None        # why the last recorded answer was not given
    last: tuple[Key, int] | None = None   # the component and place of the one given

    def start(self, batch: tuple[Key, ...]) -> None:
        """A batch starts: its components' answers, in the batch's order."""
        self._batch = batch
        self._queue = deque((key, n, answer) for key in batch
                            for n, answer in enumerate(self.recorded.get(key, ())))

    def next(self, question: str = "") -> str | None:
        """The next recorded answer of the batch for `question`, None when there
        is none or it does not fit (then `refused` says why)."""
        self.refused = None
        if not self._queue:
            return None
        key, n, answer = self._queue[0]
        before = self.asked_before.get(key, {}).get(n)
        if question and before is not None and not same_question(before, question):
            self.refused = (f"{key[0]} #{key[1]} asked something else here when this answer "
                            f"was given ({before!r})")
        elif question and not fits(question, answer):
            self.refused = f"the recorded answer {answer!r} is not one this question offers"
        if self.refused:
            self._queue.clear()
            return None
        self._queue.popleft()
        self.last = (key, n)
        return str(answer)
