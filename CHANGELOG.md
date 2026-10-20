# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html), where
the public surface is the CLI's flags and the JSON report schema — not the
Python API, which is internal.

## [Unreleased]

## [2.1.0] - 2026-10-20

A correctness and hardening release. No flag or report field changed meaning;
two behaviours changed on purpose and are listed under *Changed*. Measured on
the same machine before and after: 586 tests with 1 failing → 638 passing;
branch coverage 88% → 89%; gate failures on a clean checkout 4 → 0; 11
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
- A GitHub `403` with an exhausted quota now says so, with the reset time,
  instead of a bare "HTTP 403".
- Asset selection prefers a package for the running platform; a log line with
  no mod folder now produces a mod instead of a warning.

### Added
- `tests/test_net_loopback.py`: the real HTTP stack against a stdlib server on
  `127.0.0.1` (technique adopted from Born2BSalty's Infinity Orchestrator).
- Python 3.14 in the CI matrix and classifiers.

### Build
- ruff and mypy pinned to a minor series (`~=`), and the pre-commit ruff
  revision aligned with CI: an unpinned linter turned a green `main` red with
  no code change.

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
