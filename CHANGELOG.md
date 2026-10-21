# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html), where
the public surface is the CLI's flags and the JSON report schema — not the
Python API, which is internal.

## [Unreleased]

### Added
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
