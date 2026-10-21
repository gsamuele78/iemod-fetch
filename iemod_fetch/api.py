"""
The public API: what the command line does, as functions (ADR-0029, ADR-0030).

The command line and the GUI are two clients of this module. Neither holds
logic of its own: `cli.py` turns flags into `Settings` and prints; a GUI builds
`Settings` from its screens and reads the `Outcome`. Everything a front end may
rely on is in `__all__`; anything starting with an underscore may change.

    from iemod_fetch import api
    mods = api.list_mods("mod_downloads.json", catalogues=["lcc/db/mods.json"])
    outcome = api.run(api.Settings(selection="selection.json", target="Mods"),
                      on_event=print, cancel=threading.Event())
    outcome.exit_code, outcome.report, outcome.order_plan, outcome.conflict_report

`run` writes nothing to the terminal unless given a `stream`; its progress
reaches `on_event` (the events of schemas/events-v1.schema.json), and setting
`cancel` stops it at the next chunk. Errors are raised as `ModFetchError`
subclasses, each with a stable `code` (errors.py).
"""
import contextlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field, fields, replace
from typing import Any, List, Optional, Sequence

from .auth import resolve_credential
from .available import AvailableMod, available_mods, mods_document
from .catalogues import CatalogueSet
from . import datasync
from .conflicts import ConflictReport, build_conflict_report, render_conflict_report
from .constraints import ModConstraints, load_constraints, tp2_rules
from .errors import ConfigError
from .freshness import parse_release_cache
from .gamedir import verify_eet
from .install import State, find_tp2_files
from .installer import build_installer
from .languages import apply_language_preference, parse_preferences
from .manifest import Manifest, load_manifest
from .moddb import ModDatabase
from .modmeta import find_metadata
from .naming import normalize_key
from .net import DEFAULT_MAX_BYTES, HttpClient
from .ordering import (EET_LOG, PRE_EET_LOG, OrderIndex, plan_order, tp2_key,
                       render_plan_summary)
from .orgindex import OwnerIndex, load_trusted_owners
from .pinning import build_pinned_manifest, write_pinned_manifest
from .plan import build_plan, load_aliases
from .report import RunReport, render_summary
from . import bio
from .decisions import parse_decisions
from .resolution import (ResolutionResult, apply_decisions, before_eet_core,
                         resolve_conflicts, resolve_refusals)
from .rules import Context, Install, RuleSet, check_all, load_suppressions
from .runner import Options, Runner
from .selection import (Selection, parse_selection, selection_from_logs,
                        selection_to_json)
from .simulate import simulate_install, steps_of
from .tp2 import read_mod_tp2
from . import tra
from .contract import SCHEMA_VERSION
from .weidu import ParsedLog, parse_weidu_files, split_log_spec
from . import __version__

__all__ = ["Settings", "Outcome", "run", "list_mods", "load_selection",
           "selection_of_logs", "update_data", "data_status", "describe_mods",
           "load_bio_code", "bio_code_of"]


@dataclass
class Settings:
    """
    Everything a run can be told. One field per command-line option, with the
    same name and default (`iemod-fetch --help` describes each), so a GUI and
    the command line mean the same thing by the same word.
    """
    # inputs
    manifest: str = "mod_downloads.json"
    weidu_log: List[str] = field(default_factory=list)     # "PATH" or "PATH:GAME"
    selection: Optional[str] = None
    bio_code: Optional[str] = None         # a file holding a BIO-MODLIST-V1 code
    aliases: Optional[str] = None
    catalogue: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    mod_db: Optional[str] = None
    order_catalogue: Optional[str] = None
    eet_sequence: Optional[str] = None     # BWS-NG games/eet.json
    releases: Optional[str] = None         # krion64 data/version_cache.json
    suppress: Optional[str] = None
    all_manifest_entries: bool = False
    only: List[str] = field(default_factory=list)
    # outputs
    target: str = "./Mods"
    json_report: Optional[str] = None
    emit_pinned_manifest: Optional[str] = None
    events: Optional[str] = None
    list_mods: Optional[str] = None
    describe_mods: Optional[str] = None
    emit_selection: Optional[str] = None
    emit_bio_code: Optional[str] = None
    plan_order: Optional[str] = None
    resolve_conflicts: bool = False
    decisions: Optional[str] = None        # decisions.json: the player's answers
    simulate: bool = False
    bgee_dir: Optional[str] = None
    bg2ee_dir: Optional[str] = None
    emit_installer: bool = False
    language_preference: Any = None        # "fr_FR,en_US" or a parsed list
    game_language: Optional[str] = None
    conflict_report: Optional[str] = None
    show_advisories: bool = False
    quiet: bool = False
    # behaviour
    include_optional: bool = False
    reassign_phase: bool = False
    check_only: bool = False
    dry_run: bool = False
    force: bool = False
    refresh: bool = False
    workers: int = 4
    allow_manual: bool = False
    accept_suggestions: bool = False
    # security and network
    allow_http: bool = False
    allow_exe: bool = False
    no_discovery: bool = False
    trusted_owners: Optional[str] = None
    trusted_owner: List[str] = field(default_factory=list)
    discovery_attempts: int = 1
    owner_cache: Optional[str] = None
    accept_offsite: bool = False
    max_bytes: int = DEFAULT_MAX_BYTES
    timeout: int = 45
    retries: int = 3
    # GitHub credential
    token_file: Optional[str] = None
    no_gh_cli: bool = False
    no_git_credential: bool = False
    oauth_client_id: Optional[str] = None
    # community data (ADR-0032)
    update_data: bool = False
    no_update_data: bool = False
    data_dir: Optional[str] = None
    data_max_age: int = datasync.DEFAULT_MAX_AGE_HOURS
    no_default_data: bool = False

    @classmethod
    def from_namespace(cls, namespace) -> "Settings":
        """From the command line's parsed arguments (or anything with the names)."""
        values = {}
        for f in fields(cls):
            if hasattr(namespace, f.name):
                value = getattr(namespace, f.name)
                if value is None and isinstance(getattr(cls(), f.name), list):
                    value = []
                values[f.name] = value
        return cls(**values)


