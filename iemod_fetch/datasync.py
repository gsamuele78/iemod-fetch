"""
Keep the community data current, automatically (ADR-0032).

The order, the conflicts and the list of mods come from three community
databases: lcc-docs (the mod list), BigWorldSetup-NG (rules and per-mod
records) and krion64 (install-order categories, per-mod conflicts, upstream
release scan). A clone nobody pulls goes stale silently, and every decision
made from it goes stale with it. So the tool keeps its own cache and refreshes
it when a run starts, at most once per `max_age_hours`:

1. one API call asks for the repository's current commit; if it is the one
   cached, nothing else happens;
2. otherwise one API call lists the commit's files, and only the `.json` files
   under the paths the tool reads are considered;
3. only files whose git blob hash differs from the cached one are downloaded,
   from raw.githubusercontent.com at that exact commit, and each is checked
   against the hash GitHub listed before it is kept;
4. the new copy is assembled beside the old one and swapped in whole, so a
   failed refresh leaves the last good copy untouched;
5. before the swap, the guard: every file must be valid JSON, and the new copy
   is read with the tool's own parsers. If it does not parse, or a count (mods,
   rules, order entries) is zero or falls below half of the last good copy's -
   what a schema change upstream looks like - the update is refused, the last
   good copy stays, and that commit is not downloaded again;
6. what changed is recorded: counts before and after, mods added and removed,
   versions and catalogue statuses that moved. An update is never silent.

Offline, or when GitHub refuses, the last good copy is used and the run says
how old it is. Nothing is bundled: the data keeps its own licence (lcc-docs and
krion64 MIT, BWS-NG GPL-3.0), is fetched by the user's own run, and is read as
data, never executed.
"""
import calendar
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .catalogues import CatalogueSet
from .errors import ModFetchError
from .moddb import ModDatabase
from .naming import normalize_key, safe_component
from .ordering import OrderIndex
from .rules import RuleSet

API = "https://api.github.com/repos"
RAW = "https://raw.githubusercontent.com"
MANIFEST = "sources.json"
MAX_FILE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_AGE_HOURS = 24
COLLAPSE = 0.5              # a count below half the last good one is refused
SHOWN_CHANGES = 6

# What a guard reports about a copy: counts, and one fact per mod (a version,
# a status) whose movement between two commits is worth telling the user.
Measure = Tuple[Dict[str, int], Dict[str, str]]


def check_lcc_docs(root: str) -> Measure:
    catalogue = CatalogueSet.load([os.path.join(root, "db", "mods.json")])
    facts = {}
    for entries in catalogue.catalogues[0].by_key.values():
        for entry in entries:
            status = ", ".join(entry.status) or "listed"
            facts[normalize_key(entry.tp2)] = (
                f"{status} ({entry.last_update})" if entry.last_update else status)
    return {"mods": len(catalogue)}, facts


def check_bws_ng(root: str) -> Measure:
    rules = RuleSet.load([os.path.join(root, "data", "rules")])
    database = ModDatabase.load(os.path.join(root, "data", "mods"))
    facts = {key: record.version or "" for key, record in database.records.items()}
    return {"rules": len(rules), "mods": len(database)}, facts


def check_krion64(root: str) -> Measure:
    data = os.path.join(root, "data")
    index = OrderIndex.load(data)
    rules = RuleSet.load([os.path.join(data, "mods")])
    facts = {}
    mods = os.path.join(data, "mods")
    for name in sorted(os.listdir(mods)):
        with open(os.path.join(mods, name), encoding="utf-8") as fh:
            record = json.load(fh)
        if isinstance(record, dict) and isinstance(record.get("t"), str):
            facts[normalize_key(record["t"])] = str(record.get("v") or "")
    return {"order entries": len(index), "rules": len(rules)}, facts


@dataclass(frozen=True)
class Source:
    name: str                     # the cache directory
    repo: str                     # owner/repository on GitHub
    paths: Tuple[str, ...]        # files, or directories ending in "/"
    licence: str = ""
    # The guard: reads a staged copy with the tool's parsers and measures it.
    check: Optional[Callable[[str], Measure]] = field(default=None, compare=False)


