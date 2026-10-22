# Testing strategy

## The problem with "we do TDD"

TDD gets you a test for every case you thought of. Every defect that has
actually hurt this project was a case nobody thought of:

- a `? 1 : 0` **anywhere** in a `.tp2` suppressing every `GAME_IS` match;
- twenty WeaselMods mods all resolving to `alabaster-sands`, because a bare
  navigation link scored just high enough;
- `EET_END.json` sorting before `eet.json` in ASCII, so a folder claim put the
  EET core in "EET FINALIZATION" and sent it to the end of the install;
- `compare("master", "main")` returning 1 — and `compare("main", "master")`
  returning 1 as well.

None of those would have been written as an example. Seven techniques are used
here, each aimed at a class of defect the others cannot see.

## 1. Characterization tests — pinning the original's behaviour

`tests/test_legacy_characterization.py`, 13 tests, running against
`legacy/fetch_mods_original.py`, which is kept **verbatim** (ADR-0001).

They assert the original's *defects*: that it mutates repository names, that it
takes the first hit of a code search, that it accepts an archive whose `.tp2`
does not match. A rewrite that claims to fix something has to be able to show
the thing being fixed. Delete the legacy file and the evidence goes with it.

## 2. Example tests — the ordinary TDD layer

~540 example tests across 26 files, one per module. Offline, no network, no mocking
framework: the test doubles are small hand-written classes, and where the real
code raises `HttpStatusError` the double raises `HttpStatusError` too. (It did
not, once. The double raised a bare `NetworkError`, and a retry path that only
existed for typed errors went untested.)

Fixtures are **real files**: the operator's actual 148-entry manifest and their
796-component WeiDU logs, in `tests/data/`. Synthetic fixtures only ever contain
what the author imagined.

## 3. Property-based tests — laws, not examples

`tests/test_properties.py`, using Hypothesis. Skipped, not failed, when
Hypothesis is absent, because the runtime is standard library only and
`python3 -m pytest` must work with nothing installed.

A property states something that must hold for **every** input, and Hypothesis
searches for a counterexample and then *shrinks* it to the smallest input that
still fails. The properties are chosen where a law genuinely exists:

| Property | Why it must hold |
|---|---|
| `safe_component` is total | a path-traversal guard that itself raises is a denial of service in the guard |
| what `safe_component` accepts can never traverse | the security boundary, stated as a law rather than as twelve examples |
| `normalize_key` is idempotent | it is applied at several layers; a second application must not change the answer |
| `tp2_key` agrees with `normalize_key` | two normalisations mean rules that silently match nothing |
| `compare` is reflexive, antisymmetric, transitive | otherwise it is not a strict weak ordering and `sorted()` over releases is undefined |
| `is_newer` agrees with `compare` | one of them is used to decide staleness, the other to pick a release |
| a release tag always beats a branch snapshot | the operator's stated stability ordering |
| every parser is total over arbitrary text | a log or a catalogue is attacker-adjacent input |
| a well-formed log round-trips | reading and writing are inverse |
| `_minimum_moves` is empty for an unchanged order, and 1 for one rotation | the metric that stopped the planner claiming 146 mods were out of place when one was |

**This has already paid.** On its first run the antisymmetry property found that
`master` and `main` — both rank −6 — each compared as *newer than the other*, so
`is_newer` was true in both directions and an upstream renaming its default
branch could mark a rule stale on the rename alone. Six hundred example tests
had not noticed. Shrunk counterexample: `compare('MASTER', 'MAIN')`.

The pull-request run uses 300 examples so it stays fast; the nightly job gives
the same properties 20,000.

## 4. Architecture tests — the layering as a gate

`.importlinter`, four contracts, run in CI. The design in `docs/ARCHITECTURE.md`
is not a diagram that drifts away from the code: an import that crosses a
boundary fails the build.

**This has already paid too.** The purity contract refused
`catalogues → resolvers`, which existed as a function-local
`from .resolvers import repo_from_url` written specifically to dodge an import
cycle — the standard sign that a pure thing is trapped in an impure module. The
fix was `urls.py`, and the catalogue layer is honestly pure now.

## 5. Static analysis — the checks that need no test

