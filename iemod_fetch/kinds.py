"""
A mod's kind, as each source says it (GUI-AUDIT M5 item 26, ADR-0041).

lcc-docs and BWS-NG classify mods in the same taxonomy - BWS-NG's is lcc-docs'
(ADR-0041) - spelled two ways: lcc-docs' French labels (`Quête`, `PNJ
recrutable`, `Sort et objet`, measured on its db/mods.json, 2026-10-23: 17
labels) and BWS-NG's codes (`quest`, `npc`, `spell`: 15). Both are mapped here
onto one vocabulary, so the selection can filter on one kind and show where
the two sources disagree. krion64 (the Infinity Mod Forge) does not classify
by kind but by install category (`QUEST MODS BG2`, `KIT & CLASS MODS`...):
that is shown beside, never mapped into a kind - how decisive each kind is
for an install place is ADR-0041's table, item 27's business.

A label this table does not know is kept as it is, so a source that adds a
category shows it rather than losing it.
"""
from __future__ import annotations

from collections.abc import Iterable

# The kinds, in the order the selection lists them.
KINDS = ("interface", "cosmetic", "portraits and sound", "quest", "recruitable NPC",
         "one-day NPC", "NPC (other)", "kit", "spells and items", "smith and merchant",
         "gameplay", "tactics and scripts", "unofficial patch", "utility", "conversion",
         "party customisation", "GemRB")

LCC_DOCS = {
    "Interface": "interface", "Cosmétique": "cosmetic", "Portrait et son": "portraits and sound",
    "Quête": "quest", "PNJ recrutable": "recruitable NPC", "PNJ One Day": "one-day NPC",
    "PNJ (autre)": "NPC (other)", "Kit": "kit", "Sort et objet": "spells and items",
    "Forgeron et marchand": "smith and merchant", "Gameplay": "gameplay",
    "Script et tactique": "tactics and scripts", "Patch non officiel": "unofficial patch",
    "Utilitaire": "utility", "Conversion": "conversion",
    "Personnalisation du groupe": "party customisation", "GemRB": "GemRB",
}

BWS_NG = {
    "ui": "interface", "cosm": "cosmetic", "portrait": "portraits and sound",
    "quest": "quest", "npc": "recruitable NPC", "npc1d": "one-day NPC",
    "npcx": "NPC (other)", "kit": "kit", "spell": "spells and items", "smith": "smith and merchant",
    "gameplay": "gameplay", "tactic": "tactics and scripts", "patch": "unofficial patch",
    "util": "utility", "conv": "conversion",
}


def kinds(labels: Iterable[str], table: dict[str, str]) -> tuple[str, ...]:
    """A source's labels as kinds, in KINDS' order; an unknown label kept as is."""
    found = dict.fromkeys(table.get(label, label) for label in labels if label)
    order = {kind: i for i, kind in enumerate(KINDS)}
    return tuple(sorted(found, key=lambda kind: (order.get(kind, len(KINDS)), kind)))


def disagree(a: Iterable[str], b: Iterable[str]) -> bool:
    """Two sources that both classify a mod, with no kind in common."""
    a, b = set(a), set(b)
    return bool(a and b and not a & b)