SOURCES = (
    Source("lcc-docs", "RiwsPy/lcc-docs", ("db/mods.json",), "MIT", check_lcc_docs),
    Source("bws-ng", "Selphira/BigWorldSetup-Next-Generation",
           ("data/rules/", "data/mods/", "data/games/"), "GPL-3.0", check_bws_ng),
    Source("krion64", "krion64/krion64.github.io",
           ("data/categories.json", "data/mods/", "data/version_cache.json"), "MIT",
           check_krion64),
)


@dataclass
class SyncResult:
    name: str
    status: str                   # fresh | current | updated | rejected | failed
    commit: str = ""              # the commit the cache now serves
    date: str = ""
    changed: int = 0              # files fetched
    removed: int = 0              # files gone upstream
    detail: str = ""
    # What moved since the last good copy: {"counts": {name: [old, new]},
    # "added": [...], "removed": [...], "changed": {mod: [old, new]}}.
    changes: dict = field(default_factory=dict)


class Rejected(ModFetchError):
    """The new copy failed the guard; the last good copy stays."""
    code = "data_rejected"


@dataclass
class DataPaths:
    """What the cache can stand in for, when the flag was not given."""
    catalogue: Optional[str] = None           # --catalogue
    rules: List[str] = field(default_factory=list)   # --rules
    mod_db: Optional[str] = None              # --mod-db
    order_catalogue: Optional[str] = None     # --order-catalogue


def default_data_dir() -> str:
    """$IEMOD_DATA_DIR, else the platform's per-user cache directory."""
    if os.environ.get("IEMOD_DATA_DIR"):
        return os.environ["IEMOD_DATA_DIR"]
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "iemod-fetch", "data")


def blob_sha(data: bytes) -> str:
    """Git's object id for a file: what the tree API lists for it."""
    return hashlib.sha1(b"blob %d\x00" % len(data) + data,  # noqa: S324 - git's id
                        usedforsecurity=False).hexdigest()


def load_manifest(data_dir: str) -> Dict[str, dict]:
    try:
        with open(os.path.join(data_dir, MANIFEST), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_manifest(data_dir: str, manifest: Dict[str, dict]) -> None:
    path = os.path.join(data_dir, MANIFEST)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(path + ".tmp", path)


def _wanted(source: Source, path: str) -> bool:
    if not path.lower().endswith(".json"):
        return False
    try:
        for part in path.split("/"):
            safe_component(part)
    except ModFetchError:
        return False
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in source.paths)