| Tool | The class of defect it catches |
|---|---|
| `mypy` | `Optional` reaching somewhere that cannot handle it; a wrong attribute; a function returning `Any` where the signature promises a type. Caught a genuine `NameError` I had just introduced in the extraction path — before any test ran. |
| `ruff` | mutable default arguments, loop-variable capture, blind `except`, dead code, shadowed builtins |
| `bandit` | the security-shaped mistakes: `assert` used for a real check (stripped by `python -O`), permissive file modes, unvalidated extraction |
| `tools/check_stdlib_only.py` | any non-stdlib import in the runtime, including one nobody thought to ban |
| `zizmor` | the workflows themselves: over-broad tokens, persisted credentials |
| `-W error` in pytest | a `DeprecationWarning` from the stdlib is the earliest possible notice that a future Python breaks this. It also found two tests leaking file handles the day it was switched on. |

## 6. Mutation testing — does the suite actually assert anything?

Nightly, `mutmut`, reported and never gating.

Coverage says a line *ran*. It does not say the tests would have **noticed** if
that line were wrong, and the two are routinely confused. Mutation testing
changes an operator, deletes a branch, swaps a constant, and asks whether any
test goes red. A surviving mutant is a question — "is this behaviour actually
asserted, or merely executed?" — and sometimes the honest answer is "it does not
matter", which is why it reports rather than blocks.

This is also why the coverage floor is 85 and not 100. A number above what the
code honestly reaches turns into tests written to touch lines.

## 7. Loopback socket tests — the real HTTP stack

`tests/test_net_loopback.py` runs a stdlib `http.server` on `127.0.0.1` and
points the real client at it: real `urllib`, real `http.client`, real sockets.
Still offline — nothing leaves the loopback interface.

Every other network test uses a hand-written double, and a double encodes what
its author *believes* the library does. The first loopback run disproved one
such belief: `http.client`'s `read(n)` does **not** raise on a body cut short
of its `Content-Length` — it returns what arrived, then `b""`. A connection
dropped mid-transfer was being accepted as a complete download whose first
bytes even carried the right magic number. No double would have shown it,
because the double was written to raise `IncompleteRead`.

Borrowed from the download tests of Born2BSalty's Infinity Orchestrator, which
serve fixtures over a loopback TCP listener for the same reason.

## 8. The real WeiDU as oracle — no game data needed

`tests/test_real_weidu.py` runs the mock EET install through the real WeiDU
(v251) and, when given, the real mod_installer. WeiDU identifies a game by
marker files (`oh1000.are`, `oh6000.are`, `eet.flag`), so a folder with an empty
`chitin.key`, an empty `dialog.tlk` and the marker is enough for it to enforce
GAME_IS, REQUIRE_COMPONENT and FORBID_COMPONENT. Three claims:

* on the raw logs, WeiDU refuses exactly the components `--simulate` refuses;
* WeiDU installs the resolved plan to the last component;
* the generated `install-eet.sh` drives mod_installer + WeiDU into both games.

Its first run found two bugs no self-consistent test could: a parser bug and a
fixture placed where WeiDU does not look. Opt in locally with
`IEMOD_WEIDU=/path/to/weidu` (and `IEMOD_MOD_INSTALLER`); CI's `real-weidu` job
downloads both pinned and sets `IEMOD_REQUIRE_REAL=1`, so a missing tool fails
instead of skipping.

### Components before download: krion64 against WeiDU

The wizard offers a mod's components before it is downloaded from krion64's
records (ADR-0035). `tools/krion_components_benchmark.py` compares them with
WeiDU 251's own `--list-components` (the `tools/tra_oracle.py` output, 105
mods both know): of 1,529 components WeiDU lists, 1,471 are in krion64 under
the same number; 58 are missing (7 of them marked removed though the tp2 still
has them), 13 krion64 lists are not in the tp2, and 85 mods are identical.
Hence each component says where it came from, and the staged tp2 replaces
krion64 for its mod.

### Community sources: lcc-docs, krion64 and BWS-NG against each other

