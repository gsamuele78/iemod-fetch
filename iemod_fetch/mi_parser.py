"""
mod_installer's parser config for one install (ADR-0057, GUI-AUDIT M8).

mod_installer 16.0.0 puts a line of WeiDU's output to the player only when
it looks like a question (src/config/parser_config.rs,
string_looks_like_question): a bell, a choice phrase or a choice word, and
no progress word. A question with none of them is never put to anyone and
WeiDU waits for its timeout (3 hours; measured: 11 of the 42 questions the
corpus can tell apart). Its parser config is a file it reads at start
(confy 2.0.0, `parser.toml`) and uses only when it carries its own version,
`metadata.mod_installer_version`; otherwise it writes its defaults over it.

What this module does, read from that source:
- the file is mod_installer's defaults plus, as choice phrases, a literal
  piece of the last line of each expected question it would not ask;
- mod_installer checks each line on its own, ASCII-lowercased and trimmed,
  with `contains`: a phrase is one line's literal text, ASCII-lowercased;
- a line with "installing" or "creating" is never a question, so no phrase
  helps there: such questions stay as they are (and are said, ADR-0049);
- the file lives in a folder of this install, never the player's own:
  mod_installer finds it through XDG_CONFIG_HOME (Linux and macOS, etcetera's
  Xdg strategy: <dir>/mod_installer/parser.toml) or APPDATA (Windows:
  <dir>/mod_installer/config/parser.toml), set only in its environment.
  WeiDU and what the mods run inherit that variable; HOME is left alone.
"""
from __future__ import annotations

import os
import sys
import time

from . import prompts
from .atomic import write_text

VERSION = "16.0.0"                 # the mod_installer the release carries
CONFIG_NAME = "parser"             # src/main.rs PARSER_CONFIG_LOCATION
APP = "mod_installer"              # its CARGO_PKG_NAME

# src/config/parser_config.rs, ParserConfig::default() in 16.0.0
IN_PROGRESS_WORDS = ("creating", "installing")
USEFUL_STATUS_WORDS = ("copied", "copying", "creating", "installed", "installing",
                       "patched", "patching", "processed", "processing")
COMPLETED_WITH_WARNINGS = ("installed with warnings",)
FAILED_WITH_ERROR = ("installation aborted", "not installed due to errors")
FINISHED = ("process ended", "successfully installed      ")
EET_AUTO_FILL = "Enter the full path to your BG:EE+SoD installation then press Enter."

_UPPER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _ascii_lower(text: str) -> str:
    """Rust's to_ascii_lowercase: only A-Z change."""
    return text.translate(_UPPER)


def phrase(text: str) -> str | None:
    """The choice phrase that makes mod_installer ask this expected question,
    or None: when it asks it already, when its last line has no literal
    piece of MIN_TEXT characters, or when that line has a progress word."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1]
    if prompts.mod_installer_asks(prompts._VARIABLE.sub(" ", last)):
        return None
    if any(word in _ascii_lower(last) for word in IN_PROGRESS_WORDS):
        return None
    pieces = [piece.strip() for piece in prompts._VARIABLE.split(last)]
    best = max(pieces, key=len)
    if len(best) < prompts.MIN_TEXT:
        return None
    return _ascii_lower(best)


def asked(text: str, added: list[str] | None = None) -> bool:
    """mod_installer puts this expected question to the player: one of its
    lines looks like a question to it (its %variables% left out: what WeiDU
    fills in is not known), or the phrase it needs is in its config -
    `added`, the phrases of the install; None: as start_install writes them."""
    lines = [prompts._VARIABLE.sub(" ", line) for line in text.splitlines() if line.strip()]
    if any(prompts.mod_installer_asks(line) for line in lines):
        return True
    needed = phrase(text)
    return needed is not None and (added is None or needed in added)


def phrases(expected: dict) -> list[str]:
    """The phrases for every expected question of the install, sorted, once
    each. `expected`: component -> [(question key, text)]."""
    found = {phrase(text) for questions in expected.values() for _key, text in questions}
    found.discard(None)
    return sorted(found)  # type: ignore[arg-type]


def _string(value: str) -> str:
    """A TOML basic string."""
    out = []
    for char in value:
        if char in '"\\':
            out.append("\\" + char)
        elif char < " " or char == "\x7f":
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _array(values) -> str:
    return "[" + ", ".join(_string(v) for v in sorted(set(values))) + "]"


def toml(extra: list[str], now: float | None = None) -> str:
    """mod_installer 16.0.0's defaults with `extra` choice phrases, as the
    TOML its confy reads (`created` is serde's SystemTime)."""
    created = time.time() if now is None else now
    secs = int(created)
    return "\n".join((
        f"in_progress_words = {_array(IN_PROGRESS_WORDS)}",
        f"useful_status_words = {_array(USEFUL_STATUS_WORDS)}",
        f"choice_words = {_array(prompts._CHOICE_WORDS)}",
        f"choice_phrase = {_array((*prompts._CHOICE_PHRASES, *extra))}",
        f"completed_with_warnings = {_array(COMPLETED_WITH_WARNINGS)}",
        f"failed_with_error = {_array(FAILED_WITH_ERROR)}",
        f"finished = {_array(FINISHED)}",
        f"eet_auto_fill = {_string(EET_AUTO_FILL)}",
        f"bell_character = {_string(chr(7))}",
        "",
        "[metadata]",
        f"mod_installer_version = {_string(VERSION)}",
        "",
        "[metadata.created]",
        f"secs_since_epoch = {secs}",
        f"nanos_since_epoch = {int((created - secs) * 1e9)}",
        "",
    ))


def config_path(root: str, platform: str = sys.platform) -> str:
    """Where mod_installer looks for its parser config under `root`."""
    if platform == "win32":
        return os.path.join(root, APP, "config", CONFIG_NAME + ".toml")
    return os.path.join(root, APP, CONFIG_NAME + ".toml")


def environment(root: str, platform: str = sys.platform) -> dict[str, str]:
    """What points mod_installer at `root` (an absolute folder)."""
    return {"APPDATA" if platform == "win32" else "XDG_CONFIG_HOME": os.path.abspath(root)}


def write(root: str, expected: dict, platform: str = sys.platform) -> tuple[dict[str, str], list[str]]:
    """Write the parser config of this install under `root`; the variables to
    add to mod_installer's environment and the phrases added."""
    extra = phrases(expected)
    path = config_path(root, platform)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text(path, toml(extra))
    return environment(root, platform), extra
