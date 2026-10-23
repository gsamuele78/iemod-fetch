#!/usr/bin/env python3
"""
Do the kinds and the places still hold on the live community data? (GUI-AUDIT
M5 item 29, ADR-0041.)

    python3 tools/places_check.py DATA_DIR [--log WeiDU.log] [--json OUT]

DATA_DIR is iemod-fetch's data cache (`--update-data` fills it: lcc-docs,
bws-ng, krion64). Exit 1, naming what moved, when:

- lcc-docs or BWS-NG uses a category `iemod_fetch/kinds.py` does not map - a
  new label would show raw and place nothing, so the table needs a line;
- BWS-NG's games/eet.json has no bg2ee sequence with the EET core in it -
  its shape moved, and decision 2a would silently place nothing.

Printed, and with --json written: the mods with a kind that krion64 does not
place, and how many the sequence, the kind, or nothing places; with --log, the
plan of that log without and with those places, and for each the pairs of
components it orders the other way round from BWS-NG's sequence - the
independent check ADR-0041 decision 5 asks for (a log written by the Forge
is krion64's own order, so it cannot be the judge).

Read-only; nothing is downloaded.
"""
import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.available import available_mods  # noqa: E402
from iemod_fetch.catalogues import CatalogueSet  # noqa: E402
from iemod_fetch.datasync import data_paths  # noqa: E402
from iemod_fetch.kinds import BWS_NG, LCC_DOCS, KindHint, _fold  # noqa: E402
from iemod_fetch.moddb import ModDatabase  # noqa: E402
from iemod_fetch.ordering import (EET_LOG, OrderIndex, bws_sequence,  # noqa: E402
                                  plan_order)


def unknown_labels(catalogue: CatalogueSet, database: ModDatabase | None) -> dict:
    """The categories each source uses that the kind tables do not map."""
    lcc = {_fold(label) for label in LCC_DOCS}
    bws = {_fold(code) for code in BWS_NG}
    return {
        "lcc-docs": sorted({c for cat in catalogue.catalogues for entries in cat.by_key.values()
                            for entry in entries for c in entry.categories
                            if _fold(c) not in lcc}),
        "BWS-NG": sorted({c for record in (database.records.values() if database else ())
                          for c in record.categories if _fold(c) not in bws}),
    }


def hints(catalogue: CatalogueSet, database: ModDatabase | None) -> dict[str, KindHint]:
    return {mod.key: KindHint(mod.kinds, mod.games, tuple(mod.kinds_by_source))
            for mod in available_mods(None, catalogue, database) if mod.kinds}


def places(index: OrderIndex, kinds: dict, sequence: list) -> dict:
    """Every mod with a kind krion64 does not place, as one EET install: what
    the sequence places, what the kind places, what nothing places."""
    unplaced = sorted(key for key in kinds if index.get(key) is None)
    with tempfile.TemporaryDirectory() as work:
        log = os.path.join(work, EET_LOG)
        with open(log, "w", encoding="utf-8") as fh:
            fh.write("~EET\\EET.tp2~ #0 #0 // EET\n")
            fh.writelines(f"~{key}\\{key}.tp2~ #0 #0 // {key}\n" for key in unplaced)
        plan = plan_order([(log, EET_LOG)], index, kinds=kinds, sequence=sequence)
    return {"with a kind, krion64 does not place": len(unplaced),
            "by BWS-NG's sequence": len(plan.by_sequence),
            "by kind": len(plan.by_kind),
            "no place": len(plan.no_place)}


def inversions(order: list[tuple[str, int]], sequence: list[tuple[str, int]]) -> tuple:
    """(pairs ordered the other way round from the sequence, pairs compared)."""
    at: dict[tuple[str, int], int] = {}
    for n, entry in enumerate(sequence):
        at.setdefault(entry, n)
    known = [at[c] for c in order if c in at]
    wrong = sum(1 for i, a in enumerate(known) for b in known[i + 1:] if a > b)
    return wrong, len(known) * (len(known) - 1) // 2


def log_check(log: str, index: OrderIndex, kinds: dict, sequence: list) -> dict:
    out = {}
    for name, extra in (("without", {}), ("with", {"kinds": kinds, "sequence": sequence})):
        plan = plan_order([(log, EET_LOG)], index, **extra)
        order = [(unit.key, number) for unit in plan.logs.get(EET_LOG, ())
                 for _p, _l, number, _c in unit.lines]
        wrong, pairs = inversions(order, sequence)
        out[name] = {"components": len(order), "pairs against BWS-NG": pairs,
                     "the other way round": wrong,
                     "placed": len(plan.by_sequence) + len(plan.by_kind)}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data_dir")
    parser.add_argument("--log", help="a WeiDU.log to plan (its EET install)")
    parser.add_argument("--json", help="write the result here")
    args = parser.parse_args(argv)

    paths = data_paths(args.data_dir)
    if not (paths.catalogue and paths.mod_db and paths.order_catalogue and paths.eet_sequence):
        print(f"{args.data_dir}: the data cache lacks lcc-docs, BWS-NG or krion64",
              file=sys.stderr)
        return 1
    catalogue = CatalogueSet.load([paths.catalogue])
    database = ModDatabase.load(paths.mod_db)
    index = OrderIndex.load(paths.order_catalogue)
    with open(paths.eet_sequence, encoding="utf-8") as fh:
        sequence = bws_sequence(json.load(fh))
    kinds = hints(catalogue, database)

    result = {"unknown labels": unknown_labels(catalogue, database),
              "sequence entries": len(sequence),
              "places": places(index, kinds, sequence)}
    if args.log:
        result["log"] = log_check(args.log, index, kinds, sequence)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)

    problems = [f"{source} uses categories kinds.py does not map: {', '.join(labels)}"
                for source, labels in result["unknown labels"].items() if labels]
    if ("eet", 0) not in sequence:
        problems.append("BWS-NG's games/eet.json has no bg2ee sequence with eet:0 - "
                        "its shape moved")
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