`tools/download_sources_benchmark.py LCC_MODS_JSON KRION_DATA --bws
BWS_MODS --probe` measures where a mod is downloaded from (ADR-0036). On
2026-10-22 over the Enhanced Edition mods: lcc-docs knows 1,148, krion64 813,
BWS-NG 412. Of the 113 mods for which lcc-docs and krion64 name different
repositories, krion64's is gone in 27 and lcc-docs' in none; 23 are one
repository under two names; of the 63 different live ones lcc-docs' has the
newer last commit in 51. BWS-NG pins exact files: 279 of its 280 pinned GitHub
release tags still exist, and against the newest scanned release its pinned
version is the same for 177 mods, older for 48 and newer for 3. `tools/krion_components_benchmark.py ORACLE KRION
BWS` adds BWS-NG's components: on the 67 mods all three know, krion64 has
1,047 of WeiDU's 1,089, BWS-NG 1,023, their union 1,057.

### The authors' own order: Project Infinity metadata inis

`tools/pi_metadata_benchmark.py MODS_DIR KRION_DATA RULES...` reads every mod's
metadata ini (from git, so sparse clones do) and compares its `Before`/`After`
with krion64's order and the order rules (ADR-0037). On 103 real mods: 85 inis,
314 order pairs; krion64's order agrees with 239, a rule covers 34 of the rest,
22 span the two EET game phases, and 19 are known only to the author - 7
contradicting krion64. Two of the 19 name a mod by its display name ("Coran in
BG2"), which matches no tp2 and so orders nothing.

### Engine limits, measured as WeiDU measures them

`tests/test_real_weidu_limits.py` checks the game-folder measurement of
`limits.py` (ADR-0034) against the same WeiDU. The synthetic BG2:EE has a real
`chitin.key` and BIFF (built byte by byte), KITLIST.2DA and SPELL.IDS inside
the BIFF, and the other tables ADD_KIT appends to in override/:

* with 254, 255 and 256 kits measured, WeiDU's ADD_KIT gives kit 255 and 256,
  then refuses with its own "more than 256 kits" - so the measured number is
  WeiDU's, and 256 is a hard limit on BG2:EE;
* with 2101 and 2102 in SPELL.IDS, SPWI103 in override/ and SPWI105 in the
  BIFF, ADD_SPELL takes 2104 then 2106, and reuses 2101 for an identifier
  SPELL.IDS already has - exactly the slots measured as free.

krion64's counts, which stand in when no game folder is known, were audited
the same day: its spell scanner (`scan_spell_ids.js`) reads only literal
`APPEND spell.ids`, so of the 103 repositories NWNForBG (6 ADD_SPELL) and
Region of Terror (4) are recorded with 0; `k` is entered by hand; `ss` counts
references. Hence the estimate is labelled as one, and the measurement wins.

### Component names, measured against WeiDU itself

`iemod_fetch/tra.py` names components without running WeiDU. Its claim is
"the same text WeiDU prints", and it is measured, not argued:
`tools/tra_oracle.py` runs `weidu --nogame --list-components` for every tp2
and every language of a set of real mod repositories, and
`tools/tra_benchmark.py` compares, byte for byte.

```bash
python3 tools/tra_oracle.py /path/to/weidu MODS_DIR oracle.json
python3 tools/tra_benchmark.py oracle.json --min 99.9
```

On 103 repositories (lcc-docs and BWS-NG mods, cloned 2026-10-21) and WeiDU
251: 551 runs, 9,889 component lines. The parser went from 65.70% to 100.00%
exact, each step a form WeiDU accepts and the parser did not - bare-word
LANGUAGE names (SCS), `%WEIDU_OS%`, FORCED_SUBCOMPONENT, `BEGIN` alone on its
line, undesignated numbering as previous + 1, a bare-word .tra value,
`%MOD_FOLDER%` taken from BACKUP (LCA). Each became a unit test in
`tests/test_tra.py` or `tests/test_tp2_components.py`.

The same run records `--list-components-json` for language 0, and the
benchmark checks the rest of WeiDU's view against it: which components are
listed at all (a DEPRECATED one is not: Might and Guile #145), and each one's
title, subgroup, groups, labels and forced flag - 109 of 109 lists and 1,499 of
1,499 components on every field. It also found that the JSON drops a line
break inside a name where the text output prints a space; `name` follows the
text, `title` and `subgroup` the JSON.

The same LABELs measure krion64's: of 732 LABELs both krion64's records
(`co[].pi`) and the tp2s name, 708 point at the same tp2 and component; 24 do
not, some at another mod altogether (`cd_tweaks_drab_commoners`: cdtweaks
#100 in the tp2, iwdification #20 in krion64). That is why `--pi-list` takes
the tp2's answer whenever the mod is staged and reports every entry it took
from krion64.

Read the 100% honestly: it is the set the parser was fixed against, so it is a
training score. A new mod can still use a form not seen here; the next run of
the oracle on a wider set is the real test. Names built by code at install
time (an `OUTER_SPRINT` then `BEGIN %name%`) are out of reach by design and
are reported unresolved, not guessed.

### Versions: what is installed, and what is newest

Two rules decide the update notice, and both are measured with
`tools/version_benchmark.py` against what the mods themselves say:

```bash
python3 tools/version_benchmark.py oracle.json krion64/data BWS-NG/data/mods MODS_DIR
```

* **The version in a WeiDU.log line** (`weidu.log_version`). WeiDU 251 writes
  `Name: VERSION`, checked by installing a test mod with it, and names have
  colons too. On the oracle's 1,533 component lines: 1,409 versions read
  right, 0 wrong, 0 missed, 124 lines rightly without one. Taking whatever
  follows the last `: ` would have been wrong 111 times.
* **The newest version** (`freshness.latest`). Against the tp2 VERSION at HEAD
  of 90 mods, each source alone: GitHub release 67 the same, krion64 60,
  BWS-NG 42; the newest of the three, 79 (5 older, 6 newer, none unknown).
  The truth is imperfect: most "newer" are real releases whose author did not
  bump the tp2, so a right answer counts against the rule.

### BIO share codes, checked against BIO itself

`iemod_fetch/bio.py` implements the `BIO-MODLIST-V1:` format from reading
BIO's source (33800cc); it uses none of BIO's code. Whether it really speaks
the format is checked with BIO, built from that commit with one test added
outside this repository that calls BIO's own `encode_share_payload_text` and
`decode_share_payload` + `share_preview`:

* `tests/data/bio/eet-mock.bio` was **encoded by BIO** from the mock EET
  install (with a `// @wlb-inputs:` answer, BIO's extras, non-ASCII text).
  `tests/test_bio.py` decodes it, re-encodes it to the same JSON payload byte
  for byte, and round-trips it through a selection keeping every field. With
  classic zlib the code itself comes out identical; Python 3.14 on Windows
  ships zlib-ng, whose deflate stream differs while inflating to the same bytes
  (the first CI run showed it), so the test compares the payload.
* Codes **written by this tool** - a fresh export and an export over the
  imported code - were decoded and previewed by BIO, which read the same game,
  install mode, entry counts and name.

To repeat it: append `tools/bio_interop_test.rs` to BIO's
`src/core/app/modlist_share.rs`, then
`IEMOD_CODE_IN=ours.bio cargo test --lib iemod_interop -- --nocapture`.

## What is deliberately not done

**No network in the test suite, ever.** Not even against a local server. The
suite runs on an aeroplane and gives the same answer.

**No mocking framework.** `unittest.mock` makes it easy to assert that a
function was called, which is a test of the implementation rather than of the
behaviour. Hand-written doubles are more work and stay honest.

**No snapshot testing of the reports.** The renderers are asserted on the facts
that matter ("the plan says FRESH install", "the remedy names the cheaper
side"), not on their whole output. A snapshot test of a 40-line report fails on
every wording change and teaches people to re-bless it without reading.

**No fuzzing harness yet.** It is on the roadmap for `archives.py` and the
parsers, where the input is genuinely hostile. Hypothesis already covers the
parsers as far as structured generation goes; a real fuzzer would go further on
the zip and tar readers.

## Running it

```bash
make check            # ruff, mypy, import-linter, pytest — what CI gates on
make cover            # with the branch-coverage floor
make audit            # bandit and pip-audit
make mutants          # slow; the nightly job runs this

python3 -m pytest -q                              # the suite, ~13s
python3 -m pytest tests/test_properties.py -q     # the properties alone
python3 -m pytest -k "security" -q                # the boundary tests
```

## Current numbers

| | |
|---|---|
| Tests | 1,168 collected (7 run the real WeiDU, 49 drive the GUI with pytest-qt; both opt-in) |
| Branch coverage | 92% (floor: 85%) |
| Architecture contracts | 7, all kept |
| mypy | clean, 57 modules |
| ruff | clean |
| bandit | 0 high, 0 medium |
| Runtime dependencies | 0 |
