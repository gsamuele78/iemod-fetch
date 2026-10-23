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

A label is looked up ignoring case and Unicode composition (`Quête` typed
either way). One this table does not know is kept as it is, so a source that
adds a category shows it rather than losing it - and, not being a kind, it
never makes a disagreement (review of #65).
"""
from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping

# The kinds, in the order a mod's own kinds are listed (the selection's left
# list is alphabetical).
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


# What the player reads for a source, by the name it was loaded under: the
# data cache's folders (datasync) and BWS-NG's repository name.
SOURCE_NAMES = {"lcc-docs": "lcc-docs", "bws-ng": "BWS-NG",
                "bigworldsetup-next-generation": "BWS-NG", "krion64": "krion64"}


def _fold(label: str) -> str:
    return unicodedata.normalize("NFC", label).strip().casefold()


def source_name(origin: str) -> str:
    """`bws-ng` is BWS-NG; a source this tool does not know keeps its own name."""
    return SOURCE_NAMES.get(_fold(origin), origin)


def kinds(labels: Iterable[str], table: Mapping[str, str]) -> tuple[str, ...]:
    """A source's labels as kinds, in KINDS' order; an unknown label kept as is."""
    folded = {_fold(label): kind for label, kind in table.items()}
    found = dict.fromkeys(folded.get(_fold(label), label) for label in labels if label)
    order = {kind: i for i, kind in enumerate(KINDS)}
    return tuple(sorted(found, key=lambda kind: (order.get(kind, len(KINDS)), kind)))


def disagree(a: Iterable[str], b: Iterable[str]) -> bool:
    """Two sources that both classify a mod, with no kind in common. A label
    no table knows is not a kind: it cannot disagree."""
    a, b = set(a) & set(KINDS), set(b) & set(KINDS)
    return bool(a and b and not a & b)
