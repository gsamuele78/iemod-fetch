# GUI audit — from a CLI to a complete mod manager (2026-10-21)

The question: can iemod-fetch become a complete tool, a command line with a UI
on top where a player picks mods and components from tabs, checkboxes and
drop-downs, sees which mods are current, and gets the install order and the
component conflicts resolved? And what can be taken from the projects this one
already reads, and from Born2BSalty's Infinity Orchestrator (BIO)?

The answer in one line: **yes, but the CLI is not ready to carry a UI, and the
work to make it ready is most of the work.** The UI comes last. This document
is the audit (phase 1), the plan (phase 2) and the acceptance tests (phase 3).
The decisions are ADR-0029 to ADR-0031 in [ADR.md](ADR.md), accepted by the
owner on 2026-10-21. The answers to §1.1 changed two of the assumptions first
made: the wizard ends by installing, and the UI is a PySide6 desktop app like
BWS-NG.

---

## Phase 1 — Audit

### 1.1 Missing information, and the assumptions made instead

| Question | Answer (owner, 2026-10-21) or assumption |
|---|---|
| Should the UI also **install** (run WeiDU / mod_installer), or only plan, fetch and hand over? | **Install too**: a wizard in phases like BWS-NG, Forge/Runner and BIO, with installation as the last phase (ADR-0029). |
| Target users: only EET, or every Enhanced Edition game? | EET, BGEE and BG2EE first. IWDEE next, because BWS-NG and BIO already cover it. PST/IWD2 are out of scope. |
| Which UI toolkit? | **PySide6, like BWS-NG** (ADR-0031). The GUI is its own package and download; the CLI stays one dependency-free `.pyz`. |
| Will the BIO, BWS-NG or krion64 authors license their data for reuse? | No. Their data is read at run time as user-supplied input, never bundled. |
| Windows as the main platform? | Yes. CI already tests Windows, but no real Windows install has run yet. |

### 1.2 Where the CLI stands (v2.2.0)

Verified by reading the code. 803 tests pass, 4 are skipped, branch coverage
is at least 85%, and there are no TODO/FIXME markers.

**What it does well:**
- downloads with sha256 pinning and archive safety checks (magic bytes,
  extraction ratio, HTML-as-archive refusal);
- reads catalogues: `mod_downloads.json`, lcc-docs, the BWS-NG database and
  rules, and the krion64 order;
- builds a component-level install order and a conflict report, with automatic
  resolution where a rule decides;
- simulates the EET install, checks game folders, chooses languages;
- emits mod_installer input.

**What a UI needs and the CLI does not have:**

| Need | State | Evidence |
|---|---|---|
| Browse the available mods without a WeiDU.log | **no** | `cli.py:584-590` refuses to run without `-w`; nothing lists a catalogue |
| A selection made from scratch (mod + components + language) | **no** | the only selection format is WeiDU.log |
| Components with names, groups and choices | **partial** | `Tp2Component` (`tp2.py:201`) has numbers, SUBCOMPONENT, REQUIRE/FORBID; no name (no `.tra`), no LABEL/GROUP/DEPRECATED |
| "Newer version available" per mod | **no** | `resolvers.py:126` reads the latest release but never compares it with what is installed (roadmap E2) |
| A versioned JSON contract | **partial** | reports exist, but none has `schema_version` and findings have no stable id |
| Conflicts as choices a UI can offer | **partial** | `Finding` has both sides; `Unresolved` is free text; there is no `decisions` input |
| Progress and cancellation | **no** | one printed line per mod (`runner.py:330`); no byte progress; Ctrl-C only |
| A public library API | **partial** | the pieces can be imported, but the wiring is private in `cli.py:261-707` |
| Stable error codes | **partial** | typed exceptions, but per-mod failures become strings |
| One-run fetch then plan | **no** | planning reads the target folder before the downloads (`cli.py:604` vs `678`) |
| A stated scope that allows a GUI | **no** | ROADMAP 2.3 "Explicitly not planned": *A GUI*, *Running WeiDU* |

### 1.3 What the other projects do

| Project | License | Toolkit | Order | Conflicts | Updates | Integrity |
|---|---|---|---|---|---|---|
| **BIO** 1.0.3-beta | GPL-3.0 | Rust + egui | user drags; **no sort** | own tp2 line scan + 21 hand rules | GitHub API (releases, tags, forks), page scrapers | FNV-1a hash, **no sha256** |
| **BWS-NG** | GPL-3.0 | Python + PySide6 | 351 rules + per-game sequences | 254 incompatibility + 246 dependency rules | data bundle with a version file; mods bumped by hand | sha256 per file |
| **lcc-docs** | MIT | static site, vanilla JS | none | mod-level only | `last_update` by hand | none |
| **krion64 Forge** | MIT (data provenance uncertain) | React page | category × `ord` | hard/soft with evidence | weekly GitHub release scan | none |
| **mod_installer** 16.0.0 | GPL-3.0 | Rust CLI | follows the log | none | none | none |
| **Infinity Mod Runner** | MIT | Tauri + React | from Forge | from Forge | — | — |
| **iemod-fetch** 2.2.0 | MIT | Python CLI, stdlib only | **sorted**, component level | tp2 + rules, auto-resolution | partial | **sha256 + attestation** |

