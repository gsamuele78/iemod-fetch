#!/usr/bin/env python3
"""
How well krion64's component lists stand in for a mod not downloaded yet
(ADR-0035): its records against WeiDU's own --list-components.

    python3 tools/krion_components_benchmark.py ORACLE.json KRION_MODS_DIR

ORACLE.json is tools/tra_oracle.py's output (language 0 is used);
KRION_MODS_DIR is krion64's data/mods. Prints, over the mods both know: the
components WeiDU lists, how many krion64 has under the same number, those only
WeiDU has, those only krion64 has, and the mods whose lists are identical.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.choices import from_krion  # noqa: E402
from iemod_fetch.ordering import tp2_key  # noqa: E402


def main(argv) -> int:
    oracle_path, krion_dir = argv[1:3]
    with open(oracle_path, encoding="utf-8") as fh:
        oracle = json.load(fh)
    records = []
    for name in sorted(os.listdir(krion_dir)):
        if name.endswith(".json"):
            with open(os.path.join(krion_dir, name), encoding="utf-8") as fh:
                records.append(json.load(fh))
    krion: dict = {}
    for tp2s in from_krion(records).values():
        for tp2 in tp2s:              # one tp2 can be listed under several records
            krion.setdefault(tp2_key(tp2.tp2), set()).update(
                c.number for c in tp2.components)
    total = collections.Counter()
    for entry in oracle:
        if entry.get("lang") != 0:
            continue
        weidu = {number for number, _text in entry["components"]}
        known = krion.get(tp2_key(entry["tp2"]))
        if known is None:
            total["mods without a krion64 record"] += 1
            continue
        total["mods"] += 1
        total["components WeiDU lists"] += len(weidu)
        total["also in krion64"] += len(weidu & known)
        total["only WeiDU"] += len(weidu - known)
        total["only krion64"] += len(known - weidu)
        total["identical mods"] += weidu == known
    for key, value in total.items():
        print(f"{key:32} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
