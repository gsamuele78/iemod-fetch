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

| # | Item | Size |
|---|---|---|
| 9 | `iemod-fetch describe MOD --json`: components with names resolved through `.tra` for the chosen language, plus SUBCOMPONENT/GROUP/LABEL/DEPRECATED. The `muc`/`sub` vocabulary is taken as an idea from BWS-NG. **Names and SUBCOMPONENT done** (`--describe-mods`, 9,889/9,889 against WeiDU 251); GROUP, LABEL and DEPRECATED not yet | L |
| 10 | Conflicts as **options** (drop a side, move before or after, each with its cost), and a `decisions.json` input that is applied and re-checked. **Done** (ADR-0033): every finding of the mock EET plan has options, and each applicable one clears it (`tests/test_decisions.py`) | M |
| 11 | Freshness: installed vs latest per mod, from a cached weekly release scan (roadmap E2/E4). **Done**: krion64's daily release cache plus BWS-NG and krion64 versions, the newest of the three (79/90 against tp2 VERSION); `installed`, `latest`, `update_available` in `--list-mods` | M |
| 12 | BIO share-code **import/export** (format only) | S-M |
| 13 | Read Project Infinity `weidu-log.csv` and krion64 `mod-forge.json` | S |

### M3 — The wizard up to download (v3.0)

ADR-0031: `iemod_fetch_gui`, PySide6, importing only `iemod_fetch.api`. The
phases are BWS-NG's order. Each phase saves a file the CLI also reads, so a
run can be stopped and resumed, or finished from the command line.

| # | Phase / item | Size |
|---|---|---|
| 14 | Package skeleton: `iemod_fetch_gui`, `[gui]` extra, import-linter contract (core never imports gui; gui imports only `api`), pytest-qt offscreen in CI | M |
| 15 | **1. Game and folders**: game type (EET, BGEE, BG2EE), BGEE/BG2EE folders checked with `gamedir`, language | S |
| 16 | **2. Mod selection**: category column, search, filters "selected only / conflicts only / updates", mod → component → choice tree with tri-state checkboxes, radio buttons for exclusive groups, drop-downs for prompts, details pane, conflicts panel with one-click options | L |
| 17 | **3. Install order**: one tab per EET phase, drag to reorder, entries the rules fix are locked, violations marked | M |
| 18 | **4. Download** and **5. Extraction**: progress per mod and in bytes from the event stream, cancel, retry of the failed ones | M |
| 19 | Presets: save and load `selection.json`, import from WeiDU.log, BIO code and PI csv | S |
| 20 | PyInstaller build per OS in the release workflow, attested, with the Qt LGPL notice | M |

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