def _epoch(date: str) -> Optional[float]:
    try:
        return float(calendar.timegm(time.strptime(date, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def _sync_one(client, data_dir: str, source: Source, entry: dict, force: bool,
              max_age_hours: float, now: float, workers: int) -> Tuple[SyncResult, dict]:
    if (not force and entry.get("checked_at")
            and now - entry["checked_at"] < max_age_hours * 3600
            and os.path.isdir(os.path.join(data_dir, source.name))):
        return SyncResult(source.name, "fresh", entry.get("commit", ""),
                          entry.get("date", "")), entry

    head = client.get_json(f"{API}/{source.repo}/commits/HEAD")
    commit = str(head.get("sha") or "")
    date = str(((head.get("commit") or {}).get("committer") or {}).get("date") or "")
    if not commit:
        raise ModFetchError(f"{source.repo}: GitHub did not name a commit")
    if commit == entry.get("commit") and os.path.isdir(os.path.join(data_dir, source.name)):
        return (SyncResult(source.name, "current", commit, date),
                {**entry, "checked_at": now})
    refused = entry.get("rejected") or {}
    if refused.get("commit") == commit:
        # Already examined and refused: not downloaded again until it moves.
        return (SyncResult(source.name, "rejected", entry.get("commit", ""),
                           entry.get("date", ""), detail=refused.get("reason", "")),
                {**entry, "checked_at": now})

    tree = client.get_json(f"{API}/{source.repo}/git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise ModFetchError(f"{source.repo}: the file list GitHub returned is truncated")
    listed = {item["path"]: item for item in tree.get("tree") or ()
              if item.get("type") == "blob" and isinstance(item.get("path"), str)
              and _wanted(source, item["path"])}
    too_big = [p for p, item in listed.items() if (item.get("size") or 0) > MAX_FILE_BYTES]
    if too_big:
        raise ModFetchError(f"{source.repo}: {too_big[0]} is larger than "
                            f"{MAX_FILE_BYTES} bytes")

    live = os.path.join(data_dir, source.name)
    staging = live + ".new"
    shutil.rmtree(staging, ignore_errors=True)
    old_files = entry.get("files") or {}
    to_fetch = []
    for path, item in listed.items():
        current = os.path.join(live, *path.split("/"))
        target = os.path.join(staging, *path.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if old_files.get(path) == item["sha"] and os.path.isfile(current):
            shutil.copy2(current, target)
        else:
            to_fetch.append((path, item["sha"], target))

    def fetch(job):
        path, sha, target = job
        # Mod files are named like `A7#ImprovedArcher.json`: unencoded, '#'
        # would end the path and start a fragment the server never sees.
        url = f"{RAW}/{source.repo}/{commit}/{urllib.parse.quote(path, safe='/')}"
        data = client.read_bytes(url, limit=MAX_FILE_BYTES)
        if blob_sha(data) != sha:
            raise ModFetchError(f"{source.repo}: {path} does not match the hash "
                                f"GitHub lists for it")
        with open(target, "wb") as fh:
            fh.write(data)

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(fetch, to_fetch))
        stamp = _epoch(date)
        if stamp is not None:
            for job in to_fetch:
                os.utime(job[2], (stamp, stamp))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    try:
        metrics, facts = _guard(source, staging, entry)
    except Rejected as exc:
        shutil.rmtree(staging, ignore_errors=True)
        reason = f"{commit[:7]} refused: {exc}"
        return (SyncResult(source.name, "rejected", entry.get("commit", ""),
                           entry.get("date", ""), detail=reason),
                {**entry, "checked_at": now,
                 "rejected": {"commit": commit, "reason": reason}})

    retired = live + ".old"
    shutil.rmtree(retired, ignore_errors=True)
    if os.path.isdir(live):
        os.replace(live, retired)
    os.replace(staging, live)
    shutil.rmtree(retired, ignore_errors=True)

    removed = len(set(old_files) - set(listed))
    changes = _changes(entry, metrics, facts)
    new_entry = {"repo": source.repo, "commit": commit, "date": date,
                 "checked_at": now, "licence": source.licence,
                 "files": {p: item["sha"] for p, item in listed.items()},
                 "metrics": metrics, "facts": facts, "changes": changes}
    return (SyncResult(source.name, "updated", commit, date, changed=len(to_fetch),
                       removed=removed, changes=changes), new_entry)


def _guard(source: Source, staging: str, entry: dict) -> Measure:
    """Refuse a copy that is not JSON, does not parse, or has collapsed."""
    for root, _dirs, names in os.walk(staging):
        for name in names:
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    json.load(fh)
            except (OSError, ValueError) as exc:
                rel = os.path.relpath(path, staging).replace(os.sep, "/")
                raise Rejected(f"{rel} is not valid JSON ({exc})") from None
    if source.check is None:
        return {}, {}
    try:
        metrics, facts = source.check(staging)
    except (ModFetchError, OSError, ValueError, KeyError, TypeError) as exc:
        raise Rejected(f"the tool cannot read it: {exc}") from None
    previous = entry.get("metrics") or {}
    for name, count in metrics.items():
        if count == 0:
            raise Rejected(f"it has no {name}")
        before = previous.get(name)
        if before and count < before * COLLAPSE:
            raise Rejected(f"{name} collapsed from {before} to {count}; a format "
                           f"change upstream is the likely cause")
    return metrics, facts


def _changes(entry: dict, metrics: Dict[str, int], facts: Dict[str, str]) -> dict:
    """What moved since the last good copy; empty on the first copy."""
    old_facts = entry.get("facts")
    if not old_facts or not metrics:
        return {}
    old_metrics = entry.get("metrics") or {}
    return {
        "from": entry.get("commit", ""),
        "counts": {k: [old_metrics.get(k), v] for k, v in metrics.items()
                   if old_metrics.get(k) != v},
        "added": sorted(set(facts) - set(old_facts)),
        "removed": sorted(set(old_facts) - set(facts)),
        "changed": {k: [old_facts[k], facts[k]] for k in sorted(facts)
                    if k in old_facts and old_facts[k] != facts[k]},
    }


def refresh(client, data_dir: str, sources: Sequence[Source] = SOURCES,
            max_age_hours: float = DEFAULT_MAX_AGE_HOURS, force: bool = False,
            now: Optional[float] = None, workers: int = 8) -> List[SyncResult]:
    """
    Bring the cache up to date; never raises for one source failing.

    A source that cannot be refreshed keeps its last good copy and reports
    `failed` with the reason; the others are still refreshed.
    """
    os.makedirs(data_dir, exist_ok=True)
    manifest = load_manifest(data_dir)
    stamp = time.time() if now is None else now
    results = []
    for source in sources:
        entry = manifest.get(source.name) or {}
        try:
            result, manifest[source.name] = _sync_one(
                client, data_dir, source, entry, force, max_age_hours, stamp, workers)
        except (ModFetchError, OSError, ValueError, KeyError, TypeError) as exc:
            result = SyncResult(source.name, "failed", entry.get("commit", ""),
                                entry.get("date", ""), detail=str(exc))
        results.append(result)
    _save_manifest(data_dir, manifest)
    return results


def data_paths(data_dir: str, sources: Sequence[Source] = SOURCES) -> DataPaths:
    """The cached data, as the flags it stands in for; only what is there."""
    def there(*parts) -> Optional[str]:
        path = os.path.join(data_dir, *parts)
        return path if os.path.exists(path) else None

    names = {s.name for s in sources}
    paths = DataPaths()
    if "lcc-docs" in names:
        paths.catalogue = there("lcc-docs", "db", "mods.json")
    if "bws-ng" in names:
        paths.mod_db = there("bws-ng", "data", "mods")
        rules = there("bws-ng", "data", "rules")
        if rules:
            paths.rules.append(rules)
    if "krion64" in names:
        krion = there("krion64", "data")
        if krion and os.path.isfile(os.path.join(krion, "categories.json")):
            paths.order_catalogue = krion
        mods = there("krion64", "data", "mods")
        if mods:
            paths.rules.append(mods)
    return paths


def _describe_changes(changes: dict) -> List[str]:
    if not changes:
        return []
    lines = []
    counts = ", ".join(f"{k} {old} -> {new}" for k, (old, new) in changes["counts"].items())
    moved = (f"{len(changes['added'])} added, {len(changes['removed'])} removed, "
             f"{len(changes['changed'])} changed")
    lines.append("    " + (f"{counts}; " if counts else "") + moved)
    for kind in ("added", "removed"):
        names = changes[kind]
        if names:
            more = f", +{len(names) - SHOWN_CHANGES} more" if len(names) > SHOWN_CHANGES else ""
            lines.append(f"    {kind}: {', '.join(names[:SHOWN_CHANGES])}{more}")
    shown = list(changes["changed"].items())[:SHOWN_CHANGES]
    for key, (old, new) in shown:
        lines.append(f"    {key}: {old or '-'} -> {new or '-'}")
    if len(changes["changed"]) > SHOWN_CHANGES:
        lines.append(f"    ... {len(changes['changed']) - SHOWN_CHANGES} more changed "
                     f"(api.data_status() has them all)")
    return lines


def describe(results: Sequence[SyncResult]) -> List[str]:
    """One line per source, for the run's header."""
    lines = []
    for r in results:
        when = r.date[:10] if r.date else "unknown date"
        if r.status == "updated":
            lines.append(f"{r.name}: updated to {r.commit[:7]} ({when}), "
                         f"{r.changed} file(s) fetched, {r.removed} removed")
            lines.extend(_describe_changes(r.changes))
        elif r.status == "rejected":
            kept = f"keeping {r.commit[:7]} ({when})" if r.commit else "no copy yet"
            lines.append(f"{r.name}: update REFUSED by the guard - {r.detail}; {kept}")
        elif r.status == "failed":
            kept = f"keeping {r.commit[:7]} ({when})" if r.commit else "no copy yet"
            lines.append(f"{r.name}: not refreshed ({r.detail}); {kept}")
        else:
            lines.append(f"{r.name}: {r.commit[:7]} ({when}), {r.status}")
    return lines