What follows from that:

- **BIO's code and data cannot be taken.** BIO is GPL-3.0 and its prompt
  parser is AGPL-3.0, so nothing is copied or bundled. Its *formats* can be
  read and written. Its share code is `BIO-MODLIST-V1:` + base64url(zlib(JSON)),
  containing the WeiDU.logs, pinned sources and mod configs. That gives
  iemod-fetch access to the modlists BIO users exchange on Discord.
- **BWS-NG is the UI model players already know.** It is a PySide6 wizard:
  - a category column;
  - a tree of mod → component → choice with tri-state checkboxes;
  - `muc` groups shown as radio buttons and `sub` prompts as drop-downs;
  - a violations panel with one-click fixes;
  - EET order as per-phase tabs.
  iemod-fetch already reads its rule syntax.
- **lcc-docs is the only browse list that may legally be reused as-is.**
  It is MIT and covers 2,151 mods with status, safe, games, categories and
  `last_update`. It has no component data.
- **mod_installer is a poor engine to drive from a UI.** It produces only log
  text, its prompts arrive on stdin, and its automatic EET path answer works
  on Linux only. A UI that installs would either work around this or drive
  WeiDU itself, as BWS-NG and Infinity Mod Runner do.
- **iemod-fetch already does better than all of them** at the parts a UI cannot
  replace: verified downloads, a computed order, automatic resolution and
  running headless. That is the argument for building the UI on top of this
  core rather than adopting one of theirs.

### 1.4 Risks, stated plainly

- **`.tra` resolution is the hardest single item.** Component names live in
  translation files with `@n` references, per language, sometimes generated at
  install time. Without names a component tree is a list of numbers. Size L.
- **The scope grows.** "Also install" makes this a fifth installer in a small
  community. The plan keeps installing optional and late.
- **Data is borrowed, not owned.** Order and conflict quality depends on
  BWS-NG and krion64 data that this project may not bundle. If either goes
  stale, the UI looks wrong, not the code.
- **No real-game CI.** Everything is checked against synthetic game folders
  (roadmap F5/F9). A UI invites players who will find what synthetic folders
  do not.
- **Stale roadmap line.** The 2026-09 open item about the v2.1.0/v2.2.0 tags
  is done: both releases are published (ADR-0027).

---

## Phase 2 — Plan

A milestone is entered only when the previous one passes its tests in phase 3.

### M1 — The CLI becomes a backend (v2.3) — must have, no UI yet

*Done on 2026-10-21* in #14 (selection.json), #15 (`--list-mods`), #16
(versioned reports, finding ids), #17 (events, cancellation), #18 (error codes,
fetch then check in one run) and the API pull request (`iemod_fetch.api`).

| # | Item | Size |
|---|---|---|
| 1 | **ADR-0029** accepted: the scope changes (UI yes, installing opt-in later) | S |
| 2 | `iemod_fetch.api`: public functions (`list_mods`, `describe_mod`, `plan`, `check`, `resolve`, `fetch(items, on_event, cancel)`) with `__all__`. `cli.py` becomes a thin user of it, and filesystem reads move out of the core | M |
| 3 | `selection.json` v1 (game, mods, components, language, choices) as an alternative to WeiDU.log; both turn into the same internal objects | M |
| 4 | `iemod-fetch mods --json`: the merged catalogue (manifest + lcc-docs + mod DB) with games, categories, status, safe and sources | S-M |
| 5 | `schema_version`, stable finding ids and JSON Schema files for every JSON output, with tests that validate them | S-M |
| 6 | `--events jsonl`: per-mod and per-chunk progress, plus cancellation through a `threading.Event` | M |
| 7 | Fetch and plan in one run (planning reads what was just staged) | S |
| 8 | A stable `code` on every error, carried on each record | S |

### M2 — Components and choices (v2.4)

*Done on 2026-10-21* in #23-#29 and released as 2.4.0. Beyond the plan: the
engine limits of each install (ADR-0034), measured in the game folder by
WeiDU's own rules after krion64's counts were audited and found to miss
ADD_SPELL.

