"""
decisions.json: the player's answers to the conflict report (M2).

The conflict report lists, for every finding, the ways to clear it - each an
option with a stable id (conflicts.Option). Where the rules decide,
`--resolve-conflicts` applies their choice; where they do not (a tie, a warning,
a whole mod against a whole mod) it is the player's. This file is where that
choice is written down, by a GUI or by hand, so the next run applies it:

    {"schema_version": 1,
     "decisions": [
       {"finding": "conflict-1887f4d4f9f06816", "choose": "option-0c1d..."},
       {"finding": "conflict-d8821540fb81dfcd", "accept": "tested, works for me"}]}

`choose` applies that option to the plan; `accept` keeps both sides and marks
the finding as accepted, with the reason, instead of outstanding. Ids are
stable while the selection is the same; a decision whose finding no longer
exists is reported as stale and otherwise ignored - never applied to
something else.
"""
import json
from dataclasses import dataclass, field

from .contract import SCHEMA_VERSION
from .errors import ConfigError

_TOP = {"schema_version", "decisions"}
_ENTRY = {"finding", "choose", "accept"}


@dataclass
class Decisions:
    choose: dict[str, str] = field(default_factory=dict)    # finding id -> option id
    accept: dict[str, str] = field(default_factory=dict)    # finding id -> why

    def __len__(self) -> int:
        return len(self.choose) + len(self.accept)

    @property
    def findings(self) -> set:
        return set(self.choose) | set(self.accept)


def parse_decisions(text: str, source: str = "decisions.json") -> Decisions:
    """Read and validate; ConfigError names where and why."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"{source}: not valid JSON ({exc})") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: expected an object")
    unknown = set(data) - _TOP
    if unknown:
        raise ConfigError(f"{source}: unknown key(s) {sorted(unknown)}")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"{source}: schema_version {data.get('schema_version')!r} "
                          f"is not supported; this version reads {SCHEMA_VERSION}")
    entries = data.get("decisions")
    if not isinstance(entries, list):
        raise ConfigError(f"{source}: 'decisions' must be an array")
    out = Decisions()
    for n, entry in enumerate(entries):
        where = f"{source}: decisions[{n}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: expected an object")
        unknown = set(entry) - _ENTRY
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}")
        finding = entry.get("finding")
        if not isinstance(finding, str) or not finding.startswith("conflict-"):
            raise ConfigError(f"{where}: 'finding' must be a conflict id (conflict-...)")
        if finding in out.findings:
            raise ConfigError(f"{where}: {finding} is decided twice")
        has_choice, has_accept = "choose" in entry, "accept" in entry
        if has_choice == has_accept:
            raise ConfigError(f"{where}: give exactly one of 'choose' or 'accept'")
        if has_choice:
            option = entry["choose"]
            if not isinstance(option, str) or not option.startswith("option-"):
                raise ConfigError(f"{where}: 'choose' must be an option id (option-...)")
            out.choose[finding] = option
        else:
            why = entry["accept"]
            if not isinstance(why, str) or not why.strip():
                raise ConfigError(f"{where}: 'accept' must say why, as a non-empty string")
            out.accept[finding] = why.strip()
    return out


def decisions_to_json(decisions: Decisions) -> str:
    entries = ([{"finding": f, "choose": o} for f, o in sorted(decisions.choose.items())]
               + [{"finding": f, "accept": w} for f, w in sorted(decisions.accept.items())])
    return json.dumps({"schema_version": SCHEMA_VERSION, "decisions": entries},
                      indent=2) + "\n"
