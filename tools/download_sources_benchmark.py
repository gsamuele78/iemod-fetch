#!/usr/bin/env python3
"""
Where a mod is downloaded from: lcc-docs' URLs against krion64's (ADR-0036).

    python3 tools/download_sources_benchmark.py LCC_MODS_JSON KRION_DATA_DIR \
        [--bws BWS_NG_MODS_DIR] [--probe]

LCC_MODS_JSON is lcc-docs' db/mods.json; KRION_DATA_DIR is krion64's data/
(its mods/*.json are read; an unreadable record is skipped and counted). Counts, over the mods for an Enhanced
Edition game (BGEE, SoD, BG2EE, EET; hidden and absorbed mods left out): the
mods each source knows, those with a GitHub repository or a direct archive, and
over the mods both know whether they name the same repository.

With --probe, every repository the two name differently is asked for with
`git ls-remote` (no API, no token): gone, the same repository under two names
(same HEAD: a rename GitHub redirects), or two different live repositories,
whose last commit dates are then compared with a blob-less depth-1 clone into
a temporary directory. A newer last commit is evidence, not proof: a bulk
migration commit is newer too.

With --bws, BigWorldSetup-NG's data/mods is measured too: its mods, those with
an exact file (and a sha256), whether the version it pins is krion64's latest
scanned release, and - with --probe - whether each GitHub release tag it pins
still exists.
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.catalogues import SupplementaryCatalogue  # noqa: E402
from iemod_fetch.naming import normalize_key  # noqa: E402
from iemod_fetch.urls import repo_from_url  # noqa: E402

EE = {"BGEE", "SOD", "BG2EE", "EET"}
GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")


def lcc_mods(path):
    with open(path, encoding="utf-8") as fh:
        catalogue = SupplementaryCatalogue.from_entries(json.load(fh), "lcc-docs")
    out = {}
    for key, entries in catalogue.by_key.items():
        for entry in entries:
            if ({g.upper() for g in entry.games} & EE and "hidden" not in entry.status
                    and entry.embedded_in is None):
                out.setdefault(key, entry)
    return out


def krion_mods(data):
    out = {}
    mods = os.path.join(data, "mods")
    for name in sorted(os.listdir(mods)):
        if name.endswith(".json"):
            try:
                with open(os.path.join(mods, name), encoding="utf-8-sig") as fh:
                    record = json.load(fh)
            except (OSError, ValueError):
                out.setdefault(None, 0)
                out[None] += 1
                continue
            if isinstance(record, dict) and isinstance(record.get("t"), str):
                out.setdefault(normalize_key(record["t"]), record)
    return out


def krion_repo(record):
    # `gh` is checked as a URL would be: one record has "...Lanthornhttps:" as
    # its repository name while its URLs name the live repository.
    gh = record.get("gh")
    urls = [record.get("dl"), record.get("u")]
    if isinstance(gh, dict) and isinstance(gh.get("o"), str) and isinstance(gh.get("r"), str):
        urls.insert(0, f"https://github.com/{gh['o']}/{gh['r']}")
    for url in urls:
        repo = repo_from_url(url) if isinstance(url, str) else None
        if repo:
            return repo.lower()
    return None


def bws_mods(directory):
    out = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8-sig") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            continue
        if (isinstance(record, dict) and isinstance(record.get("tp2"), str)
                and {str(g).lower() for g in record.get("games") or []}
                & {g.lower() for g in EE}):
            out.setdefault(normalize_key(record["tp2"]), record)
    return out


RELEASE_ASSET = re.compile(r"https://github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/")


def _version(text):
    return re.sub(r"^v(ersion)?[-_ ]?", "", str(text or "").strip().lower())


def bws_report(bws, releases_path, probe_tags):
    files = [(r.get("files") or [{}])[0] for r in bws.values()]
    print(f"BWS-NG: mods {len(bws)}, with an exact file {sum(bool(f.get('download')) for f in files)}"
          f", with a sha256 {sum(any(isinstance(f, dict) and f.get('sha256') for f in r.get('files') or []) for r in bws.values())}")
    with open(releases_path, encoding="utf-8") as fh:
        releases = {k.lower(): v for k, v in json.load(fh).items() if isinstance(v, dict)}
    tally, pinned = collections.Counter(), []
    for record, first in zip(bws.values(), files):
        match = RELEASE_ASSET.match(first.get("download") or "")
        repo = (match.group(1) if match else
                repo_from_url((record.get("links") or {}).get("homepage") or ""))
        if match:
            pinned.append((match.group(1), urllib.parse.unquote(match.group(2))))
        latest = releases.get((repo or "").lower(), {}).get("tag")
        if not latest:
            tally["no scanned release"] += 1
        else:
            tally["latest release" if _version(latest) == _version(record.get("version"))
                  else "not the latest release"] += 1
    print("  pinned version against krion64's scanned release: "
          + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    if probe_tags:
        def tag(item):
            repo, name = item
            done = subprocess.run(["git", "ls-remote", "--tags", f"https://github.com/{repo}",
                                   f"refs/tags/{name}"], capture_output=True, text=True,
                                  timeout=120, env=GIT_ENV, check=False)
            return ("repository gone" if done.returncode else
                    "tag there" if done.stdout.strip() else "tag gone")
        with ThreadPoolExecutor(8) as pool:
            states = collections.Counter(pool.map(tag, pinned))
        print(f"  GitHub release tags pinned: {len(pinned)}; "
              + ", ".join(f"{k} {v}" for k, v in sorted(states.items())))


def head(repo):
    done = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}", "HEAD"],
                          capture_output=True, text=True, timeout=120, env=GIT_ENV, check=False)
    return repo, (done.stdout.split()[0] if done.returncode == 0 and done.stdout else None)


def last_commit(base, repo):
    where = os.path.join(base, repo.replace("/", "__"))
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none",
                    "--no-checkout", f"https://github.com/{repo}", where],
                   capture_output=True, timeout=300, env=GIT_ENV, check=False)
    done = subprocess.run(["git", "-C", where, "log", "-1", "--format=%cs"],
                          capture_output=True, text=True, check=False)
    return repo, done.stdout.strip() or None


def probe(differ):
    repos = sorted({r for _, a, b in differ for r in (a, b)})
    with ThreadPoolExecutor(8) as pool:
        heads = dict(pool.map(head, repos))
    tally, live = collections.Counter(), []
    for key, a, b in differ:
        if not heads[a] and not heads[b]:
            tally["both gone"] += 1
        elif not heads[a] or not heads[b]:
            tally["lcc-docs' gone" if not heads[a] else "krion64's gone"] += 1
        elif heads[a] == heads[b]:
            tally["one repository, two names"] += 1
        else:
            live.append((key, a, b))
    print("  " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    base = tempfile.mkdtemp()
    try:
        with ThreadPoolExecutor(8) as pool:
            dates = dict(pool.map(lambda r: last_commit(base, r),
                                  sorted({r for _, a, b in live for r in (a, b)})))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    newer = collections.Counter()
    for _key, a, b in live:
        if dates[a] and dates[b]:
            newer["lcc-docs'" if dates[a] > dates[b] else
                  "krion64's" if dates[b] > dates[a] else "same day"] += 1
    print(f"  two different live repositories: {len(live)}; newer last commit: "
          + ", ".join(f"{k} {v}" for k, v in sorted(newer.items())))


def main(argv) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    lcc, krion = lcc_mods(argv[1]), krion_mods(argv[2])
    unreadable = krion.pop(None, 0)
    if unreadable:
        print(f"krion64 records skipped as unreadable: {unreadable}")
    both = lcc.keys() & krion.keys()
    print(f"mods: lcc-docs {len(lcc)}, krion64 {len(krion)}, both {len(both)}, "
          f"only lcc-docs {len(lcc.keys() - krion.keys())}, "
          f"only krion64 {len(krion.keys() - lcc.keys())}")
    print(f"with a GitHub repository: lcc-docs {sum(bool(e.github) for e in lcc.values())}, "
          f"krion64 {sum(bool(krion_repo(r)) for r in krion.values())}; "
          f"lcc-docs with a direct archive and no repository: "
          f"{sum(bool(e.direct_urls and not e.github) for e in lcc.values())}")
    only_krion = [krion[k] for k in krion.keys() - lcc.keys()]
    print(f"only krion64, with a GitHub repository: "
          f"{sum(bool(krion_repo(r)) for r in only_krion)} of {len(only_krion)}")
    tally, differ = collections.Counter(), []
    for key in sorted(both):
        a = (lcc[key].github or "").lower() or None
        b = krion_repo(krion[key])
        if a and b:
            tally["same" if a == b else "different"] += 1
            if a != b:
                differ.append((key, a, b))
        else:
            tally["only lcc-docs names one" if a else
                  "only krion64 names one" if b else "neither names one"] += 1
    print("repository, on the mods both know: "
          + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    if "--probe" in argv[3:]:
        probe(differ)
    if "--bws" in argv[3:]:
        bws_report(bws_mods(argv[argv.index("--bws") + 1]),
                   os.path.join(argv[2], "version_cache.json"), "--probe" in argv[3:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
