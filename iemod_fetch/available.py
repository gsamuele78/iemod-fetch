"""
The mods a player can choose from, merged from every source given (M1).

The selection screen of a UI starts here, before any WeiDU.log exists. Each
source knows something different about a mod:

* the download manifest (`mod_downloads.json`): where to fetch it;
* the lcc-docs catalogue: games, categories, quality rating, status, last
  update, and its own advisories;
* the BWS-NG / krion64 mod database: the version and, often, a sha256;
* krion64's release cache: each GitHub repository's latest release (M2d).

With versions known and a WeiDU.log given, each mod also says what is
installed, the newest version any source names, and whether that is an update
(freshness.py has the rule and how it was measured).

They are joined on the folder name folded to its comparison key - the same key
every other part of the tool joins on - so one mod is one entry, carrying each
source's facts and where they came from. Nothing is fetched: this reads only
what was given.
"""
import json
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence

from .catalogues import CatalogueSet
from .freshness import RELEASE, Candidate, Release, github_repo, latest, update_available
from .manifest import Manifest
from .moddb import ModDatabase
from .naming import normalize_key
from .weidu import KNOWN_GAMES

SCHEMA_VERSION = 1
_GAMES = {game.upper(): game for game in KNOWN_GAMES}


@dataclass
class AvailableMod:
    key: str                          # comparison key: lowercase alphanumerics
    tp2: str                          # the folder name, as the first source spells it
    name: str
    in_manifest: bool = False
    games: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    safe: int | None = None
    last_update: str | None = None
    version: str | None = None
    blocking: bool = False
    advisories: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)       # GitHub owner/repo, lowercased
    candidates: list[Candidate] = field(default_factory=list)
    installed: str | None = None
    latest: Candidate | None = None
    update_available: bool | None = None

    def _repo(self, url: str | None) -> None:
        repo = github_repo(url)
        if repo and repo not in self.repos:
            self.repos.append(repo)

    def as_dict(self) -> dict:
        freshness = {"installed": self.installed,
                     "latest": self.latest.as_dict() if self.latest else None,
                     "update_available": self.update_available}
        return {**self._facts(), **freshness}

    def _facts(self) -> dict:
        return {"key": self.key, "tp2": self.tp2, "name": self.name,
                "in_manifest": self.in_manifest, "games": list(self.games),
                "categories": list(self.categories), "status": list(self.status),
                "safe": self.safe, "last_update": self.last_update,
                "version": self.version, "blocking": self.blocking,
                "advisories": list(self.advisories), "sources": list(self.sources)}


def _games(values) -> tuple[str, ...]:
    return tuple(_GAMES[v.upper()] for v in values if isinstance(v, str)
                 and v.upper() in _GAMES)


def _merge(found: dict[str, AvailableMod], key: str, tp2: str, name: str) -> AvailableMod:
    if key not in found:
        found[key] = AvailableMod(key=key, tp2=tp2, name=name or tp2)
    return found[key]


def available_mods(manifest: Manifest | None = None,
                   catalogues: CatalogueSet | None = None,
                   database: ModDatabase | None = None,
                   releases: Mapping[str, Release] | None = None,
                   versions: Sequence[ModDatabase] = (),
                   installed: Mapping[str, str] | None = None) -> list[AvailableMod]:
    """
    One entry per mod any source knows, sorted by name.

    `releases` is the release cache (owner/repo -> latest release), `versions`
    more databases read only for the version they record (krion64's), and
    `installed` the installed version by mod key, from a WeiDU.log.
    """
    found: dict[str, AvailableMod] = {}
    for source in (manifest.sources.values() if manifest else ()):
        tp2 = source.folder or source.key
        mod = _merge(found, normalize_key(tp2), tp2, source.name)
        mod.in_manifest = True
        mod.sources.append({k: v for k, v in (
            ("origin", "manifest"), ("url", source.url), ("github", source.github),
            ("sha256", source.sha256), ("release_tag", source.release_tag)) if v})
        mod._repo(source.github and f"https://github.com/{source.github}")
        mod._repo(source.url)

    for catalogue in (catalogues.catalogues if catalogues else ()):
        for key, entries in catalogue.by_key.items():
            for entry in entries:
                mod = _merge(found, key, entry.tp2, entry.name)
                mod.games = tuple(sorted(set(mod.games) | set(_games(entry.games))))
                mod.categories = tuple(dict.fromkeys(mod.categories + entry.categories))
                mod.status = tuple(dict.fromkeys(mod.status + entry.status))
                mod.safe = mod.safe if mod.safe is not None else entry.safe
                mod.last_update = mod.last_update or entry.last_update
                mod.blocking = mod.blocking or entry.blocking
                mod.advisories.extend(a for a in entry.advisories()
                                      if a not in mod.advisories)
                mod.sources.append({k: v for k, v in (
                    ("origin", entry.origin), ("github", entry.github),
                    ("urls", list(entry.http_urls))) if v} or {"origin": entry.origin})
                mod._repo(entry.github and f"https://github.com/{entry.github}")
                for url in entry.http_urls:
                    mod._repo(url)

    origin = database.origin if database else ""
    for record in (database.records.values() if database else ()):
        mod = _merge(found, record.key, record.key, record.name or record.key)
        mod.version = mod.version or record.version
        mod.games = tuple(sorted(set(mod.games) | set(_games(record.games))))
        best = record.best_file
        mod.sources.append({k: v for k, v in (
            ("origin", origin), ("url", best.download if best else None),
            ("sha256", best.sha256 if best else None),
            ("version", record.version)) if v})
        _record_versions(mod, record, origin)

    for extra in versions:
        for record in extra.records.values():
            if record.key in found:
                _record_versions(found[record.key], record, extra.origin)

    for mod in found.values():
        for repo in _by_likeness(mod.repos, mod.key):
            release = (releases or {}).get(repo)
            if release:
                mod.candidates.insert(0, Candidate(release.tag, RELEASE, release.date,
                                                   release.url))
                break
        mod.latest = latest(mod.candidates)
        mod.installed = (installed or {}).get(mod.key)
        mod.update_available = update_available(mod.installed, mod.latest)

    return sorted(found.values(), key=lambda m: (m.name.lower(), m.key))


def _by_likeness(repos: list[str], key: str) -> list[str]:
    """The repository named like the mod first: CTB's sub-mods link both
    their own repository and Check the Bodies'."""
    def rank(repo: str) -> int:
        name = normalize_key(repo.split("/", 1)[1])
        return 0 if name == key else 1 if key and key in name else 2
    return sorted(repos, key=rank)


def _record_versions(mod: AvailableMod, record, origin: str) -> None:
    for url in [record.homepage] + [f.download for f in record.files]:
        mod._repo(url)
    if record.version:
        mod.candidates.append(Candidate(record.version, origin))


def mods_document(mods: list[AvailableMod]) -> str:
    """The versioned JSON a UI reads (ADR-0030)."""
    return json.dumps({"schema_version": SCHEMA_VERSION,
                       "mods": [m.as_dict() for m in mods]}, indent=2) + "\n"
