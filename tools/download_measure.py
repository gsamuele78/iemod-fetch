"""
How well each download source does on a real selection (ADR-0039), from the
JSON reports of real runs - the measurement the development sandbox could not
make (its proxy refuses third-party repositories).

    python tools/download_measure.py dry-catalogue.json [dry-manifest.json]
        [--real real.json] [--pick N]

Prints a Markdown summary: per run, the mods with a downloadable candidate
(planned/ok), with none (manual) and failed, by the candidate's origin, and
each miss with its reason. `--pick N` prints instead, one per line, N planned
mods of the first report to try for real (deterministic: sorted by folder).
"""
import argparse
import collections
import json
import sys


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def summary(title, report):
    records = report.get("records") or []
    unresolved = report.get("unresolved") or []
    # over the run's --max-bytes: the measurement's own cap, not a defect
    by_status = collections.Counter(
        "over the size cap" if "byte ceiling" in str(r.get("detail") or "") else r["status"]
        for r in records)
    by_status["manual"] += len(unresolved)
    by_origin = collections.Counter(r.get("origin") or "-" for r in records
                                    if r["status"] in ("planned", "ok", "skipped"))
    lines = [f"### {title}", "",
             f"{len(records) + len(unresolved)} mods: " + ", ".join(
                 f"{n} {status}" for status, n in sorted(by_status.items()) if n), ""]
    if by_origin:
        lines += ["| candidate origin | mods |", "|---|---|"]
        lines += [f"| {origin} | {n} |" for origin, n in by_origin.most_common()]
        lines.append("")
    misses = [r for r in records if r["status"] not in ("planned", "ok", "skipped")]
    misses += [{"folder": u["folder"], "status": "manual", "detail": u["detail"]}
               for u in unresolved]
    if misses:
        lines += ["<details><summary>misses</summary>", "",
                  "| mod | status | why |", "|---|---|---|"]
        for record in sorted(misses, key=lambda r: r["folder"].lower()):
            why = " ".join(str(record.get("detail") or "").split())[:300]
            lines.append(f"| {record['folder']} | {record['status']} | "
                         f"{why.replace('|', '/')} |")
        lines += ["", "</details>", ""]
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--real")
    parser.add_argument("--pick", type=int)
    args = parser.parse_args(argv)
    first = load(args.reports[0])
    if args.pick:
        planned = sorted(r["folder"] for r in first.get("records") or []
                         if r["status"] == "planned")
        print("\n".join(planned[:args.pick]))
        return 0
    titles = ["Catalogue only (no manifest, dry run)", "With the manifest (dry run)"]
    out = ["## Download sources, measured", ""]
    for title, path in zip(titles, args.reports, strict=False):
        out += summary(title, load(path))
    if args.real:
        out += summary("Real download of a sample (archive must hold the tp2)",
                       load(args.real))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
