"""
The download-sources measurement, from a player's own computer (GUI-AUDIT M7
item 57). The download-sources workflow runs it from GitHub's runners, where
Gibberlings3, SHS and Nexus answer every request with Cloudflare's 403; from a
home connection they usually do not, and that is what is left to measure.

    python tools/measure_workstation.py [--log tests/data/WeiDU.log]
        [--real all|N] [--max-bytes BYTES] [--out DIR]

Runs, each step's output kept in DIR (default: measure-<date> here):
the community data, a dry run with the catalogue alone and one with the
manifest, a real download of the planned mods (`--real`, default all; each
over --max-bytes, default 300 MB, is counted, not fetched), premeta's live
check, and what the Gibberlings3 and SHS pages give. Then DIR/summary.md: the
same tables the workflow writes, to be pasted back. A GitHub token makes the
GitHub part work at 5,000 requests an hour instead of 60: `gh auth login`, or
GH_TOKEN set. Nothing is installed into a game; the mods land in DIR/mods.
"""
import argparse
import datetime as dt
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from iemod_fetch.atomic import write_text  # noqa: E402

# The pages the runners cannot read (download-sources workflow, 2026-10-23).
CLOUDFLARED = (
    "https://www.gibberlings3.net/files/file/702-a-mod-for-the-orderly/",
    "https://www.gibberlings3.net/mods/quests/cliffette",
    "https://www.shsforums.net/topic/57927-mod-the-picture-standard-for-bgee-1-2/",
)
MEGABYTE = 1024 * 1024


def step(title, argv, log):
    """Run one step; its output goes to the log, its exit code is only noted."""
    print(f"-- {title}", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        out.write(f"\n## {title}\n$ {' '.join(argv)}\n")
        out.flush()
        done = subprocess.run(argv, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                              check=False)
        out.write(f"(exit {done.returncode})\n")
    return done.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--log", default=os.path.join("tests", "data", "WeiDU.log"),
                        help="the WeiDU.log whose mods are measured")
    parser.add_argument("--manifest", default=os.path.join("tests", "data",
                                                           "mod_downloads.json"))
    parser.add_argument("--real", default="all", metavar="all|N",
                        help="how many planned mods to download for real")
    parser.add_argument("--max-bytes", type=int, default=300 * MEGABYTE)
    parser.add_argument("--out", default=f"measure-{dt.date.today():%Y-%m-%d}")
    args = parser.parse_args(argv)
    if args.real != "all" and not args.real.isdigit():
        parser.error("--real is a number or 'all'")

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, "steps.log")
    py = sys.executable
    tool = [py, "-m", "iemod_fetch", "--no-update-data", "-q"]
    dry = os.path.join(out, "dry-catalogue.json")
    real = os.path.join(out, "real.json")

    step("community data", [py, "-m", "iemod_fetch", "--update-data"], log)
    step("dry run, catalogue only", [*tool, "-w", args.log, "-m", "", "--dry-run",
                                     "--no-discovery", "-t", os.path.join(out, "mods-a"),
                                     "--json-report", dry], log)
    step("dry run, with the manifest",
         [*tool, "-w", args.log, "-m", args.manifest, "--dry-run", "--no-discovery",
          "-t", os.path.join(out, "mods-b"),
          "--json-report", os.path.join(out, "dry-manifest.json")], log)
    picks = subprocess.run(
        [py, os.path.join("tools", "download_measure.py"), dry, "--pick", args.real],
        cwd=ROOT, capture_output=True, text=True, check=False).stdout.split()
    if picks:
        only = [a for folder in picks for a in ("--only", folder)]
        step(f"real download of {len(picks)} mods",
             [*tool, "-w", args.log, "-m", "", "--no-discovery", *only,
              "-t", os.path.join(out, "mods"), "--max-bytes", str(args.max_bytes),
              "--json-report", real], log)
    step("premeta live check", [py, os.path.join("tools", "premeta_live_check.py")], log)
    step("the pages GitHub's runners cannot read",
         [py, os.path.join("tools", "landing_probe.py"), *CLOUDFLARED], log)

    summary = subprocess.run(
        [py, os.path.join("tools", "download_measure.py"), dry,
         os.path.join(out, "dry-manifest.json"),
         *(["--real", real] if os.path.exists(real) else [])],
        cwd=ROOT, capture_output=True, text=True, check=False).stdout
    write_text(os.path.join(out, "summary.md"), summary)
    print(summary)
    print(f"Everything is in {out}: summary.md to paste back, steps.log for the detail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
