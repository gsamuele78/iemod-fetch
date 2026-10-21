# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html), where
the public surface is the CLI's flags and the JSON report schema — not the
Python API, which is internal.

## [Unreleased]

### Added
- **The wizard's first phase** (M3, ADR-0031). `iemod_fetch_gui`, a PySide6
  app installed with the `gui` extra and started with `iemod-fetch-gui
  --project FOLDER`: choose EET, BG:EE or BG2:EE, the game folders - checked
  as WeiDU's GAME_IS sees them as they are typed - and the languages; Next
  saves the project's `iemod-fetch.ini`, which the CLI reads too. It reaches
  the tool only through the api (an import-linter contract), and the CLI and
  the `.pyz` stay standard library only. Tested with pytest-qt offscreen on
  Linux and Windows in CI.
- `api.check_game_folders`, `api.languages`, `api.load_project` and
  `api.save_project`: the first phase as functions, for any front end.

### Fixed
- **A `%` in `iemod-fetch.ini`** (a path like `C:/Games/100%BG`) stopped the
  CLI with a raw configparser traceback; it is now a ConfigError that says to
  write `%%`, and the wizard writes it that way.

## [2.4.0] - 2026-10-21

The community-data release (milestone M2 of `docs/GUI-AUDIT.md`): what the
GUI's selection screen needs to show, measured against the tools that are the
ground truth. The data refreshes itself, guarded; components are named exactly
as WeiDU names them (9,889 of 9,889 names, 1,499 of 1,499 LABELs); each mod
says whether an update exists; every conflict comes with its options and
`--decisions` applies the player's; BIO share codes and Project Infinity lists
go in (BIO's own encoder and decoder agree), and the engine limits - kits,
spell slots, spell states - are measured in the game folder by WeiDU's own
rules, checked against the real WeiDU. Measured: 857 → 1,039 tests; still no
runtime dependency. Only additions to the CLI flags and JSON reports; the text
conflict report now prints ids and options for ORDER findings too.

### Added
- **The community data is kept current automatically** (ADR-0032). Each run
  refreshes a cache of lcc-docs, BigWorldSetup-NG and krion64 before it starts,
  at most once per `--data-max-age` hours (default 24), and uses it for
  `--catalogue`, `--rules`, `--mod-db` and `--order-catalogue` whenever those
  are not given. Only the `.json` files the tool reads are fetched, only the
  changed ones, each checked against its git blob hash and swapped in whole;
  offline, the last good copy is used. `--update-data` refreshes now and
  stops, `--no-update-data` stays offline, `--no-default-data` uses only the
  flags, `--data-dir` moves the cache. `api.update_data` and `api.data_status`
  for the GUI; a `data_source` event per source.

- **Guards on every community-data update.** Before a refreshed copy replaces
  the last good one, every file must be valid JSON and the copy must parse with
  the tool's own readers; a count (mods, rules, order entries) at zero or below
  half of the last good copy's - a format change upstream - refuses the update.
  The last good copy stays and the refused commit is not downloaded again. An
  accepted update reports what changed: counts before and after, mods added and
  removed, versions (BWS-NG, krion64) and catalogue statuses (lcc-docs) that
  moved. The README and guide no longer ask for `git clone`.

- **Component names, as WeiDU prints them.** `--describe-mods PATH` writes,
  for every mod staged under `--target`, its languages and its components
  named from the tp2 and its `.tra` files (`Group -> Name: VERSION`), in the
  first `--language-preference` the mod offers; `api.describe_mods` for the
  GUI; `schemas/components-v1.schema.json`. Runs no WeiDU. Each component
  also carries what WeiDU's `--list-components-json` gives - its `subgroup`
  (SUBCOMPONENT), `groups`, `labels`, `forced` - and `deprecated`, for the
  components WeiDU no longer lists: 1,499 of 1,499 identical on 109 tp2s. Measured against
  WeiDU 251's own `--list-components` on 103 real mods: 9,889 of 9,889 names
  identical (`tools/tra_oracle.py`, `tools/tra_benchmark.py`,
  docs/TESTING.md). Paths in the tp2 are matched case-insensitively and never
  outside `--target`.

- **Update notice.** Each mod's newest known version is the newest any of
  three sources names: the latest GitHub release (krion64's
  `version_cache.json`), the BWS-NG database and krion64's records. Each
  source alone agrees with the mods' own tp2 VERSION for 42-67 of 90 mods;
  the newest of the three for 79 (`tools/version_benchmark.py`,
  docs/TESTING.md). `--list-mods` gains `installed`, `latest` (version,
  origin, date, release page) and `update_available` (null when the versions
  cannot be ranked - never a guess); with `-w`, a run prints which installed
  mods have a newer version. `--releases PATH`, read from the data cache by
  default; the cache's guard now also counts the releases.

- **Conflicts come with options, and `--decisions` applies yours**
  (ADR-0033). Every conflict-report finding lists the ways to clear it -
  deselect one side, reorder, install a missing prerequisite - each with a
  stable id, its cost in components, whether a plan can apply it, and whether
  the rules recommend it (only where they decide; never on a tie). A
  `decisions.json` (`schemas/decisions-v1.schema.json`) chooses an option or
  accepts a finding with a reason; `--decisions` applies it to the plan before
  `--resolve-conflicts`, re-checks the plan, and the report then shows the
  finding as fixed or accepted. A decision whose finding is gone is reported
  as stale, never applied elsewhere. RESOLUTION.json records `by: decision`.

- **BIO share codes in and out.** `--bio-code PATH` reads a
  `BIO-MODLIST-V1:` code (Born2BSalty's Infinity Orchestrator) as what is
  wanted, in place of `-w` or `--selection`; `--emit-bio-code PATH` writes any
  input as one. Nothing is lost: a code BIO made re-encodes to the same payload,
  byte for byte,
  and exporting an imported list keeps every field BIO put in it. Checked
  both ways against BIO's own encoder and decoder. `api.load_bio_code`,
  `api.bio_code_of`. The format only; no BIO code is used.

- **Project Infinity lists in.** `--pi-list PATH:GAME` reads a PI or
  Infinity Mod Forge list (`LABEL;description`, or `folder:number;...`) as
  what is wanted. LABELs come from the staged tp2s, else from krion64's
  records - which agree with the tp2s for 708 of 732 LABELs, so each entry
  resolved that way is reported; an unresolved entry stops the run, never
  matched by its description.
- **An author's `mod-forge.json`** in a staged mod adds its conflicts,
  dependencies (with their component numbers) and known issues to the
  check; numbers as text, a number or a list.

- **Engine limits** (ADR-0034). The conflict report shows, per install, the
  kits, spell states and spell ids per level the chosen components add, with
  who adds them: kits against 256 (WeiDU's ADD_KIT limit on every EE game; the
  game has 40), spell ids against 50 per level (WeiDU's ADD_SPELL). Spell
  states are shown but never warned on: krion64's counts include states a mod
  only reads. Values checked in WeiDU's, EEex's and IESDP's sources; Infinity
  Mod Forge's 320 kits has no source. Warnings only, for every game patch.
  **Measured in the game folder** when the WeiDU.log is in one: the last kit
  number in KITLIST.2DA, the spell slots ADD_SPELL would skip, the ids in
  SPLSTATE.IDS - read from override/ or the BIFFs, by WeiDU's own rules, and
  checked against the real WeiDU in CI. krion64's counts stand in only for
  what the game does not hold yet: its spell scanner misses ADD_SPELL (an
  audit of its method found it), so an estimate is labelled as one.

### Fixed
- **Reading a mod's text stays inside the mod**, on Windows too: a tp2 path
  with a drive (`C:`), a stream or an absolute part is refused, a FIFO is
  never opened, and the resolved path is checked against the mod folder.
- **LABELs after `REQUIRE_FILE` or a multi-line `REQUIRE_PREDICATE`** are read.
- **Malformed krion64 records or JSON files** are skipped instead of stopping
  the PI-list import.
- **The version a WeiDU.log records is read.** WeiDU 251 writes
  `Name: VERSION` - one colon, despite its header's `[ : Version]` - and the
  parser looked only for ` : `, so a real log never gave a version. The
  suffix is now taken when it looks like a version and every component of the
  mod shares it: 1,409 of 1,409 component lines with a version read right, no
  option text (`cdtweaks: Use BG2 values`) taken for one. Rules about mod
  versions (the staleness check) now see installed versions.
- BIO's prompt answers at the end of a log line (`// @wlb-inputs: C:\My
  Games\BG2`) are no longer read as the mod's version.
- **Version comparison:** `Version 6.1` is 6.1, `1.0` equals `1`, and across
  sources `v071`/`0.71`, `V19`/`1.9` and `v2.02`/`2.0.2` are one release;
  `pre-v6.0` sits between 5.0 and 6.0.
- **A mod database's name** in `--list-mods` is the project, not its folder:
  `BigWorldSetup-Next-Generation`, not `mods`.
- **A component named `%like this%`** was not seen at all, and every
  component after it was numbered one too low. WeiDU reads `%...%` as a plain
  string (`BEGIN %Literal Name%` lists as "Literal Name"; checked with WeiDU
  251); so does the parser now.
- `--describe-mods`: a pre-EE `.tra` in Windows-1252 keeps its punctuation
  (`Imoen’s`, not a control character); a file that cannot be read leaves its
  names unresolved instead of stopping the run; symbolic links are not
  followed.
- The text conflict report shows the id and option of an outstanding order
  finding too, so it can be written into `decisions.json`.
- **Component numbers without DESIGNATED** are the previous number + 1, as
  WeiDU numbers them, not their position. A tp2 that designates some
  components and not others (EEUITweaks) had its
  constraints attached to the wrong numbers. Also read now: FORCED_SUBCOMPONENT
  groups, and `BEGIN` with the name on the next line (LCA).

### Changed
- **What may go on BG2:EE before the EET core comes from BWS-NG.** Its
  `games/eet.json` (maintained, last changed 2026-02-24) orders the EE
  Fixpack, `correctfrbg2ee` and `bws-fr-fixpack` before `eet:0`; EET's readme
  names only the Fixpack. `--resolve-conflicts` now moves any of them that
  refuses EET before the core instead of dropping it. The file is read from
  the data cache, or `--eet-sequence PATH`; without it, EET's readme rule
  stands as before.
- **`--plan-order` no longer needs `--order-catalogue`**, and checks use the
  community rules without setup, once the cache holds them. A run that gave no
  rules may therefore now report findings; `--no-default-data` restores the
  previous behaviour.

### Build
- The nightly "upstream rule data still parses" job became
  `community-data.yml`: the real refresh against GitHub, twice (the second must
  fetch nothing), then the parse floors. It also runs on pull requests that
  change the refresh.
- **macOS is informational, not a gate.** The CI gate (`ci.yml`), which the
  release re-runs, is Linux and Windows; the macOS test jobs moved to
  `macos.yml`, which runs on every pull request and on `main` but blocks
  neither. macOS runners stopped being assigned to this repository on
  2026-10-21 and held this release; the owner decided they should not.

## [2.3.0] - 2026-10-21

The backend release (milestone M1 of `docs/GUI-AUDIT.md`): everything the
command line does is now a public API (`iemod_fetch.api`) that the PySide6 GUI
will call, and a choice of mods no longer needs a WeiDU.log. Mods can be listed
from the catalogues, every JSON output is versioned with stable ids, progress
is reported as events and a run can be cancelled. Measured: 784 → 857 tests;
five architecture contracts, one of them keeping the CLI free of logic. Only
additions to the CLI flags and JSON reports, so existing scripts keep working;
the one new behaviour to know is exit code 130 for a cancelled run.

### Changed
- **Releases are automatic.** Merging a release pull request (a new
  `## [X.Y.Z]` section and the matching `__version__`) builds, attests, tags
  `vX.Y.Z` on that merge and publishes the GitHub release, with the changelog
  section as its notes. Nobody tags by hand. An older version without a release
  is published with *Run workflow* and its `version`. PyPI publishing is opt-in
  through the `PYPI_PUBLISH` repository variable. This is the method of
  R-studioConf's ADR-0006, adapted (ADR-0027).
- **One run goes from nothing to a checked plan.** A run that downloads now
  checks the rules, plans the order and builds the conflict report *after* the
  downloads, so the mods' own tp2 constraints and languages are read from what
  it just staged. Before, they were read first, and a fresh selection needed a
  second run to be checked (M1). `--check-only` is unchanged.

### Added
- **selection.json** (`--selection`, `--emit-selection`): the mods, components
  and languages wanted, without a WeiDU.log. One install, or BGEE + EET for an
  EET setup, in install order. It converts to and from WeiDU.log without loss,
  so every mode (fetch, check, plan) accepts it. Validated strictly: unknown
  keys, unknown games and tp2 paths leaving their folder are refused. JSON
  Schema in `schemas/selection-v1.schema.json` (ADR-0030, milestone M1).
- **`--list-mods PATH`**: every mod the manifest, the lcc-docs catalogues and
  the BWS-NG/krion64 mod database know about, one entry per mod with games,
  categories, rating, status, last update, version, advisories and each
  source's URLs and sha256. No WeiDU.log needed, nothing downloaded; a
  catalogue alone is enough. Schema in `schemas/mods-v1.schema.json` (M1).
- **Versioned JSON reports with stable ids.** `--json-report`,
  `--conflict-report` and `RESOLUTION.json` carry `schema_version: 1`. Every
  rule finding (`rule-…`) and conflict finding (`conflict-…`) has an `id`
  derived only from what it is about, so the same conflict keeps its id across
  runs. What `--resolve-conflicts` removes or leaves to you names the
  `finding_id` it settles. Schemas in `schemas/` (ADR-0030, M1). Fields were
  only added; existing readers are unaffected.
- **Progress events and cancellation.** `--events PATH` (`-` for stdout)
  writes one JSON object per line as the run goes: `run_started`,
  `mod_started`, `download_progress` (bytes and total, every 256 KiB),
  `mod_finished`, `run_finished`. The same events reach a `Runner`'s
  `on_event` callback, and a `cancel` event stops the run: no new mod starts,
  a download in flight stops at its next chunk without leaving a file, the
  mods it reached are marked `cancelled`, and the exit code is 130. Ctrl-C now
  stops downloads in flight the same way instead of waiting for them. Schema
  in `schemas/events-v1.schema.json` (ADR-0030, M1).
- **Stable error codes.** Every error class has a `code` (`checksum_mismatch`,
  `not_an_archive`, `http_status`, `unresolved`, `cancelled`, ...), and each
  record of the JSON report carries `error_code` when the mod did not succeed
  (plus `filesystem` and `internal`). A front end decides what to show from the
  code instead of parsing the message. The codes are pinned by
  `tests/test_error_codes.py` (ADR-0030, M1).
- **A public API, `iemod_fetch.api`** (ADR-0029): `Settings` (one field per
  command-line option, same name and default), `run(settings, stream=None,
  on_event=None, cancel=None) -> Outcome` (exit code, run report, order plan,
  conflict report), `list_mods`, `load_selection`, `selection_of_logs`. The
  command line is now a thin client of it, and an import-linter contract
  keeps it that way: `cli.py` may not import the planners, the runner or the
  formats. The GUI will call the same functions. This completes milestone M1.
- **Weekly check of the pinned test toolchain** (`upstream-versions.yml`):
  WeiDU and mod_installer are compared with upstream, and an issue opens for
  each one behind, with how to bump it. Dependabot cannot see those two pins.
  Its GitHub Actions updates now come grouped in one pull request (ADR-0028).
- **Published release notes follow CHANGELOG.md.** Each push to `main`
  rewrites a release body whose changelog section has changed, keeping its
  verification block (`tools/release_notes.py`).
- **Back-fills from the workflow itself.** Versions listed in `BACKFILL` are
  released by the next automatic run once the newest version is tagged. A tag
  on an older commit needs the `RELEASE_TOKEN` secret; without it the run
  skips with a notice instead of failing.

### Fixed
- **The 2.2.0 notes lost the start of the `--simulate` entry** (a text edit
  cut it). The section is restored, `tests/test_changelog.py` now rejects such
  stumps and unpaired bold markers, and the release notes are read from the
  current CHANGELOG.md, so *Run workflow* with `version` = `2.2.0` republishes
  them corrected.
- **The release step was refused with 403** for both 2.2.0 and 2.1.0, after
  the build and attestation had passed. GITHUB_TOKEN cannot create a tag on a
  commit whose workflow files differ from main's. Now main's head is tagged
  when nothing shipped changed since the version commit, so 2.2.0 releases
  with no token. A back-fill such as 2.1.0 stops early with the two ways out:
  push the tag by hand and then run the workflow for that version, or add a
  `RELEASE_TOKEN` secret (docs/RELEASING.md).
- **The release build ran the wrong `build`.** `python -m build` in the
  repository root imports the repository's own `build.py` (the zipapp script)
  instead of PyPA's build, so no wheel or sdist was made and the first automatic
  release stopped at "cp: cannot create regular file 'dist/'". The workflow now
  calls `pyproject-build`; the whole build step was re-run locally on 46eb8cb.
- **The release workflow could never run.** It called `ci.yml` as a reusable
  workflow, but `ci.yml` had no `workflow_call` trigger. It also shared a
  concurrency group with main's own CI run, so either could cancel the other.

### Build
- **GitHub Actions updated by Dependabot** (#10), still pinned by commit SHA:
  checkout v4 → v7.0.1, setup-python v5 → v7.0.0, upload-artifact v4 → v7.0.2,
  download-artifact v4 → v8.0.2, attest-build-provenance v1 → v4.2.2,
  action-gh-release v2 → v3.0.3, codeql-action v3 → v4.39.0. This clears the
  Node 20 deprecation warnings. The release-only actions (download-artifact,
  attest-build-provenance, action-gh-release) are first exercised by a release
  run; a dry run is *Run workflow* with a released `version` and `dry_run`.
- **The release pipeline is rehearsed on pull requests** that change it: the
  gate, build and attestation run on the pull request's own commit, and nothing
  is tagged or published. A Dependabot bump of a release-only action is tested
  before it merges (ADR-0027).

### Documentation
- **GUI audit** (`docs/GUI-AUDIT.md`): what the CLI still lacks before a UI
  can sit on it, what BIO, BWS-NG, lcc-docs, krion64 and mod_installer do and
  what of it may be reused, and a plan in milestones with acceptance tests.
  Accepted: ADR-0029 (a phased wizard that ends by installing), ADR-0030
  (a versioned JSON contract) and ADR-0031 (a PySide6 desktop GUI, packaged
  apart from the dependency-free CLI).

## [2.2.0] - 2026-10-21

The install-time release: the plan is now checked the way WeiDU will run it,
against the games it will run on, and that check is itself checked by the real
WeiDU. Measured: 761 → 784 tests (3 of them run the real WeiDU 251 and
mod_installer); branch coverage 91% → 92%; on the mock EET install, refusals
WeiDU would hit 1 → 0, with EEFixPack kept instead of dropped.

### Added
- **`--bgee-dir` / `--bg2ee-dir`: the game folders, verified.** Each folder is
  identified exactly as WeiDU's GAME_IS does it (marker resources in override/
  and chitin.key); a swapped pair, the same folder twice, an already-EET game, a
  modded BG2:EE and a BG:EE without Siege of Dragonspear are refused; SoD still
  in its `sod-dlc` archive (GOG/Steam) requires DlcMerger in the plan. Never
  written to. Patch level is reported as not checked (ADR-0026).
- **The real WeiDU as test oracle** (`tests/test_real_weidu.py`, and a CI job):
  synthetic game folders - no game data - on which WeiDU v251 refuses exactly
  what `--simulate` predicts, installs the resolved plan to the last component,
  and the generated `install-eet.sh` runs through the real mod_installer into
  both games. The toolchain is pinned: WeiDU by sha256, mod_installer by commit.
- **`--simulate`: walk the plan the way WeiDU will run it.** Each component's
  own tp2 constraints (REQUIRE/FORBID_COMPONENT, GAME_IS, ENGINE_IS,
  GAME_INCLUDES, MOD_IS_INSTALLED, body-level `NOT GAME_IS … ABORT`) are checked
  in plan order on the game it lands on: the BGEE log on BGEE, the EET log on
  BG2EE turning into EET once the EET core is in. Every component WeiDU would
  refuse is listed with the flag that refuses it. `--check-only` exits 1 if
  anything would be refused (ADR-0025).
- **The staged mods' own tp2s as rules** (origin `mod tp2`): a REQUIRE orders
  the required component first and is a dependency; a one-sided FORBID orders
  the declaring component first and warns that coexistence is not stated; a
  mutual FORBID is an incompatibility. Loaded whenever mods are staged, with or
  without `--rules`.
- **EET's merge check**, read from the staged EET (`tbl/compatibility.tbl` and
  its wrong-option `PATCH_FAIL`s): a BG:EE mod EET cannot import is found
  before the install, not at the merge.
- **`--resolve-conflicts` removes what WeiDU would refuse**, with WeiDU's
  reason, including the BG:EE mods that would make EET refuse the merge. The
  EET core is never removed.
- **A mock EET install test** (`tests/data/eetmock`): verbatim tp2 excerpts of
  DlcMerger, EEFixPack, BG1UB, EET, EET_end, Tweaks Anthology, SCS, Ascension
  and UB at pinned commits, EET's real `compatibility.tbl`, and logs carrying
  the usual mistakes.

### Changed
- **A refusal an order can fix is fixed by the order.** EEFixPack in the EET
  log is moved before the EET core, where the game is still BG2:EE, instead of
  being removed - as EET's readme and BWS-NG's `games/eet.json` place it. The
  report lists it under "moved before the EET core"; `RESOLUTION.json` gains a
  `moved` list.

### Fixed
- **A `BEGIN` inside an inlined file was read as a component.** EET_end.tp2
  inlines a `.d` file reading `BEGIN ~%file%~`; it was counted as component #0,
  which renumbered the real ones and lost EET_end's REQUIRE on the EET core.
  Found by the real-WeiDU test on its first run.
- **The mock EET fixture staged EET_end where WeiDU 251 cannot run it**
  (`eet/EET_end/`); it is now at `EET_end/`, as the EET repository ships it.

## [2.1.0] - 2026-10-20

A correctness and hardening release. No flag or report field changed meaning;
two behaviours changed on purpose and are listed under *Changed*. Measured on
the same machine before and after: 586 tests with 1 failing → 713 passing;
branch coverage 88% → 90%; gate failures on a clean checkout 4 → 0; 11
defects fixed, each with a test written to fail first.

### Fixed
- **A transfer cut short was accepted as a complete download.** `http.client`
  returns a truncated body without raising, so a dropped connection produced a
  partial file whose first bytes carried the right magic number. Bytes received
  are now checked against `Content-Length` and a shortfall is retried. Found by
  the new loopback socket tests; no test double could have shown it.
- **`IncompleteRead` crashed the run as an "internal error"** instead of being
  retried: it is an `HTTPException`, not an `OSError`.
- **Damaged archives crashed the run as an "internal error".** A truncated or
  CRC-corrupt zip/tar raised `BadZipFile`/`zlib.error`/`EOFError`, which escaped
  every typed handler and skipped the catalogue-alternate retry. Reported now as
  "damaged or incomplete - usually a partial download".
- **Security (Windows): a server-chosen file name could escape the work
  directory.** `Content-Disposition: filename="..\..\x.zip"` (or `C:\x.zip`)
  was joined onto the staging path; `posixpath.basename` does not split on `\`.
  Reduced to one safe component at the sink (`naming.archive_filename`).
- **Security: rar/7z/exe archives skipped the member checks** that zip and tar
  get. Their 7-Zip listing is now held to the same traversal, entry-count and
  size limits before anything is written.
- **Hostile `Retry-After` crashed the retry loop.** `-1` or `NaN` reached
  `time.sleep`, which raises. Clamped to 0–300 s.
- **Every retried HTTP error leaked a connection** until garbage collection
  (a `ResourceWarning` on Python 3.14).
- **Local disk errors were retried** (disk full, permission denied, read-only
  file system), downloading the whole file again each time to fail the same way.
- **Old-style packages were staged as `<mod>/<mod>/...`.** An archive with
  `setup-<mod>.tp2` beside a `<mod>/` folder now installs as `<mod>/` with the
  tp2 inside, which is what WeiDU needs.
- **Root-level WeiDU log lines were dropped.** `~SETUP-X.TP2~ #0 #0` (an older mod
  whose tp2 sits in the game directory) was warned about and never planned or
  fetched; the mod is now named by WeiDU's own `setup-<mod>.tp2` rule and the
  line is kept verbatim.
- **A release with `win-`/`lin-`/`osx-` packages picked `lin-` on Windows**
  (shortest name won). WeiDU's platform-prefix convention now decides first.
- The `L9` characterization test failed on every Python ≥ 3.12 under `-W error`;
  it now pins the tar filter the legacy script was written against.
- Five lint failures from a newer ruff (`ISC004`), and a mypy configuration that
  mypy 2.x refuses.

### Changed
- **Order checking is component-correct.** "A before B" now means every named
  component of A precedes every one of B, by real log line. The old check used
  each mod's first component and a per-mod grouped line counter: on the real
  install 34 of its 46 order findings were false ("X before EET_end", with
  EET_end logged last), and 2 real ones were hidden.
- `--resolve-conflicts` no longer resolves a tie by taking the left side (a
  guess); ties go to the operator. Same-mod conflicts with an unequal split are
  resolved like cross-mod ones.
- BWS-NG-format rules keep an `evidenceLevel` / `source` when an entry carries
  one, so a speculative claim is never resolved automatically.
- README no longer says `pip install iemod-fetch`: the package is not on PyPI.
  It is `pip install git+https://github.com/gsamuele78/iemod-fetch`.
- A GitHub `403` with an exhausted quota now says so, with the reset time,
  instead of a bare "HTTP 403".
- Asset selection prefers a package for the running platform; a log line with
  no mod folder now produces a mod instead of a warning.

### Added
- **From WeiDU logs to a running game.** `--emit-installer` writes
  `install-eet.sh` + `install-eet.cmd` (or `install.sh`/`.cmd` for one game)
  beside the plan. They hand the planned logs to dark0dave's mod_installer +
  WeiDU: BGEE first, then the EET core with the BGEE path, the EET mods, EET_end
  last. Before anything runs they refuse a folder without `chitin.key`, a game
  that already has mods, a missing WeiDU/mod_installer, and on Linux mixed-case
  mod folders (mod_installer hands WeiDU lower-cased paths). Verified by running
  the generated script with the real mod_installer 16.0.0 binary. iemod-fetch
  never executes the scripts (ADR-0022).
- **Automatic conflict resolution, where the rules decide.**
  `--resolve-conflicts` removes from the plan the components an error-graded,
  non-speculative incompatibility rule pins (the remedy the conflict report
  already named), re-verifies the plan, and writes `RESOLUTION.json`. Whole-mod
  pairs, same-mod option groups, missing dependencies and warnings are listed
  for the operator, never decided (ADR-0021). Your own logs are never edited.
- **Component-level install order** (ADR-0023). A mod is split across the order
  where krion64 places a component in another category (`co[].cat`) or an
  order rule names specific components; a mod nothing distinguishes stays
  whole. A rule between two components of one mod is honoured. On the real
  install: 6 mods split, plan verified against 158 constraints.
- **Preferred installation language with fallback** (ADR-0024).
  `--language-preference it_IT,en_US` sets each mod's `#lang` from its own tp2
  LANGUAGE declarations, first preference it offers; BWS-NG's model.
- **WeiDU SUBCOMPONENT clashes** (two options of one `Group -> Option` group)
  are reported without any rule set, and resolved by keeping the last.
- `--game-language` for the installer scripts (default: the first preferred
  language, else `en_US`).
- README banner, contents, feature table and an end-to-end quick start; guide
  chapter 10 (Windows and Linux); ADR-0021 and ADR-0022.
- `tests/test_net_loopback.py`: the real HTTP stack against a stdlib server on
  `127.0.0.1` (technique adopted from Born2BSalty's Infinity Orchestrator).
- Python 3.14 in the CI matrix and classifiers.

### Build
- ruff and mypy pinned to a minor series (`~=`), and the pre-commit ruff
  revision aligned with CI: an unpinned linter turned a green `main` red with
  no code change.
- Every GitHub Action pinned to a commit SHA (zizmor: 37 high findings → 0),
  and zizmor itself pinned. The release-notes step no longer expands the tag
  name into script source (template injection).
- The stdlib-only CI job failed at start-up: a warning filter naming
  `hypothesis` is a config error when Hypothesis is absent. It is registered
  from `conftest.py` only when Hypothesis is installed.

### Repository readiness (unreleased since 2026-09-10, shipped here)

#### Added
- `docs/ARCHITECTURE.md`, `docs/TESTING.md`, `docs/SECURITY-MODEL.md`,
  `docs/RELEASING.md` and `docs/ROADMAP.md`.
- Property-based tests (Hypothesis) over the parsers, the safety predicates and
  the version comparator (ADR-0019).
- Architecture contracts enforced by `import-linter`: the functional core may
  not import the imperative shell, and the runtime may not import a third-party
  package (ADR-0020).
- `iemod_fetch/urls.py` — pure URL facts, extracted from `resolvers`.
- CI/CD: lint, typecheck, architecture, test matrix, coverage floor, security
  scanning, SBOM, build provenance and signed releases.

#### Fixed
- **Version comparison was not antisymmetric.** Two spellings of the same
  stability level (`master`/`main`, `alpha`/`a`, `rc`/`pre`) each compared as
  *newer than the other*, so `is_newer` was true in both directions and an
  upstream renaming its default branch could mark a rule stale on the rename
  alone. Found by property-based testing, not by any example test.
- Archive extraction no longer hands an unvalidated member list back to the
  standard library: entries are extracted one at a time and the resolved
  destination is re-checked before each write.
- A manifest invariant in the pinned-manifest generator was an `assert`, which
  `python -O` strips. It is a raised `ManifestError` now.
- Two tests leaked file handles, surfaced by promoting warnings to errors.
- `catalogues` no longer reaches into `resolvers` through a function-local
  import to dodge an import cycle.

## [2.0.0] - 2026-09-09

### Added
- Component-level conflict reporting: which component of which mod fights which
  component of which other mod, with the upstream's evidence grade and source,
  and the narrowest remedy (ADR-0018).
- Whole-install order planning: `--plan-order` writes a rule-compliant
  `WeiDU.log` + `WeiDU-BGEE.log` pair and verifies the result against the same
  rules that judged the input (ADR-0017).
- Install-order, incompatibility and dependency checking against BigWorldSetup
  Next-Generation and krion64 rule data, with staleness detection (ADR-0015,
  ADR-0016).
- `.iemod` / Project Infinity metadata parsing, and `.tp2` introspection for the
  installed version and supported games.
- INI configuration file with documented precedence, `expect_tp2` manifest
  override, trusted-owner release discovery, LCC catalogue enrichment,
  `--emit-pinned-manifest`, and a single-file `zipapp` build.

### Changed
- Complete rewrite of the original single-file script. The original is kept in
  `legacy/` so its defects stay reproducible (ADR-0001).

### Security
- HTTPS enforced including across redirects; the GitHub credential is never
  attached to a non-GitHub host; archives are size-, ratio- and traversal-checked
  before extraction; downloads are verified against a pinned `sha256` when the
  manifest carries one.
