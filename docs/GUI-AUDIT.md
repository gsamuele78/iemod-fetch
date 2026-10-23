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

### M3 — The wizard up to download (v3.0)

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
| 20 | **Done** (ADR-0040): `packaging/gui_bundle.py`, a `gui` job in the release workflow - Linux and Windows; macOS by `release-macos.yml`, attached after the release when its runner starts - one folder (Qt replaceable, LGPL-3.0), started once offscreen with `--check`, zipped deterministically, attested and in SHA256SUMS, with the LGPL/GPL texts and `NOTICE-Qt.txt`; the Linux zip is 60 MB. PyInstaller build per OS in the release workflow, attested, with the Qt LGPL notice | M |

### M4 — Backup and installation (v3.x)

| # | Phase / item | Size |
|---|---|---|
| 21 | **Backup** phase before installing: copy or zip of the game folder's override, dialogs and WeiDU state, with a restore action | M |
| 22 | **6. Installation**: drives mod_installer (EET mode) or WeiDU directly, streams the output into the window, recognises prompts and answers them only from a recorded answer file (`@wlb-inputs` style); otherwise it asks the player | L |
| 23 | Resume after a failure or cancel; the WeiDU.log is the state | M |
| 24 | A real Windows end-to-end CI job (roadmap F) and live GitHub API contract tests (item A) | M |

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

**M3 so far.** `tests/gui/test_m3_end_to_end.py` drives the real main window,
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
- `selection.json` byte-identical to `api.save_selection`'s for the same
  choices: **met** (asserted in the same run).
- Never blocked for 100 ms during a download: **met on Linux** - the longest
  gap of a 10 ms timer during both downloads is 11-16 ms, 32 ms with every
  core busy; the same assertion holds on every OS CI runs it on.
- The `.pyz` standard-library only: kept by the `stdlib-only` CI job.
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
