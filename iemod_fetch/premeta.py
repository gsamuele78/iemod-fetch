"""
A mod's own metadata ini, read before the mod is downloaded (ADR-0037).

Project Infinity's metadata file (`<tp2 name>.ini`, `[Metadata]`, beside the
tp2; modmeta.py reads it) carries the author's own install order: `Before`
and `After`, lists of other mods' tp2 names. The tool already reads it from a
staged mod. But the order is planned, and conflicts are judged, before
anything is downloaded - and then only the community rule sets speak.

Measured on 85 real metadata inis (tools/pi_metadata_benchmark.py): they
state 314 order pairs; krion64's install order agrees with 239, a rule already
covers 34 more, and 19 are known only to the author's ini - 7 of them
contradicting krion64's order (Region of Terror after IWD1_EET and IWD2_EET,
Kivan before Adrian, ...). So the ini is worth reading early.

It is one small text file, fetched from the repository the catalogue names,
at its default branch, from raw.githubusercontent.com: never executed, capped
at 1 MiB, parsed by the same tolerant reader as a staged one. What was found -
and what was not, so a missing file is not asked for again on every run - is
kept in one JSON file in the community-data cache, with the date. A staged
mod's own ini always wins over a fetched one.
"""
import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .errors import ModFetchError
from .modmeta import ModMetadata, parse_metadata_ini
from .naming import normalize_key

RAW = "https://raw.githubusercontent.com"
API = "https://api.github.com/repos"
CACHE_FILE = "mod-metadata.json"
MAX_INI_BYTES = 1024 * 1024
MAX_AGE_DAYS = 7          # a found or missing ini is asked for again after this
RETRY_AFTER_SECONDS = 3600   # after a network error: not before this


@dataclass(frozen=True)
class Wanted:
    """A mod whose ini is wanted: its folder, its tp2 file, its repository."""
    folder: str
    tp2_file: str
    repo: str                 # owner/name on GitHub


def candidates(folder: str, tp2_file: str) -> List[str]:
    """Where the ini may be in the repository: beside the tp2, named after it."""
    stem = os.path.splitext(os.path.basename(tp2_file.replace("\\", "/")))[0]
    names = [stem]
    if stem.lower().startswith("setup-"):
        names.append(stem[6:])
    # Project Infinity runs on Windows, where `rot.ini` is `RoT.ini`; GitHub is
    # case-sensitive, and Region of Terror ships `RoT/rot.ini` beside
    # `setup-RoT.tp2`. The lower-case spelling is tried too.
    names += [name.lower() for name in names if name.lower() != name]
    out = []
    for name in names:
        for where in (f"{folder}/{name}.ini", f"{name}.ini"):
            if where not in out:
                out.append(where)
    return out


def cache_key(folder: str) -> str:
    return normalize_key(folder)


