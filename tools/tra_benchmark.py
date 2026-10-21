#!/usr/bin/env python3
"""
Measure iemod_fetch.tra against WeiDU's own --list-components.

    python3 tools/tra_benchmark.py ORACLE.json [--show N] [--min PERCENT]

ORACLE.json is a list of {"game", "tp2", "lang", "components": [[n, text]]},
each produced by `weidu --nogame --list-components TP2 LANG` run in "game"
(tools/tra_oracle.py writes it; docs/TESTING.md). Prints exact-match accuracy
and the first mismatches; with --min, exits 1 below that accuracy.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.tra import component_names  # noqa: E402


def reader(game: str):
    cache = {}

    def find(path: str):
        """Case-insensitive, as on Windows, relative to the game directory."""
        current = game
        for part in path.replace("\\", "/").split("/"):
            if part in ("", "."):
                continue
            try:
                names = cache.setdefault(current, os.listdir(current))
            except OSError:
                return None
            hit = next((n for n in names if n.lower() == part.lower()), None)
            if hit is None:
                return None
            current = os.path.join(current, hit)
        return current if os.path.isfile(current) else None

    def read(path: str):
        found = find(path)
        if found is None:
            return None
        with open(found, "rb") as fh:
            return fh.read().decode("latin-1")   # byte-exact, as WeiDU prints
    return read, find


def main(argv) -> int:
    with open(argv[1], encoding="utf-8") as fh:
        oracle = json.load(fh)
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 15
    floor = float(argv[argv.index("--min") + 1]) if "--min" in argv else 0.0
    total = exact = missing = 0
    misses = []
    for run in oracle:
        if not run["components"]:
            continue
        read, find = reader(run["game"])
        tp2_path = find(run["tp2"])
        with open(tp2_path, "rb") as fh:
            tp2 = fh.read().decode("latin-1")
        predicted = {c.number: c.name for c in component_names(
            tp2, run["lang"], read, weidu_os="unix")}   # the oracle ran on Linux
        for number, text in run["components"]:
            total += 1
            got = predicted.get(number)
            if got is None:
                missing += 1
                misses.append((run["tp2"], run["lang"], number, text, None))
            elif got == text:
                exact += 1
            else:
                misses.append((run["tp2"], run["lang"], number, text, got))
    accuracy = 100 * exact / total if total else 0.0
    print(f"{exact}/{total} exact ({accuracy:.2f}%), {missing} components not found")
    for miss in misses[:show]:
        print("  ", miss)
    return 0 if accuracy >= floor else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