| # | Item | Size |
|---|---|---|
| 9 | `iemod-fetch describe MOD --json`: components with names resolved through `.tra` for the chosen language, plus SUBCOMPONENT/GROUP/LABEL/DEPRECATED. The `muc`/`sub` vocabulary is taken as an idea from BWS-NG. **Done**: names (`--describe-mods`, 9,889/9,889 against WeiDU 251's `--list-components`) and SUBCOMPONENT, FORCED, GROUP, LABEL, DEPRECATED (1,499/1,499 against its `--list-components-json`) | L |
| 10 | Conflicts as **options** (drop a side, move before or after, each with its cost), and a `decisions.json` input that is applied and re-checked. **Done** (ADR-0033): every finding of the mock EET plan has options, and each applicable one clears it (`tests/test_decisions.py`) | M |
| 11 | Freshness: installed vs latest per mod, from a cached weekly release scan (roadmap E2/E4). **Done**: krion64's daily release cache plus BWS-NG and krion64 versions, the newest of the three (79/90 against tp2 VERSION); `installed`, `latest`, `update_available` in `--list-mods` | M |
| 12 | BIO share-code **import/export** (format only). **Done**: `--bio-code`, `--emit-bio-code`; a BIO-made code round-trips to the same payload byte for byte, and BIO decodes ours | S-M |
| 13 | Read Project Infinity `weidu-log.csv` and krion64 `mod-forge.json`. **Done**: `--pi-list` (LABELs from the tp2s, krion64 as a reported fallback: 708/732 agree) and staged `mod-forge.json` read as rules (none of 103 measured mods ships one yet) | S |

### M3 — The wizard up to download (v3.0) — released in 3.0.0

ADR-0031: `iemod_fetch_gui`, PySide6, importing only `iemod_fetch.api`. The
phases are BWS-NG's order. Each phase saves a file the CLI also reads, so a
run can be stopped and resumed, or finished from the command line.

| # | Phase / item | Size |
|---|---|---|
| 14 | **Done**: `iemod_fetch_gui`, the `gui`/`guitest` extras and the `iemod-fetch-gui` command, two contracts (the tool never imports the GUI; the GUI imports only `api`, with a test keeping the list complete), and a CI job running pytest-qt offscreen on Linux and Windows. Package skeleton: `iemod_fetch_gui`, `[gui]` extra, import-linter contract (core never imports gui; gui imports only `api`), pytest-qt offscreen in CI | M |
| 15 | **Done**: the phase checks the folders as GAME_IS does while they are typed, and Next saves the project's `iemod-fetch.ini`, which the CLI reads. **1. Game and folders**: game type (EET, BGEE, BG2EE), BGEE/BG2EE folders checked with `gamedir`, language | S |
| 16 | **Done** except prompts (ADR-0033/0035/0036): categories, search, filters "chosen only / conflicts only / updates", the mod -> component tree with tri-state boxes and exclusive SUBCOMPONENT choices, a details pane, `selection.json` on Next; components from the staged tp2, else krion64 (1,471/1,529 against WeiDU); a conflicts tab checked in the background with one-click options (deselect, choose a missing prerequisite, accept to `decisions.json`, the ids `--decisions` matches). Drop-downs for prompts move to M4: only BWS-NG describes prompts as data, for 4 components, and a selection carries no answers yet. **2. Mod selection**: category column, search, filters "selected only / conflicts only / updates", mod → component → choice tree with tri-state checkboxes, radio buttons for exclusive groups, drop-downs for prompts, details pane, conflicts panel with one-click options | L |
| 17 | **Done** (ADR-0038): one tab per install - for EET the BG:EE phase and EET, split by krion64's categories in the saved selection too - in the run's planned order; bold where a rule places a mod, red where an order rule still objects, with the rule; drag to reorder, saved as `install-order.txt` (Project Infinity Sorting Order) and named in the project's ini, so the CLI plans the same order (checked by a test). **3. Install order**: one tab per EET phase, drag to reorder, entries the rules place marked (bold, still movable: a move that breaks a rule is shown), violations marked | M |
| 18 | **Done** (ADR-0039): one page, "Download and extraction" - one step per mod in the engine - with a row per mod (downloading, bytes of total, extracting, done, failed, no download found, cancelled), cancel, resume, "Retry the failed"; it runs the CLI's own run in the project (`api.download_selection`), and with no manifest lcc-docs is the download source (138 of 145 mods of the supplied log have a candidate). Phase 5 is now Installation (M4). **4. Download** and **5. Extraction**: progress per mod and in bytes from the event stream, cancel, retry of the failed ones | M |
| 19 | **Done**: *Load preset...* and *Save preset...* on the mod selection page; a preset is a selection.json byte for byte as the project's (a test compares them), and a WeiDU.log, a BIO share code or a Project Infinity list loads too, told apart by what the file holds and matched to the list ignoring case and `setup-`; what the list lacks is named, never guessed (`api.import_selection`, `api.export_selection`). Presets: save and load `selection.json`, import from WeiDU.log, BIO code and PI csv | S |
| 20 | **Done** (ADR-0040): `packaging/gui_bundle.py`, a `gui` job in the release workflow - Linux and Windows; macOS by `release-macos.yml`, attached after the release when its runner starts - one folder (Qt replaceable, LGPL-3.0), started once offscreen with `--check`, zipped deterministically, attested and in SHA256SUMS, with the LGPL/GPL texts and `NOTICE-Qt.txt`; in the 3.0.0 release the Linux zip is 83 MB and the Windows one 48 MB (60 MB measured locally: the runner's PySide6 wheel is bigger). PyInstaller build per OS in the release workflow, attested, with the Qt LGPL notice | M |

### M4 — Backup and installation (v3.x)

| # | Phase / item | Size |
|---|---|---|
| 21 | **Backup and restore in the tool: done** (ADR-0042: `iemod_fetch/backup.py`, `api.backup_game` / `plan_restore` / `restore_backup`, `--backup`, `--verify-backup`, `--restore-backup [--apply]`); the wizard's page is next. **Backup** phase before installing: copy or zip of the game folder's override, dialogs and WeiDU state, with a restore action | M |
| 22 | **6. Installation**: drives mod_installer (EET mode) or WeiDU directly, streams the output into the window, recognises prompts and answers them only from a recorded answer file (`@wlb-inputs` style); otherwise it asks the player | L |
| 23 | Resume after a failure or cancel; the WeiDU.log is the state | M |
| 24 | A real Windows end-to-end CI job (roadmap F) and live GitHub API contract tests (item A) | M |

Infinity Mod Runner (MIT) has solved most of M4 in a shipped installer, and
is the reference to measure against before each item is designed: per-game
backups with a verify step (21); per-batch Retry / Skip / Stop, checkpoints,
pause and resume, EET's two phases, per-mod timeouts (22, 23); a
reconciliation of WeiDU's exit code with WeiDU.log after every batch that
catches components that "succeeded" without being logged; READLN default
answers kept as configuration; and the File Guard above. Its ideas, and its
MIT data with attribution, may be used; its code is Rust and TypeScript and
is not copied into a Python project.

### M5 — The order and the selection by kind of mod (after 3.0.0)

Asked for on 2026-10-23: use the generic kind of each mod (interface,
graphics, portraits and sound, quests, NPCs and banter, items and spells,
kits, AI and tactics, tweaks, maps, after EET_end...) in the selection and in
the order, as Project Infinity, krion64 and BWS-NG classify them, with the
exceptions where one component must go elsewhere.

What exists in 3.0.0: the order **is** already by kind where krion64 knows
the mod - its 26 categories, in install order (`PRE EET BGEE MODS`, `ENGINE`,
`INTERFACE`, `GRAPHICS`, ... `TACTICAL MODS`, `PORTRAITS`, `EET FINALIZATION`,
`POST EET`), with its position inside the category, and a mod split where
krion64 files one component elsewhere (ADR-0038). Rules then move it: BWS-NG's,
the authors' metadata inis, the player's Sorting Order. Measured gaps:

- krion64 places 813 mods; lcc-docs lists 1,148 for the EE games (2,151 in
  all). A mod krion64 does not know keeps the place of the mod before it in
  the input - from the wizard, a place that depends on the selection's order,
  not on what the mod is.
- lcc-docs has its own 17 categories (Gameplay 403, Kit 262, recruitable NPC
  232, spells and items 225, quest 225, portrait and sound 172, ...) and the
  selection page filters by them; they are not install phases and are not
  mapped to krion64's.
- BWS-NG's and Project Infinity's classifications are not read yet; their
  shape has to be measured first (the session sandbox cannot reach them; a
  workflow can).
- **Infinity Mod Runner** (Anprionsa, MIT, a Tauri/Rust installer, beta
  1.0.2, "1,675 components installed in 12.2 h") and the **Infinity Mod
  Forge** it reads. **krion64's site is the Infinity Mod Forge** (its README:
  "Infinity Mod Forge", formerly "EET Mod Forge"), the data this tool has
  read since M2. The Runner's default address for it,
  `anprionsa.github.io/infinity-mod-forge`, answers GitHub Pages' "Site not
  found" (checked 2026-10-23); the live Forge is `krion64.github.io`. One
  source, counted once; the Runner adds no classification of its own.

| # | Item | Size |
|---|---|---|
| 25 | **Done** (ADR-0041, `tools/order_sources_benchmark.py`): measured on the real files - krion64 is the Forge; BWS-NG's per-component EET sequence (3,232 components) is the second order, disagreeing with krion64 on 21% of pairs and placing 26 mods krion64 does not; lcc-docs classifies 546 EE mods krion64 does not place; the supplied log is the Forge's output. **Audit, measured on GitHub's runners**: every source's classification (krion64's (the Infinity Mod Forge's) categories and per-component `c`, lcc-docs' categories, BWS-NG's, Project Infinity's), how many mods each covers, a mapping from each to krion64's install phases, and where they disagree. On the supplied 145-mod EET log: how many mods have no krion64 place, and how far the order by kind is from the order the player actually installed. ADR-0041 decides from these numbers. | M |
| 26 | **Selection by kind**: one "kind" filter and column in phase 2, from the mapping, each mod showing which source says what; a disagreement is shown, never settled silently. | M |
| 27 | **Order by kind for what krion64 does not place**: such a mod takes the place its kind maps to, marked "placed by kind" with its source in the order page, the plan summary and the JSON plan. It never overrides, in this order: the player's Sorting Order, the authors' inis, BWS-NG's rules, krion64's own place. | M |
| 28 | **Exceptions per component**: a component whose kind differs from its mod's (a tweak pack's portraits, a tactical mod's kits, what goes after EET_end) is split and placed by its own kind, from krion64's and BWS-NG's per-component data; two chosen components known to overwrite the same thing (BWS-NG and krion64 conflict records, `mod-forge.json`) are reported with their order as an option, as conflicts are today. Static analysis of what a tp2 copies is not promised: WeiDU's language can compute any path. What can be measured is what an install really overwrote: Infinity Mod Runner's *File Guard* snapshots the override folder's md5s after each batch and flags a change outside an allowlist of files several mods legitimately write (`guard_allowlist.json`); the same check belongs to M4's installation, and its findings feed this item. | L |
| 29 | **Tests on real data**: fixtures in the shape of the real files (krion64 MIT data may be pinned; BWS-NG's is GPL and is not bundled, so its fixtures are written by hand to its schema), a weekly workflow on the live sources, the 146-mod log as a benchmark (order inversions against the player's order, before and after), and the mock EET install with the real WeiDU on a plan reordered by kind. | M |

### M5b — Editing the order by component (asked for on 2026-10-23)

The player chooses and drops parts of mods, reorders by hand, and the tool
checks the order again and offers fixes. Measured against BWS-NG (GPL, ideas
only), Infinity Mod Runner (MIT) and Project Infinity (docs and wiki) on their
real code: BWS-NG is the reference for component-level ordering (one row per
component, incremental re-check of only the rules a move touches, a per-row
violation panel, "ignore" that comes back on a new break); Infinity Mod
Runner only runs an order made elsewhere; Project Infinity orders mods, and
components through its Sorting Order file. **None of the three re-sorts or
offers a fix after a manual move**; this tool's planner already computes the
smallest moves, so it can.

| # | Item | Size |
|---|---|---|
| 30 | **Split a mod and move one component** on the order page (expand a mod into its components); saved as Sorting Order `tp2 n n` lines, which the CLI already reads. Test: the GUI order and `--plan-order` agree after a split and a move. | M |
| 31 | **Incremental check after a drop** (BWS-NG's technique: re-check only the rules touching what moved, at once; the full re-plan stays in the background). Measured: time to the marks after a drop, p50/p95, on the 146-mod / 780-component log and on a synthetic 3,000-component order; a property test that the incremental result always equals the full check. | M |
| 32 | **Fixes on each flagged row**: "move just after X", "move just before Y", "re-plan keeping my other moves", "turn this component off"; each previewed. Test: a fix leaves no violation of its rule and no new error. | M |
| 33 | **A per-row panel** (must be before / after, the rule's source) and **ignore**, kept in `decisions.json`, shown again when the row moves or a new rule breaks; rules naming a whole mod shown dimmed. | S |
| 34 | **Deselect knowing who depends on it**: unticking a component warns about (or unticks) the ones that need it; one "auto-resolve" (dependencies first, then keep-this). Not BWS-NG's quirk of selecting every target of an "any one of" rule. | M |
| 35 | Multi-row drag, Ctrl+Up/Down and search on the order page; exclusive groups with a default choice and a guard against emptying a required one; a selection hash that skips re-checks when nothing changed. | M |

### M6 — One Python, and the libraries that earn their place (4.0.0; ADR-0043)

Decided by the owner on 2026-10-23: one Python version for everything,
chosen the way Debian chooses a kernel. Audited twice, on PyPI's metadata and
by running the candidates.

| # | Item | Size |
|---|---|---|
| 36 | **Done** but the CLI bundle (`.python-version`, the workflows, pyproject, `iemod_fetch.PYTHON`). **The platform**: `.python-version` (3.14) read by every workflow instead of 20 literal versions in 10 workflows, two test matrices and four settings in `pyproject.toml`; `requires-python = ">=3.14"`; ruff, mypy and the classifiers on it; tests on it, on Linux and Windows (macOS informational). The CLI also ships as a PyInstaller bundle beside the wizard, so a player needs no Python of their own. Breaking: 4.0.0, with a migration note. | M |
| 37 | **Done** (`tools/upstream_versions.py`). **The weekly check** (ADR-0028's `upstream-versions.yml`): the newest stable from actions/python-versions' manifest, and every place that names the version compared; an issue when they disagree or a newer Python is out, and the move made by hand once a full build - wizard and CLI bundles, all tests - passes on the newer one (a pull request opened by a workflow's token would start no CI to prove it). Dependabot cannot do it (verified in dependabot-core: it never touches `python-version`). Next candidate: 3.15, after its build is green - it makes UTF-8 the default on Windows (PEP 686). | S |
| 38 | **Done**. **Mechanical modernisation**, alone in its PR: ruff `UP` rewrites about 890 `Optional`/`List`/... annotations (522 UP006 and 371 UP045 at py314) and 140 typing imports; `hashlib.file_digest`; `datetime.fromisoformat`; tarfile's data filter without the fallback; `PySide6>=6.11`. | S |
| 39 | **publicsuffixlist: done** (net.py, carried in the .pyz and the bundles, `requirements/runtime.txt`); filelock next. **Libraries adopted**, each with a test that fails before it, pinned by hash, scanned by pip-audit: **filelock** (MIT: a lock around the shared data folder, which the GUI and the CLI both write) and **publicsuffixlist** (MPL-2.0, unmodified, licence shipped: `a.github.io` and `b.github.io` are different sites, which the offsite check gets wrong today). **urllib3** only if keep-alive is measured to matter. | M |
| 40 | **7-Zip in the bundles** (about half of lcc-docs' direct download links - 150 of 290 - are .rar, .7z or .exe), after a licence review of the unRAR clause. | S |

Rejected, with the measurement: charset-normalizer (it reads short Cyrillic
`.tra` text as cp1125 and Western text as big5), tenacity and requests-cache
(neither fixes our retry or caching gaps), packaging (mod versions are not
PEP 440), rapidfuzz (difflib is enough), tldextract, vdf, atomicwrites,
keyring, py7zr (LGPL, compiled dependencies, no RAR).

### M7 — Defects the audits found, fixed in the standard library (except the offsite check: publicsuffixlist, item 39)

| # | Defect, reproduced | Fix |
|---|---|---|
| 41 | **Done** (item 39). **Security**: `same_site("https://modder.github.io/m/", "https://attacker.github.io/x.zip")` is true (`registrable_suffix` reduces both to `github.io`), so a link to another user's page escapes the offsite gate. | item 39 |
| 42 | **Done**. **Order**: a stuck sort reports every remaining unit as the cycle and forces the top one even outside it; with A<->B, "C after A" is broken. Measured on the old code with units C, D, A, B (in that priority): the order came out C, D, A, B - C and D both ahead of A - and two cycles were reported, all four units and then A, B. Now: the real cycle (a strongly connected component nothing outside it holds back, Tarjan's algorithm) is reported once, and the unit released is taken from inside it. `graphlib` was not used: `TopologicalSorter` stops at the first cycle (`CycleError`) and cannot release a unit or keep the priority order the plan needs | the real cycle, released from inside it; each cycle reported once; rules outside it hold (3 tests, each failing before) |
| 43 | **tp2**: `~Use "smart" AI~` is read as `Use `; `~~~~~` strings are not read. | reuse `tra.py`'s scanner; real WeiDU as the oracle |
| 44 | **.tra**: non-UTF-8 Russian, Polish, Japanese and Chinese text decoded as cp1252 (or latin-1), silently. | after UTF-8, the code page of the language folder |
| 45 | **GitHub**: a 403 secondary limit is not retried; an HTTP-date `Retry-After` is ignored; no ETag, so repeat runs spend the rate limit. | `email.utils`, an ETag store |
| 46 | **Done**. Nine hand-written atomic writes: seven with one fixed temp name, two with an fsync. Counted again: eight file writes (seven `<file>.tmp`, the config with `mkstemp`) and one fsync, the install state's; the ninth was the download's `.part`, which streams, resumes and fsyncs on its own and stays. | one helper, `iemod_fetch/atomic.py`: a temp of its own per write, removed on failure, mode kept; the review of #55 added the `--conflict-report` writer, which was not atomic at all. **Left**: a temp left by a power cut now has a name of its own, so such leftovers are not overwritten by the next write; nothing sweeps them yet. 8 tests |
| 54 | **Done** (one turn per source - a source, not the URL it resolves to: a review of #52 found a link signing a new URL on each probe downloaded forever). **Catalogue fallback**: with the catalogue alone (`-m ''`, ADR-0039), lcc-docs' direct links go first, and 8 of the 145 mods of the supplied EET log have one on forums.beamdog.com that is not the mod: a save game (Foundling), two `.debug` logs (ntotsc), a compatibility patch (IHateUndead), another mod (A7-GolemConstruction ships SoDGolemFix). The .tp2 check refused each one, and the retry probed the catalogue again and got the same attachment, so the repository or page the same entry lists was never tried. | every source of the entry gets its turn, each downloaded once, the same check on each. Measured: 2 of the 8 now install (Foundling, GAHESH from WeaselMods); the other 6 go to their repository, whose tree has the right tp2 (`git ls-tree`), not measured through the API |
| 55 | **baldurs-gate.de**: a XenForo resource's `/download` answers 301 to `github.com/<owner>/<repo>/releases`, an HTML page, so 4 mods (AC_QUEST, bgqe, c#solaufein, JA#BGT_AdvPack) fail "did not return an archive" or 403. | hand a redirect to a GitHub repository page to the GitHub resolver; to be measured where the GitHub API is reachable |
| 56 | **lcc-docs data**: Dark Tidings' direct link (`baldurs-gate.de/acifer/Dark_Tidings.rar`) is 404; ArtisansKitpack's Beamdog `.rar` holds one sound file (`HIT_07.wav`). | report the links upstream |
| 57 | **Measured where GitHub answers; Cloudflare's three sites from a workstation.** The audit's sandbox refused third-party GitHub repositories and Cloudflare challenges Gibberlings3, SHS and Nexus from any datacenter. The download-sources workflow, on GitHub's runners with a token (2026-10-23): with the catalogue alone 135 of 145 planned (86 release assets, 28 source snapshots, 20 page links, 1 direct), 139 with the manifest; 20 real downloads, 16 installed with their tp2 and 4 over the 300 MB cap (BGGO 1.4 GB, Autumn's Twilight, Classic Movies, Aura) - no wrong archive; the misses are the three Cloudflare sites and mods no source lists. premeta's live check (mod-metadata workflow): all 5 cases as expected. | the workflow takes `real=all` by hand (every planned mod, not 20) and its summary says what the player was told (forum-post copies, newer releases offered, links that led to GitHub); `tools/measure_workstation.py` runs the same steps from a home connection, Gibberlings3 and SHS included, into one folder with `summary.md` to paste back. **Left**: a run of each |
| 58 | **Done.** **A forum's file, silently old**: real downloads of all 145 mods (7-Zip and unar installed) with GitHub out of reach installed Ascension from a Beamdog thread as v1.5 BETA (its repository: 2.1.0) and Finch as v4.0 (v6.0), with nothing to say so - the tp2 check cannot tell an old copy from a new one. Without a token, 115 GitHub mods exceed the 60 requests an hour, so a player can meet this. | a forum thread or attachment (`urls.is_forum_post`) is tried after the entry's direct links, repository and other pages, and installing from one adds an advisory with the post and the declared version (ADR-0039 amendment, the owner's decision). Measured: both now carry it |
| 59 | **Done** but the wizard's button. **A newer release, offered**: a copy from anywhere but GitHub (a forum post, an author's site) said nothing when its repository had a newer release - Ascension v1.5 BETA against 2.1.0. | the run compares the copy's tp2 VERSION with krion64's latest release of the repository called like the mod (`compare_published`; nothing when unrankable, never a fork's), puts it in the record as `newer` and beside the mod, and `--take-newer FOLDER`/`all` installs that release over the copy (kept in `.backup/`), or leaves the copy if GitHub cannot give it. Measured: Ascension offered 2.1.0 (Gibberlings3/Ascension), finchnpc nothing (its scanned repository a fork). **Left**: the button on the wizard's download page, reading `newer` |

### M8 — What the other projects do and this tool does not (feature audit)

Read on their code and data (Infinity Mod Runner, the Forge, BWS-NG, Project
Infinity). Ranked by value to a player installing a large EET setup.

| # | Item | From | Size |
|---|---|---|---|
| 47 | **Known-issue classifier** for install output: the Forge's 37 general patterns and per-mod `ki` matched against WeiDU's output and WSETUP.DEBUG (today only their descriptions are shown, before installing). Measured on a labelled corpus. | IMR, Forge (MIT) | M |
| 48 | **Prompts known before installing**: every `ACTION_READLN` in the staged tp2s plus the Forge's manual-step notes, and whether an answer is recorded. Never IMR's "answer 1 after 30 s" (ADR-0005). | IMR | S |
| 49 | **Preflight**: free disk space for the plan and the backup; the WeiDU binary's version against the newest and against what mods need. | IMR, BWS-NG | S |
| 50 | **Update signal from lcc-docs' dates** (ADR-0044): between 30 and 55 of the supplied 149 mods, depending on how they are matched, have no GitHub release krion64 can see, only an lcc-docs date (ADR-0044). | lcc-docs | S |
| 51 | Release notes and activity (`body`, `pushed`) in the update view; the Forge's `in`, `rec` and `eet_compat` notes in the selection. | Forge | S |
| 52 | An opt-in set of community patches for known mod bugs (IMR's 62, idempotent), with sha256 before and after; needs its own ADR - it changes mod content. | IMR (MIT data) | M |
| 53 | `AT_EXIT` scripts kept beside a mod's folder (to be checked first); install-time estimate and slow-component notice; a post-install report and a diagnostic bundle with paths removed; a translated wizard. | IMR, BWS-NG | M |

**Explicitly not planned:**
- Copying any BIO, BWS-NG or mod_installer code.
- Bundling GPL data.
- A web or Tauri front end. The API allows one later, but none is planned.

---

## Phase 3 — Validation

| Milestone | Done when |
|---|---|
| M1 | A test builds a selection from `mods --json` alone, plans and fetches it in **one** run with no WeiDU.log, and validates every output against its JSON Schema.<br>`--events jsonl` emits progress for every byte range, and a cancel stops the run within one chunk.<br>`cli.py` contains no planning logic: `lint-imports` gets a contract that only `cli` and `ui` import `api`.<br>Every existing test still passes. |
| M2 | `describe` gives the right component names in English and one other language for a fixture set of real tp2/tra pairs (EET, SCS, BG1NPC).<br>Every conflict in the fixture EET plan has at least one option, and applying it leaves the plan free of that conflict.<br>A BIO share code goes through import and export without losing anything. |
| M3 | A pytest-qt test, run offscreen on Windows, Linux and macOS, goes through phases 1-5 on a fixture EET selection: picks components, resolves a conflict, reorders, downloads from a local fixture server, cancels and resumes.<br>The `selection.json` it saves is byte-identical to the CLI's for the same choices.<br>The window never blocks for more than 100 ms during a download.<br>The `.pyz` stays standard-library only, and the PyInstaller build starts on all three OSes. |
| M4 | The mock EET plan installs end to end from the GUI on Windows and Linux runners with the real WeiDU and mod_installer.<br>Cancelling mid-install, then resuming, finishes with the same WeiDU.log as an uninterrupted run.<br>A prompt without a recorded answer stops and asks; it is never answered by guess.<br>Restoring the backup gives back the game folder as it was. |
| M5 | Every mod of the 146-mod log has a place from krion64, BWS-NG's sequence or a decisive kind, with its source named, or is marked as having none; none is placed silently (ADR-0041).<br>The plan's disagreements with BWS-NG's sequence (independent of krion64; the supplied log is the Forge's own output) are measured and published, and shown to the player.<br>Each source's classification is read from its real files by a weekly workflow, and a change in its shape fails that workflow, not a player's run.<br>A plan reordered by kind installs with the real WeiDU in the mock EET job. |
| M5b | After a split and a move in the wizard, the GUI's order and `--plan-order`'s agree; the incremental check equals the full one after random sequences of moves (property test), and its time after a drop is measured on the 146-mod log and a 3,000-component order; every offered fix leaves its rule satisfied and adds no error. |
| M6 | One `.python-version` names the version every workflow, `requires-python`, ruff, mypy and the classifiers use, and the weekly check fails when one disagrees; the CLI and the wizard bundles start on a machine with no Python; each adopted library has a test that failed without it, is pinned by hash and passes pip-audit. |
| M7 | Each defect has a test reproducing it, red before its fix and green after; the tp2 one is checked against the real WeiDU. |
| M8 | Each item ships with its own measurement: the classifier's precision and recall on a labelled corpus, the prompts found against the prompts met in a real-WeiDU run, the update signals on the supplied logs. |

**M3, as released in 3.0.0.** `tests/gui/test_m3_end_to_end.py` drives the real main window,
offscreen, through phases 1-4 on a fixture EET selection: the project's ini,
components chosen and a conflict resolved, a mod reordered, then the real
download from a loopback `http.server`, cancelled while a mod is still
arriving (the page says so, nothing half-installed is in the target) and
resumed (only what was not done is fetched again). The catalogue, the
conflict check and the planner are injected there - the real ones fetch
community data - and tested against the command line on their own. Phase 5 is installation
now (item 18), so it belongs to M4. What each criterion stands at:

- Phases 1-4 offscreen: CI's GUI job runs it on Linux and Windows (a gate),
  and `macos.yml`'s GUI job on macOS (informational, as all of macOS is since
  its runners stopped starting on 2026-10-21).
- `selection.json` byte-identical to the CLI's: **met** - the wizard's file
  equals what `iemod-fetch --emit-selection` writes from WeiDU.logs that
  install the same components under the same names (asserted in the same
  run). A real log that spells a tp2 in capitals gives that spelling, not
  the catalogue's, so the two then differ in case only.
- Never blocked for 100 ms during a download: **met on Linux** - the longest
  gap of a 10 ms timer during both downloads is 11-16 ms, 32 ms with every
  core busy; the same assertion holds on every OS CI runs it on.
- The `.pyz` standard-library only: kept by the `stdlib-only` CI job until 4.0.0; since ADR-0043 it carries its runtime libraries inside, checked by the same job.
- The PyInstaller build starts on all three OSes: **met** (item 20,
  ADR-0040). In #42's CI the Linux and Windows bundles were built, unzipped
  and started with `--check` by the release rehearsal, and the macOS one by
  `release-macos.yml`'s.

Gates that apply throughout: pytest, ruff, mypy, import-linter, bandit,
actionlint, zizmor, and the real-WeiDU job. A UI change is the same pull
request process as any other.

## Sources

- [BIO](https://github.com/Born2BSalty/Born2BSaltys_Infinity_Orchestrator) (read at 33800cc)
- [BigWorldSetup-Next-Generation](https://github.com/Selphira/BigWorldSetup-Next-Generation) (f7befca)
- [lcc-docs](https://github.com/RiwsPy/lcc-docs) (6d73f77)
- [mod_installer](https://github.com/dark0dave/mod_installer) (3b6827a)
- [krion64 Forge](https://github.com/krion64/krion64.github.io) (a8d17c4)
- [Infinity Mod Runner](https://github.com/Anprionsa/infinity-mod-runner)
- [WeiDU Install Tool](https://github.com/InfinityTools/WeiduInstallTool)
