"""
A mod's own metadata ini, read before the mod is downloaded (ADR-0037).

Project Infinity's metadata file (`<tp2 name>.ini`, `[Metadata]`, beside the
tp2; modmeta.py reads it) carries the author's own install order: `Before`
and `After`, lists of other mods' tp2 names. The tool already reads it from a
staged mod. But the order is planned, and conflicts are judged, before
anything is downloaded - and then only the community rule sets speak.

Measured on 85 real metadata inis (tools/pi_metadata_benchmark.py): they
state 314 order pairs; krion64's install order agrees with 260, a rule already
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
CACHE_FILE = "mod-metadata.json"
MAX_INI_BYTES = 1024 * 1024
MAX_AGE_DAYS = 7          # a found or missing ini is asked for again after this


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
    """The fetched inis, by mod folder key: {"repo", "path", "text", "checked"}."""

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

    def get(self, folder: str) -> Optional[ModMetadata]:
        entry = self.entries.get(cache_key(folder)) or {}
        text = entry.get("text")
        if not isinstance(text, str):
            return None
        meta = parse_metadata_ini(text, source=f"{entry.get('repo')}:{entry.get('path')}")
        return meta if meta.has_order_hints else None

    def fresh(self, folder: str, repo: str, now: float) -> bool:
        entry = self.entries.get(cache_key(folder))
        return bool(entry and entry.get("repo") == repo.lower()
                    and now - float(entry.get("checked") or 0) < MAX_AGE_DAYS * 86400)

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


def fetch(client, cache: MetadataCache, wanted: Iterable[Wanted],
          now: Optional[float] = None) -> Tuple[int, int, List[str]]:
    """
    Fetch the ini of every `wanted` mod whose cache entry is missing or old.
    Returns (found, missing, problems); a network error leaves the old entry.
    """
    now = time.time() if now is None else now
    found = missing = 0
    problems: List[str] = []
    for mod in wanted:
        repo = mod.repo.lower()
        if cache.fresh(mod.folder, repo, now):
            continue
        text, path, failed = None, None, False
        for where in candidates(mod.folder, mod.tp2_file):
            url = f"{RAW}/{repo}/HEAD/{urllib.parse.quote(where, safe='/')}"
            try:
                data = client.read_bytes(url, limit=MAX_INI_BYTES)
            except ModFetchError as exc:
                if getattr(exc, "status", None) == 404:
                    continue          # not at this path: try the next
                problems.append(f"{mod.folder}: {exc}")
                failed = True
                break
            decoded = data.decode("utf-8-sig", errors="replace")
            if "[metadata]" in decoded.lower():
                text, path = decoded, where
                break
        if failed:
            continue
        cache.entries[cache_key(mod.folder)] = {"repo": repo, "path": path, "text": text,
                                                "checked": now}
        if text is None:
            missing += 1
        else:
            found += 1
    return found, missing, problems
