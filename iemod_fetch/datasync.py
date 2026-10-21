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
   failed refresh leaves the last good copy untouched.

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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .errors import ModFetchError
from .naming import safe_component

API = "https://api.github.com/repos"
RAW = "https://raw.githubusercontent.com"
MANIFEST = "sources.json"
MAX_FILE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_AGE_HOURS = 24


@dataclass(frozen=True)
class Source:
    name: str                     # the cache directory
    repo: str                     # owner/repository on GitHub
    paths: Tuple[str, ...]        # files, or directories ending in "/"
    licence: str = ""


SOURCES = (
    Source("lcc-docs", "RiwsPy/lcc-docs", ("db/mods.json",), "MIT"),
    Source("bws-ng", "Selphira/BigWorldSetup-Next-Generation",
           ("data/rules/", "data/mods/", "data/games/"), "GPL-3.0"),
    Source("krion64", "krion64/krion64.github.io",
           ("data/categories.json", "data/mods/", "data/version_cache.json"), "MIT"),
)


@dataclass
class SyncResult:
    name: str
    status: str                   # fresh | current | updated | failed
    commit: str = ""
    date: str = ""
    changed: int = 0
    removed: int = 0
    detail: str = ""


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
        data = client.read_bytes(f"{RAW}/{source.repo}/{commit}/{path}",
                                 limit=MAX_FILE_BYTES)
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

    retired = live + ".old"
    shutil.rmtree(retired, ignore_errors=True)
    if os.path.isdir(live):
        os.replace(live, retired)
    os.replace(staging, live)
    shutil.rmtree(retired, ignore_errors=True)

    removed = len(set(old_files) - set(listed))
    new_entry = {"repo": source.repo, "commit": commit, "date": date,
                 "checked_at": now, "licence": source.licence,
                 "files": {p: item["sha"] for p, item in listed.items()}}
    return (SyncResult(source.name, "updated", commit, date, changed=len(to_fetch),
                       removed=removed), new_entry)


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


def describe(results: Sequence[SyncResult]) -> List[str]:
    """One line per source, for the run's header."""
    lines = []
    for r in results:
        when = r.date[:10] if r.date else "unknown date"
        if r.status == "updated":
            lines.append(f"{r.name}: updated to {r.commit[:7]} ({when}), "
                         f"{r.changed} file(s) fetched, {r.removed} removed")
        elif r.status == "failed":
            kept = f"keeping {r.commit[:7]} ({when})" if r.commit else "no copy yet"
            lines.append(f"{r.name}: not refreshed ({r.detail}); {kept}")
        else:
            lines.append(f"{r.name}: {r.commit[:7]} ({when}), {r.status}")
    return lines
