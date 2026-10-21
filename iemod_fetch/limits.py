"""
Engine limits a big install can run out of (ADR-0034).

Three tables of the Enhanced Edition engine fill up as mods add to them, and
past the end a mod fails to install or the game misbehaves:

* **kits** - WeiDU's ADD_KIT refuses a kit number above 256 on every EE game
  ("The game requires ToBEx or GemRB to support more than 256 kits",
  WeiDU src/tpaction.ml). BG2:EE's own KITLIST.2DA holds 40 kits (IESDP).
* **spell states** - SPLSTATE.IDS ids run 0-255 without EEex (EEex's
  EEex_Stats_Patch.lua: "the vanilla range of [0-255]"); about 133 are taken
  by the game (IESDP's BG:EE list), leaving 123.
* **spell slots** - WeiDU's ADD_SPELL gives wizard and priest spells 50 ids
  per level (src/tph/define/add_spell.tpa, `tb#max_spell = 50`). What the
  engine does past that is not documented by a primary source.

Infinity Mod Forge warns on the same three with other numbers (320 kits, 128
spell states taken); those are reported beside ours, not used. What each
component adds comes from krion64's records (`k`, `ss`, `spLv`/`sp`) - and
only for components krion64 has measured, so every total says how much of the
selection it could see. Its spell-state counts include ids a mod only reads,
so that table is shown, never warned on. No game version is assumed: nothing here differs
between patch 2.5, 2.6 and 2.7 in any source found, and nothing is blocked -
these are warnings. Measured from an installed game, the base values replace
these (M4).
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .naming import normalize_key

WARN_SHARE = 0.9          # warn when 90% of a table is used


@dataclass(frozen=True)
class Limit:
    key: str
    label: str
    cap: int
    base: int
    source: str
    forge_cap: Optional[int] = None     # what Infinity Mod Forge uses, if different
    forge_base: Optional[int] = None


KITS = Limit("kits", "kits (KITLIST.2DA)", 256, 40,
             "WeiDU ADD_KIT refuses kit number > 256 on EE games (src/tpaction.ml); "
             "BG2:EE ships 40 kits (IESDP kitlist)", forge_cap=320, forge_base=37)
SPELL_STATES = Limit("spell_states", "spell states (SPLSTATE.IDS)", 256, 133,
                     "ids 0-255 without EEex (EEex_Stats_Patch.lua); ~133 used by the "
                     "game (IESDP splstate)", forge_base=128)
SPELL_SLOTS = 50          # per type and level: WeiDU add_spell.tpa
# The game's own spells per level, as Infinity Mod Forge counts them
# (VANILLA_SPELLS); w = wizard, p = priest. Not checked against a primary source.
GAME_SPELLS = {"w1": 22, "w2": 21, "w3": 21, "w4": 24, "w5": 18, "w6": 20, "w7": 20,
               "w8": 12, "w9": 18, "p1": 13, "p2": 14, "p3": 16, "p4": 17, "p5": 16,
               "p6": 14, "p7": 20}


@dataclass
class Tally:
    """One table: what the game takes, what the selection adds, and who adds it."""
    label: str
    cap: int
    base: int
    added: int = 0
    by: List[Tuple[str, int, int]] = field(default_factory=list)   # (mod, component, n)
    source: str = ""
    note: str = ""
    checked: bool = True        # False: the counts are not reliable enough to warn on

    @property
    def total(self) -> int:
        return self.base + self.added

    @property
    def severity(self) -> Optional[str]:
        if not self.checked:
            return None
        if self.total > self.cap:
            return "error"
        if self.total >= self.cap * WARN_SHARE:
            return "warning"
        return None

    def as_dict(self) -> dict:
        return {"label": self.label, "cap": self.cap, "base": self.base,
                "added": self.added, "total": self.total, "severity": self.severity,
                "source": self.source, "note": self.note, "checked": self.checked,
                "added_by": [{"mod": m, "component": c, "count": n} for m, c, n in self.by]}


@dataclass
class LimitsReport:
    install: str
    tallies: List[Tally] = field(default_factory=list)
    components: int = 0           # chosen components
    unknown_mods: List[str] = field(default_factory=list)   # mods krion64 has no record of
    eeex: bool = False
    unlevelled_spells: int = 0    # krion64 counts them but not by level: not checked

    def as_dict(self) -> dict:
        return {"install": self.install, "components": self.components,
                "mods_without_data": list(self.unknown_mods), "eeex": self.eeex,
                "spells_of_unknown_level": self.unlevelled_spells,
                "tables": [t.as_dict() for t in self.tallies]}

    def render(self) -> str:
        lines = [f"  [{self.install}] engine limits"
                 + (f" - {len(self.unknown_mods)} mod(s) krion64 has no counts for, so "
                    f"these are at least: {', '.join(self.unknown_mods[:6])}"
                    + (" ..." if len(self.unknown_mods) > 6 else "")
                    if self.unknown_mods else "")]
        for tally in self.tallies:
            mark = {"error": "!!", "warning": " !"}.get(tally.severity or "",
                                                        "  " if tally.checked else " ?")
            lines.append(f"    {mark} {tally.label}: {tally.total}/{tally.cap} "
                         f"({tally.base} the game's, {tally.added} from mods)"
                         + (f" - {tally.note}" if tally.note else ""))
            for mod, number, count in sorted(tally.by, key=lambda b: -b[2])[:3]:
                lines.append(f"         {count:>3} {mod} #{number}")
        if self.unlevelled_spells:
            lines.append(f"       + {self.unlevelled_spells} new spell(s) whose level krion64 "
                         f"does not record: not counted against a level")
        return "\n".join(lines)


def _index(records: Iterable[dict]) -> Dict[str, Dict[int, dict]]:
    """krion64 records -> tp2 key -> component number -> component."""
    out: Dict[str, Dict[int, dict]] = {}
    for record in records:
        components = {}
        for position, component in enumerate(record.get("co") or []):
            number = component.get("wc", component.get("cn"))
            if isinstance(number, int):
                entry = dict(component)
                if position == 0 and record.get("ss") and not entry.get("ss"):
                    entry["ss"] = record["ss"]     # Mod Forge's mod-level spell states
                components[number] = entry
        for name in {record.get("t"), *(c.get("wf") for c in record.get("co") or [])}:
            if isinstance(name, str) and name:
                components_for = out.setdefault(normalize_key(name), {})
                components_for.update(components)
    return out


def engine_limits(install: str, chosen: Sequence[Tuple[str, int]],
                  records: Iterable[dict], eeex: bool = False) -> LimitsReport:
    """
    The three tables for one install. `chosen` is (tp2 key, component number)
    in install order; `records` krion64's per-mod records.
    """
    index = _index(records)
    report = LimitsReport(install, components=len(chosen), eeex=eeex)
    kits = Tally(KITS.label, KITS.cap, KITS.base, source=KITS.source,
                 note=f"Infinity Mod Forge says {KITS.forge_cap}; WeiDU stops at {KITS.cap}")
    # krion64's `ss` counts a mod's SPLSTATE.IDS references, not only the ids it
    # adds: EE Fixpack is counted 19, and only looks existing ones up
    # (IDS_OF_SYMBOL). Summed, the user's real 148-mod EET install comes to
    # 257/256 - and it plays. So this table is shown, never warned on, until it
    # is measured from the game itself.
    states = Tally(SPELL_STATES.label, SPELL_STATES.cap, SPELL_STATES.base,
                   source=SPELL_STATES.source, checked=False,
                   note=("EEex is installed: its extended states lift this" if eeex else
                         "krion64 counts references, not only new ids - an upper "
                         "bound, not checked"))
    levels: Dict[str, Tally] = {
        level: Tally(f"{'wizard' if level[0] == 'w' else 'priest'} level {level[1]} spells "
                     f"(SPELL.IDS)", SPELL_SLOTS, base,
                     source="WeiDU ADD_SPELL: 50 per level (add_spell.tpa); the game's "
                            "count from Infinity Mod Forge")
        for level, base in GAME_SPELLS.items()}
    unlevelled = 0
    unknown = set()
    for key, number in chosen:
        components = index.get(key)
        if components is None:
            unknown.add(key)
            continue
        component = components.get(number)
        if not component:
            continue
        _add(kits, key, number, component.get("k"))
        _add(states, key, number, component.get("ss"))
        per_level: Mapping = component.get("spLv") or {}
        if isinstance(per_level, dict) and per_level:
            for level, count in per_level.items():
                if level in levels:
                    _add(levels[level], key, number, count)
        elif isinstance(component.get("sp"), int) and component["sp"] > 0:
            unlevelled += component["sp"]
    report.unknown_mods = sorted(unknown)
    if eeex:
        states.cap = 2 ** 32 - 1
    report.tallies = [kits, states] + [t for t in levels.values() if t.added or t.severity]
    report.unlevelled_spells = unlevelled
    return report


def _add(tally: Tally, key: str, number: int, count) -> None:
    if isinstance(count, int) and not isinstance(count, bool) and count > 0:
        tally.added += count
        tally.by.append((key, number, count))