class MetadataCache:
    """
    The fetched inis, by mod folder key: {"repo", "path", "text", "checked"},
    plus "failed" (when the network last failed) while it is backing off.
    """

    def __init__(self, data_dir: str) -> None:
        self.path = os.path.join(data_dir, CACHE_FILE)
        self.entries: Dict[str, dict] = {}
        try:
            with open(self.path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.entries = {k: v for k, v in loaded.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass                  # no cache yet, or a broken one: start again

    def get(self, folder: str, repo: str) -> Optional[ModMetadata]:
        """The cached ini of `folder`, if it came from `repo` and gives an order."""
        entry = self.entries.get(cache_key(folder)) or {}
        text = entry.get("text")
        if not isinstance(text, str) or entry.get("repo") != repo.lower():
            return None
        meta = parse_metadata_ini(text, source=f"{entry.get('repo')}:{entry.get('path')}")
        return meta if meta.has_order_hints else None

    def fresh(self, folder: str, repo: str, now: float) -> bool:
        entry = self.entries.get(cache_key(folder))
        if not entry or entry.get("repo") != repo.lower():
            return False
        if now - float(entry.get("failed") or 0) < RETRY_AFTER_SECONDS:
            return True           # backing off after a network error
        if not entry.get("checked"):
            return False          # never checked: only ever failed
        return now - float(entry["checked"]) < MAX_AGE_DAYS * 86400

    def back_off(self, folder: str, repo: str, now: float) -> None:
        """Remember a network failure; what was found before is kept."""
        key = cache_key(folder)
        entry = dict(self.entries.get(key) or {})
        if entry.get("repo") != repo.lower():
            entry = {"repo": repo.lower(), "path": None, "text": None, "checked": 0}
        entry["failed"] = now
        self.entries[key] = entry

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp = self.path + ".tmp"
        try:
            with open(temp, "w", encoding="utf-8") as fh:
                json.dump(self.entries, fh, indent=1, sort_keys=True)
            os.replace(temp, self.path)
        except BaseException:
            if os.path.exists(temp):
                os.unlink(temp)
            raise


def _names(tp2_file: str) -> List[str]:
    stem = os.path.splitext(os.path.basename(tp2_file.replace("\\", "/")))[0]
    names = [stem]
    if stem.lower().startswith("setup-"):
        names.append(stem[6:])
    return [name.lower() + ".ini" for name in names]


def _raw(client, repo: str, where: str) -> Optional[str]:
    """The file's text, or None when it is not there (404). Other errors raise."""
    url = f"{RAW}/{repo}/HEAD/{urllib.parse.quote(where, safe='/')}"
    try:
        data = client.read_bytes(url, limit=MAX_INI_BYTES)
    except ModFetchError as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise
    return bytes(data).decode("utf-8-sig", errors="replace")


def _listed(client, repo: str, path: str) -> Optional[List[dict]]:
    """A repository folder's entries (GitHub's contents API); None if it is not there."""
    url = f"{API}/{repo}/contents" + (f"/{urllib.parse.quote(path, safe='/')}" if path else "")
    try:
        listed = client.get_json(url)
    except ModFetchError as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise
    return [e for e in listed if isinstance(e, dict)] if isinstance(listed, list) else None


def _find(client, repo: str, mod: Wanted) -> Tuple[Optional[str], Optional[str]]:
    """
    (text, path) of the mod's ini, or (None, None) when the repository has none.

    The likely spellings are tried first, on raw.githubusercontent.com (no API
    quota). On a miss the folder is listed once and matched ignoring case: a
    WeiDU log may spell `ASCENSION/ASCENSION.TP2`, and a mod may ship
    `DeitiesOfFaerun/Deitiesoffaerun.ini` beside `DeitiesOffaerun.tp2` - PI runs
    where case does not matter, GitHub does not. Only a listing proves a miss.
    """
    for where in candidates(mod.folder, mod.tp2_file):
        text = _raw(client, repo, where)
        if text is not None and "[metadata]" in text.lower():
            return text, where
    wanted = set(_names(mod.tp2_file))
    root = _listed(client, repo, "") or []
    folders = [e["name"] for e in root if e.get("type") == "dir"
               and str(e.get("name", "")).lower() == mod.folder.lower()]
    places = [("", root)] + [(name, _listed(client, repo, name) or []) for name in folders]
    for prefix, entries in reversed(places):           # the mod folder first
        for entry in entries:
            name = str(entry.get("name", ""))
            if entry.get("type") == "file" and name.lower() in wanted:
                where = f"{prefix}/{name}" if prefix else name
                text = _raw(client, repo, where)
                if text is not None and "[metadata]" in text.lower():
                    return text, where
    return None, None


def fetch(client, cache: MetadataCache, wanted: Iterable[Wanted],
          now: Optional[float] = None) -> Tuple[int, int, List[str]]:
    """
    Fetch the ini of every `wanted` mod whose cache entry is missing or old.
    Returns (found, missing, problems). A network error is the network's, not
    the file's: nothing more is asked this time, every mod still to ask backs
    off for an hour, and what was found before is kept.
    """
    now = time.time() if now is None else now
    found = missing = 0
    problems: List[str] = []
    todo = [mod for mod in wanted if not cache.fresh(mod.folder, mod.repo, now)]
    for n, mod in enumerate(todo):
        repo = mod.repo.lower()
        try:
            text, path = _find(client, repo, mod)
        except ModFetchError as exc:
            problems.append(f"{mod.folder}: {exc}")
            for rest in todo[n:]:
                cache.back_off(rest.folder, rest.repo, now)
            break
        cache.entries[cache_key(mod.folder)] = {"repo": repo, "path": path, "text": text,
                                                "checked": now}
        if text is None:
            missing += 1
        else:
            found += 1
    return found, missing, problems