@dataclass
class Outcome:
    """What a run produced. Any part may be None when the run did not make it."""
    exit_code: int
    report: Optional[RunReport] = None
    order_plan: Any = None                  # ordering.OrderPlan, with --plan-order
    conflict_report: Optional[ConflictReport] = None


class _Silent:
    """A stream that discards: `run` prints nothing unless given a stream."""

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def run(settings: Settings, stream=None, config=None, on_event=None,
        cancel=None) -> Outcome:
    """
    Do what `settings` asks: list mods, convert a selection, check, plan, fetch.

    `stream` receives the human-readable report (the command line passes
    stdout); `on_event` receives progress events; `cancel` (a threading.Event)
    stops the run. `settings` is not modified.
    """
    settings = replace(settings, weidu_log=list(settings.weidu_log or []))
    stream = stream if stream is not None else _Silent()
    if settings.update_data:
        results = update_data(settings, force=True, stream=stream, on_event=on_event)
        return Outcome(1 if all(r.status == "failed" for r in results) else 0)
    _use_data(settings, stream, on_event)
    with tempfile.TemporaryDirectory(prefix="iemod-selection-") as workdir:
        imported = _use_selection(settings, workdir)
        _emit_bio_code(settings, imported, stream)
        return _run(settings, stream, config, on_event, cancel)


def update_data(settings: Optional[Settings] = None, force: bool = False,
                stream=None, on_event=None) -> List[datasync.SyncResult]:
    """
    Refresh the cached community data (lcc-docs, BWS-NG, krion64).

    Without `force`, a source checked within `settings.data_max_age` hours is
    left alone. A source that cannot be refreshed keeps its last good copy and
    is reported `failed`; this never raises for that.
    """
    settings = settings or Settings()
    results = datasync.refresh(_LazyClient(settings), _data_dir(settings),
                               datasync.SOURCES, max_age_hours=settings.data_max_age,
                               force=force)
    for result in results:
        if on_event is not None:
            on_event({"schema_version": SCHEMA_VERSION, "event": "data_source",
                      "name": result.name, "status": result.status,
                      "commit": result.commit, "date": result.date,
                      "changed": result.changed, "detail": result.detail,
                      "changes": result.changes})
    if stream is not None and not settings.quiet:
        for line in datasync.describe(results):
            if line.endswith(", fresh"):
                continue
            if line.startswith("    "):            # the detail of a change
                print(f"                {line.strip()}", file=stream)
            else:
                print(f"  data        : {line}", file=stream)
    return results


def data_status(data_dir: Optional[str] = None) -> dict:
    """What the cache holds: per source, its repository, commit, date and check time."""
    return datasync.load_manifest(data_dir or datasync.default_data_dir())


def _data_dir(settings: Settings) -> str:
    return settings.data_dir or datasync.default_data_dir()


def _use_data(settings: Settings, stream, on_event) -> None:
    """
    Refresh the community data if it is older than `data_max_age`, then use it
    for every source flag the run was not given (ADR-0032). An explicit flag
    always wins; `--no-default-data` turns the defaults off.
    """
    if not (settings.no_update_data or os.environ.get("IEMOD_NO_UPDATE_DATA")):
        update_data(settings, stream=stream, on_event=on_event)
    if settings.no_default_data:
        return
    cached = datasync.data_paths(_data_dir(settings))
    if not settings.catalogue and cached.catalogue:
        settings.catalogue = [cached.catalogue]
    if not settings.rules and cached.rules:
        settings.rules = list(cached.rules)
    if not settings.mod_db and cached.mod_db:
        settings.mod_db = cached.mod_db
    if not settings.order_catalogue and cached.order_catalogue:
        settings.order_catalogue = cached.order_catalogue
    if not settings.eet_sequence and cached.eet_sequence:
        settings.eet_sequence = cached.eet_sequence
    if not settings.releases and cached.releases:
        settings.releases = cached.releases


def _before_eet_core(settings: Settings):
    """What may precede the EET core: BWS-NG's sequence if given, else EET's rule."""
    if not settings.eet_sequence:
        return before_eet_core(None)
    try:
        with open(settings.eet_sequence, encoding="utf-8") as fh:
            return before_eet_core(json.load(fh))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read --eet-sequence {settings.eet_sequence}: "
                          f"{exc}") from exc


