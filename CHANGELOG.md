# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html), where
the public surface is the CLI's flags and the JSON report schema — not the
Python API, which is internal.

## [Unreleased]

### Changed
- **Releases are automatic.** Merging a release pull request (a new
  `## [X.Y.Z]` section and the matching `__version__`) builds, attests, tags
  `vX.Y.Z` on that merge and publishes the GitHub release, with the changelog
  section as its notes. Nobody tags by hand. An older version without a release
  is published with *Run workflow* and its `version`. PyPI publishing is opt-in
  through the `PYPI_PUBLISH` repository variable. This is the method of
  R-studioConf's ADR-0006, adapted (ADR-0027).

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