class _LazyClient:
    """
    The HTTP client, built on first use. Finding a credential runs `gh` and
    git's credential helper; a cache checked within the hour needs neither.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: Optional[HttpClient] = None

    def _get(self) -> HttpClient:
        if self._client is None:
            self._client = _http_client(self._settings)
        return self._client

    def get_json(self, url: str):
        return self._get().get_json(url)

    def read_bytes(self, url: str, limit: Optional[int] = None) -> bytes:
        return self._get().read_bytes(url, limit=limit)


def _http_client(settings: Settings) -> HttpClient:
    credential = resolve_credential(token_file=settings.token_file,
                                    use_gh=not settings.no_gh_cli,
                                    use_git_credential=not settings.no_git_credential,
                                    oauth_client_id=settings.oauth_client_id)
    return HttpClient(token=credential.token, allow_http=settings.allow_http,
                      timeout=settings.timeout, max_bytes=settings.max_bytes,
                      retries=settings.retries)


def list_mods(manifest: Optional[str] = None, catalogues: Sequence[str] = (),
              mod_db: Optional[str] = None, allow_http: bool = False,
              releases: Optional[str] = None,
              weidu_logs: Sequence[str] = ()) -> List[AvailableMod]:
    """
    Every mod the given sources know about, one entry each, sorted by name.

    `releases` is krion64's version_cache.json (its sibling mods/ adds the
    versions krion64 records); with `weidu_logs` ("PATH" or "PATH:GAME") each
    mod also says what is installed and whether a newer version exists (M2d).
    """
    if manifest and (os.path.exists(manifest) or not (catalogues or mod_db)):
        loaded = load_manifest(manifest, allow_http=allow_http)
    else:
        loaded = Manifest()       # a catalogue alone is enough to choose from
    release_cache, versions = _releases(releases)
    return available_mods(loaded, CatalogueSet.load(catalogues),
                          ModDatabase.load(mod_db) if mod_db else None,
                          releases=release_cache, versions=versions,
                          installed=_installed_versions(weidu_logs))


def _releases(path: Optional[str]):
    if not path:
        return {}, []
    try:
        with open(path, encoding="utf-8") as fh:
            cache = parse_release_cache(json.load(fh))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"--releases: cannot read {path}: {exc}") from None
    krion = os.path.join(os.path.dirname(os.path.abspath(path)), "mods")
    return cache, ([ModDatabase.load(krion, origin="krion64")]
                   if os.path.isdir(krion) else [])


def _installed_versions(specs: Sequence[str]) -> dict:
    """Mod key -> the version its WeiDU.log records, where it records one."""
    if not specs:
        return {}
    installed = parse_weidu_files([split_log_spec(spec) for spec in specs])
    return {normalize_key(mod.folder): mod.version
            for mod in installed.mods.values() if mod.version}


def load_selection(path: str) -> Selection:
    """Read and validate a selection.json; ConfigError names where and why."""
    with open(path, encoding="utf-8") as fh:
        return parse_selection(fh.read(), source=path)


def selection_of_logs(specs: Sequence[str]) -> Selection:
    """The selection that says what these WeiDU.logs ("PATH" or "PATH:GAME") say."""
    logs = []
    for spec in specs:
        path, game = split_log_spec(spec)
        logs.append((game, parse_weidu_files([(path, game)])))
    return selection_from_logs(logs)


_MAX_TEXT_BYTES = 8 * 1024 * 1024
_WEIDU_OS = "win32" if sys.platform.startswith("win") else (
    "osx" if sys.platform == "darwin" else "unix")


def _text_under(root: str, relative: str) -> Optional[str]:
    """
    A mod's text file by the path its tp2 writes, as WeiDU on Windows finds it:
    case-insensitive, separators either way. Nothing outside `root` is read.
    """
    path = os.path.realpath(root)
    for part in relative.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == ".." or not os.path.isdir(path):
            return None
        direct = os.path.join(path, part)
        if not os.path.exists(direct):
            matches = [e for e in os.listdir(path) if e.lower() == part.lower()]
            if not matches:
                return None
            direct = os.path.join(path, matches[0])
        path = direct
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(real):
        return None
    if os.path.getsize(real) > _MAX_TEXT_BYTES:
        return None
    with open(real, "rb") as fh:
        data = fh.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")     # pre-EE mods: Windows-1252 and kin


def describe_mods(target: str = "./Mods", preferences: Sequence[str] = ()) -> List[dict]:
    """
    Every staged mod's components, named as WeiDU would name them (M2e).

    `target` is the --target directory; WeiDU runs from it, so a tp2's paths
    are read relative to it. `preferences` are language codes in order.
    """
    root = os.path.abspath(target)
    preferences = parse_preferences(preferences) if preferences else []
    out = []
    for path in find_tp2_files(root):
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        text = _text_under(root, relative)
        if text is None:
            continue
        entry = {"tp2": relative}
        entry.update(tra.describe(text, lambda p: _text_under(root, p),
                                  preferences, weidu_os=_WEIDU_OS))
        out.append(entry)
    return out


# --------------------------------------------------------------- internals
def load_bio_code(path: str) -> bio.BioModlist:
    """A BIO share code from a file (the code alone, as BIO copies it)."""
    with open(path, encoding="utf-8") as fh:
        return bio.decode_share_code(fh.read(bio.MAX_CODE_CHARS + 1))


def bio_code_of(selection: Selection, base: Optional[bio.BioModlist] = None) -> str:
    """The BIO-MODLIST-V1 code for `selection`, keeping `base`'s other fields."""
    return bio.encode_share_code(bio.modlist_from_selection(selection, base, __version__))


def _use_selection(settings, workdir: str) -> Optional[bio.BioModlist]:
    """
    Turn --selection or --bio-code into the WeiDU.log inputs every planner
    already reads.

    A selection says what a log says (ADR-0030), so it is written out as one log
    per install and passed on as `-w PATH:GAME`. The logs live only for the run.
    Returns the imported BIO payload, so an export can keep its other fields.
    """
    given = [flag for flag, value in (("--selection", settings.selection),
                                      ("--bio-code", settings.bio_code),
                                      ("--weidu-log", settings.weidu_log)) if value]
    if len(given) > 1:
        raise ConfigError(f"{' and '.join(given)} each define what is wanted: "
                          f"give one of them")
    imported = None
    if settings.bio_code:
        imported = load_bio_code(settings.bio_code)
        selection = imported.to_selection()
    elif settings.selection:
        with open(settings.selection, encoding="utf-8") as fh:
            selection = parse_selection(fh.read(), source=settings.selection)
    else:
        return None
    for log in selection.weidu_logs():
        path = os.path.join(workdir, log.name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(log.text)
        settings.weidu_log.append(f"{path}:{log.game}")
    return imported


def _emit_bio_code(settings, imported, stream) -> None:
    """Write the run's input as a BIO share code (--emit-bio-code)."""
    if not settings.emit_bio_code:
        return
    if not settings.weidu_log:
        raise ConfigError("--emit-bio-code converts what is wanted: give --weidu-log, "
                          "--selection or --bio-code")
    code = bio_code_of(selection_of_logs(settings.weidu_log), imported)
    if settings.emit_bio_code == "-":
        stream.write(code + "\n")
        return
    with open(settings.emit_bio_code, "w", encoding="utf-8") as fh:
        fh.write(code + "\n")
    if not settings.quiet:
        print(f"  bio code    : wrote {settings.emit_bio_code}", file=stream)


def _list_mods(settings, stream) -> int:
    """What a selection screen offers: every mod any given source knows."""
    document = mods_document(list_mods(settings.manifest, settings.catalogue,
                                       settings.mod_db, settings.allow_http,
                                       settings.releases, settings.weidu_log))
    if settings.list_mods == "-":
        stream.write(document)
    else:
        with open(settings.list_mods, "w", encoding="utf-8") as fh:
            fh.write(document)
        if not settings.quiet:
            print(f"  mods        : wrote {settings.list_mods}", file=stream)
    return 0


def _describe_mods(settings, stream) -> int:
    """What a component screen shows: the staged mods' components, by name."""
    document = json.dumps({"schema_version": SCHEMA_VERSION,
                           "mods": describe_mods(settings.target,
                                                 settings.language_preference or ())},
                          indent=2, ensure_ascii=False) + "\n"
    if settings.describe_mods == "-":
        stream.write(document)
    else:
        with open(settings.describe_mods, "w", encoding="utf-8") as fh:
            fh.write(document)
        if not settings.quiet:
            print(f"  components  : wrote {settings.describe_mods}", file=stream)
    return 0


def _render_updates(settings, stream) -> None:
    """
    The update notice: installed mods some source names a newer version of.
    Silent without --releases data or a WeiDU.log; a mod whose versions cannot
    be ranked is counted, never reported as an update.
    """
    if not (settings.releases and settings.weidu_log):
        return
    mods = [m for m in list_mods(settings.manifest, settings.catalogue, settings.mod_db,
                                 settings.allow_http, settings.releases, settings.weidu_log)
            if m.installed]
    newer = [m for m in mods if m.update_available]
    unknown = sum(1 for m in mods if m.update_available is None)
    print(f"  updates     : {len(newer)} of {len(mods)} installed mods with a version "
          f"have a newer one" + (f" ({unknown} not comparable)" if unknown else ""),
          file=stream)
    for mod in newer:
        latest = mod.latest
        if latest is None:
            continue
        where = ", ".join(x for x in (latest.origin, latest.date) if x)
        print(f"    {mod.tp2:<24} {mod.installed} -> {latest.version} ({where})", file=stream)


@contextlib.contextmanager
def _event_sink(path, stream, callback=None):
    """
    The events go to `callback` and, with --events, to a file as one JSON
    object per line, flushed so a reader sees each as it happens.
    """
    if not path:
        yield callback
        return
    with contextlib.ExitStack() as stack:
        out = (stream if path == "-"
               else stack.enter_context(open(path, "w", encoding="utf-8")))

        def write(event: dict) -> None:
            out.write(json.dumps(event, sort_keys=True) + "\n")
            out.flush()
            if callback is not None:
                callback(event)
        yield write


def _emit_selection(settings, stream) -> None:
    """Write the --weidu-log input as the selection.json a UI would save."""
    if not settings.emit_selection:
        return
    if not settings.weidu_log:
        raise ConfigError("--emit-selection converts --weidu-log input: give one")
    with open(settings.emit_selection, "w", encoding="utf-8") as fh:
        fh.write(selection_to_json(selection_of_logs(settings.weidu_log)))
    if not settings.quiet:
        print(f"  selection   : wrote {settings.emit_selection}", file=stream)


@dataclass
class RuleAnalysis:
    """
    What the rule pass produced, passed explicitly to whatever needs it next.

    This used to be stashed on `_check_rules.last`, a function attribute, so the
    order planner and the conflict report could reach it. That is global mutable
    state dressed as a cache: it makes the call order load-bearing and invisible,
    it cannot be constructed in a test without calling the CLI, and mypy is right
    to refuse it. An empty instance means "no rules were loaded", which every
    consumer already handles.
    """
    ruleset: Optional[RuleSet] = None
    context: Optional[Context] = None
    installs: Sequence[Install] = ()
    findings: List[dict] = field(default_factory=list)
    # The staged mods' own tp2 constraints (ADR-0025): part of `ruleset` as
    # rules, and kept whole for the install simulation.
    constraints: Optional[ModConstraints] = None

    def __bool__(self) -> bool:
        return self.ruleset is not None


def _check_rules(settings, installed, stream) -> RuleAnalysis:
    """
    Check each WeiDU log against the rule set, separately.

    One log is one game install: a mod in the BGEE log neither conflicts with
    nor orders against a mod in the EET log, so the logs are never merged for
    this.
    """
    if not settings.weidu_log:
        return RuleAnalysis()
    # A staged mod's own tp2 is a rule source in its own right - checked even
    # when no community rule set is given.
    constraints = _staged_constraints(
        settings, [(split_log_spec(spec)[0], None) for spec in settings.weidu_log])
    if not settings.rules and not constraints.by_mod:
        return RuleAnalysis(constraints=constraints)
    ruleset = RuleSet.load(settings.rules) if settings.rules else RuleSet()
    if constraints.by_mod:
        ruleset.rules.extend(tp2_rules(constraints))
        if not settings.quiet:
            print(f"  own tp2s    : {constraints.summary()}", file=stream)
    context = _rule_context(settings, installed, ruleset, stream)
    installs = []
    for spec in settings.weidu_log:
        path, game = split_log_spec(spec)
        installs.append(Install.from_log(parse_weidu_files([(path, game)]),
                                         label=os.path.basename(path)))
    # `rule` is the Rule object the finding drilled down from - useful in
    # process, not serialisable, and the conflict report carries it properly.
    findings = [{"id": f.id, **{k: v for k, v in vars(f).items() if k != "rule"}}
                for f in check_all(installs, ruleset, context)]
    if not settings.quiet:
        age = ""
        if ruleset.updated:
            age = f", updated {ruleset.updated}"
            if (ruleset.age_days or 0) > 180:
                age += f" — {ruleset.age_days} days old, verify before acting"
        undirected = (f", {ruleset.undirected} order-sensitive pair(s) not "
                      f"evaluated (no direction recorded)"
                      if ruleset.undirected else "")
        print(f"  rules       : {len(ruleset)} loaded{age}; "
              f"{len(findings)} finding(s){undirected}", file=stream)
    for warning in ruleset.warnings[:5]:
        print(f"[warning] {warning}", file=sys.stderr)
    return RuleAnalysis(ruleset=ruleset, context=context, installs=installs,
                        findings=findings, constraints=constraints)


def _log_roles(specs):
    """
    Decide which input log is the EET install and which is the pre-EET BG1 one.

    An EET setup is two installs, and the plan has to keep them apart. The log
    that installs the EET core IS the merged-game log; the other is the BG1:EE
    phase. `-w PATH:EET` states it outright; otherwise it is inferred from the
    log's own contents, never from the filename - `WeiDUBGEE.log`,
    `weidu-bgee.log` and `bg1.log` are all names people actually use.
    """
    roles, eet_logs = [], []
    for spec in specs:
        path, game = split_log_spec(spec)
        parsed = parse_weidu_files([(path, game)])
        role = EET_LOG if (parsed.game or "").upper() == "EET" else PRE_EET_LOG
        if role == EET_LOG:
            eet_logs.append(path)
        roles.append((path, role))

    if len(eet_logs) > 1:
        raise ConfigError(
            "two logs both look like the EET install (" + ", ".join(eet_logs) +
            "). Name the pre-EET one explicitly, e.g. -w WeiDUBGEE.log:BGEE")
    if not eet_logs and len(roles) > 1:
        raise ConfigError(
            "no log installs the EET core, so which one is the merged game is a "
            "guess. Say so explicitly: -w WeiDU.log:EET")
    return roles


def _plan_order(settings, analysis: "RuleAnalysis", stream):
    """Build the rule-compliant install order, if asked for."""
    if not getattr(settings, "plan_order", None):
        return None
    if not settings.weidu_log:
        raise ConfigError("--plan-order needs at least one --weidu-log to order")
    if not settings.order_catalogue:
        raise ConfigError(
            "--plan-order needs --order-catalogue PATH: a krion64 data directory "
            "(categories.json + mods/*.json). Without it there is no reference "
            "order to sort towards, and the tool will not invent one")

    index = OrderIndex.load(settings.order_catalogue)
    # Reuse the ruleset the checker just built: it carries the per-mod ordering
    # metadata read from installed .iemod/.ini files on top of --rules. Planning
    # against a thinner ruleset than the check uses would emit a plan the very
    # next check rejects.
    ruleset, context = analysis.ruleset, analysis.context
    if ruleset is None:
        ruleset = RuleSet.load(settings.rules) if settings.rules else RuleSet()
    specs = _log_roles(settings.weidu_log)
    # What each staged mod's own tp2 enforces (ADR-0025) is already in the rule
    # set the check built; the simulation needs the constraints themselves.
    constraints = analysis.constraints or _staged_constraints(settings, specs)
    plan = plan_order(specs, index, ruleset, context,
                      include_optional=settings.include_optional,
                      reassign_phase=settings.reassign_phase)
    games = _phase_games(settings, specs)
    resolution = None
    if settings.decisions or settings.resolve_conflicts:
        resolution = ResolutionResult()
        decided: set = set()
        if settings.decisions:
            # The player's answers first: a choice they made is never second-
            # guessed by the automatic resolution that follows.
            with open(settings.decisions, encoding="utf-8") as fh:
                decisions = parse_decisions(fh.read(), source=settings.decisions)
            report = build_conflict_report(plan.installs(), ruleset or RuleSet(),
                                           context, plan)
            resolution.extend(apply_decisions(plan, report, decisions, ruleset, context))
            decided = decisions.findings
    if settings.resolve_conflicts and resolution is not None:
        # Judged on the PLAN's own installs, so the report's log labels are the
        # plan's roles, and re-verified by the same rules afterwards.
        report = build_conflict_report(plan.installs(), ruleset or RuleSet(),
                                       context, plan)
        resolution.extend(resolve_conflicts(plan, report, ruleset, context, skip=decided))
        if constraints.by_mod:
            resolution.extend(resolve_refusals(plan, constraints, games, ruleset, context,
                                               before_core=_before_eet_core(settings)))
    plan.resolution = resolution
    languages = None
    if settings.language_preference:
        languages = apply_language_preference(plan, os.path.abspath(settings.target),
                                              settings.language_preference)
    written = plan.write(settings.plan_order)
    if resolution is not None:
        path = os.path.join(settings.plan_order, "RESOLUTION.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(resolution.as_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")
        written.append(path)
    if not settings.quiet:
        print(f"  order plan  : {index.origin} "
              f"({len(index)} mods, {len(index.categories)} categories); "
              f"{plan.edges} ordering constraint(s)", file=stream)
        for path in written:
            print(f"                wrote {path}", file=stream)
        if resolution is not None:
            print("\n" + resolution.render(), file=stream)
        if languages is not None:
            print("\n" + languages.render(), file=stream)
    if settings.simulate:
        plan.simulation = simulate_install(
            {role: steps_of(units) for role, units in plan.logs.items()},
            constraints.by_mod, games=games, eet_rules=constraints.eet)
        if not settings.quiet:
            print("\n" + plan.simulation.render(), file=stream)
    if settings.bgee_dir:
        plan.game_report = verify_eet(
            settings.bgee_dir, settings.bg2ee_dir,
            plan_mods={unit.key for unit in plan.logs.get(PRE_EET_LOG, [])})
        print("\n" + plan.game_report.render(), file=stream)
    if settings.emit_installer:
        _emit_installer(settings, plan, stream)
    return plan


def _staged_constraints(settings, specs):
    """The tp2 constraints of every planned mod that is already staged."""
    mods = []
    for path, _role in specs:
        parsed = parse_weidu_files([(path, None)])
        for mod in parsed.mods.values():
            for component in mod.components:
                mods.append((tp2_key(component.tp2_file), mod.folder,
                             component.tp2_file))
    target = os.path.abspath(settings.target)
    if not os.path.isdir(target):
        return ModConstraints()
    return load_constraints(target, mods)


def _phase_games(settings, specs):
    """
    Which game each planned log installs on. The pre-EET log is BGEE and the
    EET log starts as BG2EE - unless a single non-EET log names its game
    (`-w WeiDU.log:BG2EE`), which then decides.
    """
    games = {}
    for spec, (_path, role) in zip(settings.weidu_log, specs):
        _p, game = split_log_spec(spec)
        if role == PRE_EET_LOG and game and len(specs) == 1:
            games[role] = game
    return games


def _emit_installer(settings, plan, stream) -> None:
    """Write the scripts that hand the plan to mod_installer (ADR-0022)."""
    target = os.path.abspath(settings.target)
    plan_dir = os.path.abspath(settings.plan_order)
    try:
        mods_ref = os.path.relpath(target, plan_dir)
    except ValueError:            # Windows: the mods and the plan on different drives
        mods_ref = target
    installer = build_installer(plan, mods_relpath=mods_ref.replace(os.sep, "/"),
                                mods_dir=target, language=_game_language(settings))
    written = installer.write(plan_dir)
    if settings.quiet:
        return
    print(f"\nINSTALLER ({installer.mode}: mod_installer + WeiDU; review, then run)",
          file=stream)
    for path in written:
        print(f"  wrote {path}", file=stream)
    for problem in installer.problems:
        print(f"  !! {problem}", file=stream)
    for warning in installer.warnings:
        print(f"   ! {warning}", file=stream)
    games = ("BGEE_DIR=<BGEE game> BG2EE_DIR=<BG2EE game>"
             if installer.mode == "eet" else "GAME_DIR=<game>")
    script = "install-eet" if installer.mode == "eet" else "install"
    print(f"  run on a CLEAN copy of the game(s):\n"
          f"    Linux/macOS: {games} sh {os.path.join(plan_dir, script + '.sh')}\n"
          f"    Windows    : set the same variables, then "
          f"{os.path.join(plan_dir, script + '.cmd')}", file=stream)


def _conflict_report(settings, analysis: "RuleAnalysis", plan):
    """
    The component-level view: what actually fights what, and the smallest fix.

    Ordering answers "in what sequence"; this answers "and what still clashes
    once the sequence is right". Findings the plan already resolves are marked
    as such instead of being reported twice.
    """
    if analysis.ruleset is None or not analysis.installs:
        return None
    report = build_conflict_report(analysis.installs, analysis.ruleset,
                                   analysis.context, plan)
    resolution = getattr(plan, "resolution", None)
    if resolution is not None:
        # What the plan settled is not outstanding work: an accepted finding is
        # withheld with the player's reason, a removed side is fixed in the plan.
        accepted = {a.finding_id: a.why for a in resolution.accepted}
        removed = {r.finding_id: r for r in resolution.removed if r.finding_id}
        for finding in report.findings:
            if finding.id in accepted:
                finding.suppressed = f"accepted in decisions.json: {accepted[finding.id]}"
            elif finding.id in removed:
                gone = removed[finding.id]
                finding.fixed_by_plan = True
                finding.remedy = (f"{gone.mod} " + ", ".join(f"#{n}" for n in gone.components)
                                  + (" removed by your decision" if gone.by == "decision"
                                     else " removed by --resolve-conflicts"))
    if settings.conflict_report:
        report.write_json(settings.conflict_report)
    return report


def _rule_context(settings, installed, ruleset, stream):
    """
    Gather what is needed to judge whether a rule is still current: the version
    of each installed mod, the versions the rules were built against, mods that
    ship their own ordering metadata, and any verified suppressions.
    """
    target = os.path.abspath(settings.target)
    context = Context(suppressions=load_suppressions(settings.suppress),
                      include_optional=settings.include_optional)

    if settings.mod_db:
        context.baseline = ModDatabase.load(settings.mod_db)
        if not settings.quiet:
            print(f"  mod database: {len(context.baseline)} mods "
                  f"(versions the rules were written against)", file=stream)

    state = State.load(target)
    for key, entry in state.mods.items():
        if entry.get("mod_version"):
            context.installed_versions[normalize_key(key)] = entry["mod_version"]

    # Anything already on disk can be read directly, which is better than the
    # state file: it reflects what is installed now, not what we last fetched.
    for mod in installed.mods.values():
        folder_key = normalize_key(mod.folder)
        mod_dir = os.path.join(target, mod.folder)
        if not os.path.isdir(mod_dir):
            continue
        info = read_mod_tp2(mod_dir, mod.tp2_file)
        if info and info.version:
            context.installed_versions[folder_key] = info.version
        meta = find_metadata(mod_dir, mod.folder)
        if meta and meta.has_order_hints:
            context.mods_with_own_ini.add(folder_key)
            ruleset.add_metadata_order(mod.folder, meta.before, meta.after)
    return context


def _game_language(settings) -> str:
    """--game-language, else the first preferred mod language, else en_US."""
    if settings.game_language:
        return str(settings.game_language)
    return str(settings.language_preference[0]) if settings.language_preference else "en_US"


def _require_plan(settings) -> None:
    """Flags that act on an install plan are meaningless without one."""
    if settings.language_preference:
        settings.language_preference = parse_preferences(settings.language_preference)
    if bool(settings.bgee_dir) != bool(settings.bg2ee_dir):
        raise ConfigError("--bgee-dir and --bg2ee-dir go together: an EET install "
                          "needs both games")
    if settings.plan_order:
        return
    for flag, given in (("--resolve-conflicts", settings.resolve_conflicts),
                        ("--decisions", settings.decisions),
                        ("--emit-installer", settings.emit_installer),
                        ("--simulate", settings.simulate),
                        ("--bgee-dir", settings.bgee_dir),
                        ("--bg2ee-dir", settings.bg2ee_dir),
                        ("--language-preference", settings.language_preference)):
        if given:
            raise ConfigError(f"{flag} works on an install plan: add "
                              f"--plan-order DIR (and --order-catalogue)")


def _analyse(settings, installed, stream):
    """Rule check, order plan and conflict report, over what is staged now."""
    analysis = _check_rules(settings, installed, stream)
    order_plan = _plan_order(settings, analysis, stream)
    return analysis.findings, order_plan, _conflict_report(settings, analysis, order_plan)


def _run(settings, stream, config=None, on_event=None, cancel=None) -> "Outcome":
    if settings.list_mods:
        _list_mods(settings, stream)
        return Outcome(exit_code=0)
    if settings.describe_mods:
        _describe_mods(settings, stream)
        return Outcome(exit_code=0)
    _require_plan(settings)
    _emit_selection(settings, stream)
    target = os.path.abspath(settings.target)
    manifest = load_manifest(settings.manifest, allow_http=settings.allow_http)

    if settings.weidu_log:
        installed = parse_weidu_files([split_log_spec(spec) for spec in settings.weidu_log])
    else:
        installed = ParsedLog()
        if not settings.all_manifest_entries:
            raise ConfigError(
                "no --weidu-log given. Pass at least one WeiDU.log to define which "
                "mods are wanted, or --all-manifest-entries to fetch the whole "
                "catalogue.")

    plan = build_plan(installed, manifest, aliases=load_aliases(settings.aliases),
                      include_manifest_only=settings.all_manifest_entries or not settings.weidu_log,
                      accept_suggestions=settings.accept_suggestions)

    if settings.only:
        wanted = {name.lower() for name in settings.only}
        plan.items = [i for i in plan.items if i.folder.lower() in wanted]
        plan.unresolved = [i for i in plan.unresolved if i.folder.lower() in wanted]

    if settings.check_only:
        findings, order_plan, conflict_report = _analyse(settings, installed, stream)
        report = RunReport(findings=findings)
        if not settings.quiet:
            render_summary(report, target, stream=stream)
            if order_plan is not None:
                render_plan_summary(order_plan, settings.plan_order, stream)
            if conflict_report is not None:
                render_conflict_report(conflict_report, stream,
                                       show_notes=settings.show_advisories)
                if settings.conflict_report:
                    print(f"  full report written to {settings.conflict_report}",
                          file=stream)
            _render_updates(settings, stream)
        if settings.json_report:
            report.write_json(settings.json_report)
        refused = bool(order_plan is not None and (
            (order_plan.simulation and order_plan.simulation.refused)
            or (order_plan.game_report and order_plan.game_report.problems)))
        return Outcome(1 if report.blocking_findings or refused else 0,
                       report, order_plan, conflict_report)

    credential = resolve_credential(token_file=settings.token_file,
                                    use_gh=not settings.no_gh_cli,
                                    use_git_credential=not settings.no_git_credential,
                                    oauth_client_id=settings.oauth_client_id)
    client = HttpClient(token=credential.token, allow_http=settings.allow_http,
                        timeout=settings.timeout, max_bytes=settings.max_bytes,
                        retries=settings.retries)

    for warning in (config.warnings if config else []):
        print(f"[warning] {warning}", file=sys.stderr)

    if not settings.quiet:
        print(f"iemod-fetch {__version__}", file=stream)
        if config is not None and config.path:
            print(f"  config      : {config.path} ({len(config.values)} setting(s))",
                  file=stream)
        print(f"  catalogue   : {settings.manifest} ({len(manifest.sources)} entries)", file=stream)
        games = sorted({m.game for m in installed.mods.values() if m.game})
        print(f"  weidu logs  : {', '.join(settings.weidu_log) or '(none)'} "
              f"({len(installed.mods)} mods, {installed.component_count} components"
              f"{'; game: ' + ', '.join(games) if games else ''})", file=stream)
        print(f"  target      : {target}", file=stream)
        print(f"  credential  : {credential.describe()}", file=stream)
        print(f"  to process  : {len(plan.items)} resolved, "
              f"{len(plan.unresolved)} unresolved", file=stream)
        if settings.dry_run:
            print("  MODE        : dry run, nothing will be written", file=stream)
        print(file=stream)

    os.makedirs(target, exist_ok=True)
    options = Options(target_dir=target, workers=settings.workers, dry_run=settings.dry_run,
                      force=settings.force, allow_exe=settings.allow_exe,
                      accept_offsite=settings.accept_offsite, refresh=settings.refresh,
                      discovery_attempts=settings.discovery_attempts)

    catalogue = CatalogueSet.load(settings.catalogue)
    if catalogue and not settings.quiet:
        print(f"  catalogues  : {len(settings.catalogue)} file(s), {len(catalogue)} mods",
              file=stream)

    org_index = None
    if not settings.no_discovery:
        owners = load_trusted_owners(settings.trusted_owners, manifest=manifest,
                                     extra=settings.trusted_owner)
        org_index = OwnerIndex(
            client=client, owners=owners,
            cache_path=settings.owner_cache or os.path.join(target, ".owner-index.json"))
        if not settings.quiet:
            print(f"  discovery   : enabled over {len(owners)} trusted owner(s)",
                  file=stream)
    with _event_sink(settings.events, stream, on_event) as sink:
        runner = Runner(client, options, stream=None if settings.quiet else stream,
                        org_index=org_index, catalogue=catalogue or None,
                        on_event=sink, cancel=cancel)
        report = runner.run(plan)
    # Checked and planned AFTER the fetch, so the mods' own tp2s are read from
    # what this run just staged: one run takes a selection from nothing to a
    # checked plan.
    report.findings, order_plan, conflict_report = _analyse(settings, installed, stream)

    if not settings.quiet:
        render_summary(report, target, stream=stream)
        if order_plan is not None:
            render_plan_summary(order_plan, settings.plan_order, stream)
        if conflict_report is not None:
            render_conflict_report(conflict_report, stream,
                                   show_notes=settings.show_advisories)
            if settings.conflict_report:
                print(f"  full report written to {settings.conflict_report}",
                      file=stream)
        _render_updates(settings, stream)
    if settings.emit_pinned_manifest:
        payload = build_pinned_manifest(manifest, report.records,
                                        state=runner.state.mods)
        write_pinned_manifest(settings.emit_pinned_manifest, payload)
        if not settings.quiet:
            print(f"\nPinned manifest written to {settings.emit_pinned_manifest} "
                  f"({payload['pinned_entries']} of {len(payload['mods'])} entries "
                  f"carry a sha256)", file=stream)
            if settings.dry_run:
                print("  note: --dry-run downloads nothing, so only release_tag/asset "
                      "could be pinned. Re-run without --dry-run to pin sha256.",
                      file=stream)
    if settings.json_report:
        report.write_json(settings.json_report)
        if not settings.quiet:
            print(f"\nJSON report written to {settings.json_report}", file=stream)
    return Outcome(report.exit_code(allow_manual=settings.allow_manual),
                   report, order_plan, conflict_report)
