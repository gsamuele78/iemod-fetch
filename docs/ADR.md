# Architecture Decision Records

Format: context → decision → consequences. One record per decision that a future
maintainer would otherwise be tempted to reverse.

---

## ADR-0001 — Keep it stdlib-only, but stop being a single file

**Context.** The original is one 683-line script with no dependencies. The
portability is genuinely valuable: it runs on a fresh Windows box next to the
game install with nothing but CPython. But it is untestable as written — network,
filesystem and policy are interleaved in every function.

**Decision.** Keep the zero-runtime-dependency constraint. Split into a package
of small modules with injectable seams (`HttpClient`, `sleep`, `client`) so every
policy decision is unit-testable offline. `pytest` is a *test-time* dependency
only.

**Consequences.** Deployment is a directory instead of a file (or `python -m
zipapp` for a single `.pyz`). In exchange, 170 tests run in ~1 s with no network.
Anyone who insists on one file can `zipapp` it; nobody has to fork it to test it.

---

## ADR-0002 — One name, three jobs: split them

**Context.** The manifest's `tp2` field was used simultaneously as catalogue id,
install directory name, and identity check. Your real data proves those are
different strings: 30 differ by case, 10 differ outright. Fuzzy matching was
introduced to bridge the gap and then leaked into verification, where it made
every check pass (`find_tp2_in_dir` ends in `return True`).

**Decision.** Three separate concepts:

| Job | Source of truth | Matching |
|---|---|---|
| Install directory | the WeiDU log folder, verbatim | none — it *is* the name |
| Catalogue lookup | manifest `tp2` key | exact → explicit alias file → suggestion |
| Identity check | `.tp2` inside the artefact | strict: `<f>.tp2` or `setup-<f>.tp2` |

Fuzzy matching may **propose**; it may never **decide**. Suggestions are printed
and written to the JSON report; applying them requires `--accept-suggestions` or
an `aliases.json` under version control.

**Consequences.** 10 mods need a one-time human decision instead of being
silently mis-installed. `aliases.json` (shipped, 9 entries) reduces that to 1 —
`HPS_PORTRAITS_PROJECT`, which genuinely has no source. Strictness is free: it
identifies 148/148 real mods correctly.

---

## ADR-0003 — Credentials are scoped to an exact host allowlist

**Context.** The token was attached to every request, reaching 9 third-party
hosts (3 over cleartext). Redirect stripping used a substring test that a
lookalike host defeats.

**Decision.** `headers_for(url)` attaches the credential only when the host is
exactly `api.github.com` or `github.com`. Not a suffix test, not a substring
test. On redirect, the credential is dropped for any host outside that set —
including GitHub's own `objects.githubusercontent.com`, which rejects it anyway.
Non-https is refused unless `--allow-http`, and a redirect may never downgrade.

**Amendment (ADR-0005a) — restoring automatic acquisition without the impersonation.**
Removing the device flow removed the convenience along with the problem. Two
providers put it back using credentials the machine already has, minted by
tools the user already trusts: `gh auth token`, and `git credential fill`
against git's configured helper (Git Credential Manager on Windows holds a
GitHub token after any HTTPS push). The credential-helper probe is forced
non-interactive on every channel — `credential.interactive=false`,
`credential.guiPrompt=false`, `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`
— because a mod download must never trigger an auth prompt, and the value is
accepted only if it matches a GitHub token shape, so a stored username/password
is never sent as a bearer.

**Consequences.** The three `http://` entries in your manifest now need an
explicit `--allow-http`. That is the correct friction: you should know you are
fetching mods over cleartext.

---

## ADR-0004 — Integrity is the manifest's job; the tool makes it possible and records it

**Context.** Your manifest has no `sha256`, no `release_tag`, no version. Your
WeiDU logs record no versions either. Nothing downstream can verify that today's
download is what was installed last time, and "latest" drifts.

**Decision.** The tool cannot invent trust it doesn't have, so it does three
things instead of pretending:

1. **Honours** optional `sha256`, `release_tag` and `asset` fields when present —
   a pinned download is verified before extraction and rejected on mismatch.
2. **Records** what it actually fetched — sha256, resolved URL, release tag, tp2
   filename — into `Mods/.iemod-fetch-state.json` on every run.
3. **Reports** the same in `--json-report`.

**Consequences.** Run once, commit the state file, and you have a lockfile you
can promote into the manifest as `sha256`/`release_tag`. This is the only path
from "it worked on my machine in September" to a reproducible install. Until you
do that, every run is best-effort and the tool says so rather than implying
otherwise.

---

## ADR-0005 — Resolution never guesses

**Context.** On failure the script mutated repo names and finally installed the
top hit of a GitHub code search — a name anyone can register.

**Decision.** Exact repository, or an honest `MANUAL` with the reason and the
URL. No name mutation, no search fallback, no "first plausible link on the page"
across hosts. Landing-page links must be same-site to be auto-selected.

**Consequences.** More mods land in the manual bucket than before. That number
was always the truth; the old script hid it behind guesses. The manual list is
actionable: reason, URL, target directory, and suggested catalogue entry.

---

## ADR-0006 — Extraction is contained, and never executes anything

**Context.** `extractall()` on both zip and tar with no validation; `.exe`
handled as an archive.

**Decision.** Validate every member before writing (traversal, absolute paths,
symlinks, special files), enforce entry-count / total-size / compression-ratio
ceilings, use `filter="data"` for tar, and re-audit the extracted tree for
escaping symlinks. A `.exe` is never run — it is only *read* by `7z`/`unar`, and
only when `--allow-exe` is given. A missing unpacker is an explicit error naming
the package to install, never a silent skip.

**Consequences.** Some exotic archives will be refused rather than extracted. A
refusal you can read beats a traversal you cannot see.

---

## ADR-0007 — The destination directory is never deleted

**Context.** `shutil.rmtree(mod_dest_dir, ignore_errors=True)` ran on every error
path, including for directories the script had not created.

**Decision.** Extract to `Mods/.staging/<folder>-<uuid>/`, verify the strict
`.tp2` is present, and only then move into place. An existing destination is a
`CONFLICT` unless `--force`; `--force` *moves* it to
`Mods/.backup/<folder>.<timestamp>`. Failure at any stage leaves the destination
byte-for-byte unchanged.

**Consequences.** `.backup/` accumulates and is yours to prune. Disk cost is
bounded and recoverable; deleted hand-edits are not.

---

## ADR-0008 — Release discovery scoped to trusted owners

**Status.** Accepted; amends ADR-0005 ("resolution never guesses").

**Context.** 38 of the 148 catalogue entries have no `github` field, and the
supplied manifest contains stale pointers — five entries name
`SpellholdStudios`, the account Spellhold Studios abandoned in 2022 when its
owner disappeared, whose mods now live in `Spellhold-Studios`. Every one of
these lands in the manual bucket, which is correct but not helpful.

ADR-0005 removed the legacy global search
(`api.github.com/search/repositories?q=<name>+in:name` → install `items[0]`).
The objection to it was never "searching"; it was the **trust boundary**: the
search space was the whole of GitHub, a namespace anyone can register in, and
the top hit was installed with nothing standing between it and the game
directory.

**Decision.** Add discovery with a different boundary and a gate.

* **Bounded search space.** An explicit owner allowlist, defaulting to the
  shipped modding houses plus every owner the manifest already depends on. An
  owner your catalogue already trusts is one you have already accepted;
  `--trusted-owners` replaces the list, `--trusted-owner` extends it.
* **A hit is a candidate, not a decision.** The artefact still has to contain
  `<folder>.tp2` or `setup-<folder>.tp2` to be installed. A wrong repository
  inside a right owner fails verification and is reported — asserted by
  `test_a_discovered_repo_with_the_wrong_tp2_is_not_installed`.
* **Catalogue always wins.** Discovery runs only after the manifest entry fails
  to resolve; a working entry never triggers an index build.
* **A guess becomes a fact.** Every discovered source is printed under
  "DISCOVERED SOURCES" as a ready-to-paste `"github"` value and recorded in the
  JSON report, so the next run is deterministic.
* **Bounded cost.** Owner listings are paginated and cached to disk for 24 h —
  roughly one API call per owner, against 148 per-mod calls.

**Consequences.** Mods whose catalogue entry rotted become installable again
without hand-editing, and the SHS migration resolves itself. The residual risk
is a compromised trusted owner, or a fork inside a trusted owner carrying a
matching `.tp2` — forks and archived repos are ranked down, and the answer to
both is pinning (ADR-0004): once discovered, pin the sha256 and the question
stops being reopened. `--no-discovery` restores strict ADR-0005 behaviour.

This is the one place where the tool searches rather than looks up, so the
default is loud: it says what it found, why, and what to write down.

---

## ADR-0009 — Supplementary catalogues

**Status.** Accepted; extends ADR-0008.

**Context.** `mod_downloads.json` gives one URL per mod and no integrity or
health metadata. 41 of the 148 entries had no resolvable repository, and one
WeiDU folder had no catalogue entry at all.

The community maintains far richer databases. The La Couronne de Cuivre list
(<https://github.com/RiwsPy/lcc-docs>, MIT, descended from FreddyGwendo's and
JohnBob's lists) publishes `db/mods.json`: ~2,100 WeiDU mods with tp2 name,
every known download URL, a maintenance status and a 0/1/2 quality rating, all
CI-validated against a pydantic schema. Measured against the supplied data it
covers **142 of the 148** installed mods.

**Decision.** Accept a supplementary catalogue as a *second* source of
resolution and as a source of advisories — never as an authority.

* **Order.** Manifest entry → supplementary catalogue → trusted-owner discovery
  → manual. Curated data outranks name similarity; the manifest outranks both.
* **Same gate.** A catalogue hit is a candidate. The archive still has to
  contain `<folder>.tp2`. `Vampire_World` resolves to
  `Spellhold-Studios/Miscellaneous`, a collection repository — exactly the case
  the gate exists for.
* **Advisories, not vetoes.** `safe` and `status` become warnings in the run
  report. The catalogue's opinion that a mod is beta or obsolete is worth
  surfacing; it is not grounds for refusing to fetch something you asked for.
* **Never bundled, never auto-fetched.** It is third-party data with its own
  licence and cadence. You pass `--catalogue PATH`. Only a 16-entry sample is
  vendored, as a test fixture, with attribution.
* **Prefer baking it in.** `tools/enrich_from_lcc.py` writes the resolved
  repositories into the manifest with provenance in `notes`, so the lookup
  happens once and ends up in a reviewable diff.

**Correction (measured after the fact).** An earlier reading of this data
concluded the catalogue held no direct download URLs. That was wrong: it holds
**269 across 262 mods** (~12%), which its own model flags as `is_direct_archive`
and its page renders with a padlock. The zero was an artefact of looking only at
the 142 mods in one install, none of which happened to have one but `vampire_world`.
Resolution order inside a catalogue entry is therefore: **direct archive URL →
repository → landing page**. A direct URL needs no API call and leaves no doubt
about which asset is meant. `vampire_world` is the case that proves it: its
repository is `Spellhold-Studios/Miscellaneous`, a collection whose release
assets are other mods, while the catalogue's direct link points straight at
`Vampire_world_mod_v.0.56_EET.zip`.

**Consequences.** Entries needing a landing-page scrape drop from 41 to 26 on
the supplied data, and a mod absent from the manifest entirely becomes
resolvable. The 21 WeaselMods entries stay — WeaselMods self-hosts and is not
on GitHub, which no catalogue can change. A stale catalogue can point at a dead
repository; that fails resolution and falls through to discovery, which is the
same path as any other rotted URL.

---

## ADR-0010 — Health advisories are printed, and judged per game

**Status.** Accepted; extends ADR-0009.

**Context.** Two questions about the catalogue metadata: should a mod's
obsolete/problem status be shown even when the download succeeds, and can the
`games` tags catch mods that do not belong in an EET build?

Measuring first. Across the 148 installed mods the catalogue lists 322 URLs:
116 GitHub repository or release pages, 206 forum and landing pages, and
**zero direct archive links**. That settles what a catalogue is good for — see
the consequences below.

**Decision.**

* **Advisories are printed, not filed.** A health warning appears indented
  under the mod as it is installed, and again in a `MOD HEALTH WARNINGS` block
  at the end. Previously they were warnings in the JSON report, which is where
  you look after something has gone wrong rather than before.
* **They never block.** The catalogue's opinion that a mod is beta or
  "may cause problems" is information; it is not grounds for refusing to fetch
  something you asked for. Only verification failures stop an install.
* **Compatibility is judged per log, never globally.** Each WeiDU log gets its
  own game. EET is inferred from the log itself (a log that installs the `eet`
  mod is an EET install); anything else stays unknown unless you write
  `-w WeiDUBGEE.log:BGEE`. An unknown game produces **no** warnings.

That last point is the whole reason this is per-log. `bg1ub` is tagged
BG/Tutu/BGT/BGEE/SoD and not EET — but it lives in the BGEE log, where it is
entirely correct. A global EET check would have flagged it, and one confident
false positive on a 148-mod install teaches you to ignore the other twelve.
Judged per log, the supplied data yields exactly two real flags:
`BloodiedStingsOfBarovia` (BG2EE only) and `impasylum` (BG2/BGT only).

**Consequences.** Thirteen of the 148 mods now carry a visible warning. The
catalogue's `games` list can lag reality — a mod may work under EET before the
list says so — so these are advisories, not verdicts, and they say which
catalogue said it. `conflicts` data exists in the schema but is sparse (zero
records touch this install), so it is captured and exposed but not yet
surfaced as a warning; promoting it would mean promising a completeness the
data does not have.

---

## ADR-0011 — A navigation link is not a download

**Status.** Accepted. Written after the first real run.

**Context.** Twenty mods — every WeaselMods entry in the install — downloaded the
same file. `SotSC`, `TotDG`, `Innershade`, `ISNF`, `Ooze`, `Yvette`, `VerrBG2`,
`Foundling`, `GAHESH`, `WhinHill`, `Bristlelick` and the rest all resolved to
`downloads.weaselmods.net/download/alabaster-sands/`.

The cause was arithmetic. A link matching `/download/…/` scored 20 for looking
download-ish. On a site whose sidebar lists every mod it hosts, twenty links
scored 20, no link scored more, and the sort is stable — so the alphabetically
first entry won, for every mod on the site. This is legacy defect L12 wearing a
different hat: the tool guessed, and guessed consistently wrong.

**Decision.**

* **A minimum score to be used unattended.** `_MIN_LINK_SCORE = 40`, deliberately
  above the 20 that "looks download-ish" earns. A `wpdmdl=` link scores 90, a
  `do=download` link 80, a direct archive 100. A bare nav entry cannot clear the
  bar on its own.
* **Sibling pages are rejected outright.** `/download/alabaster-sands/` reached
  from `/download/shades-of-the-sword-coast/` shares a parent and differs in the
  last segment: it is another entry in the same listing, so it is another mod.
  This holds even when the sibling is a real `.zip` — another mod's archive is
  still another mod's archive.
* **A link carrying this page's own slug is preferred** (+30).
* **Forum interstitials are unwrapped.** `…/leaving?target=<url>` yields its
  target rather than the wrapper page.
* **Nothing is better than something wrong.** When no link clears the bar the
  mod is reported, with an explanation and an instruction to pin the URL.

**Consequences.** Some pages that previously "resolved" now report instead. That
number was always the truth. The alternative is twenty copies of the wrong mod
installed under twenty right names — the failure mode this whole rewrite exists
to prevent.

---

## ADR-0012 — The mod's own .tp2 is the authority

**Status.** Accepted; supersedes part of AUDIT.md and amends ADR-0004 and ADR-0010.

**Context.** `AUDIT.md` states that this install "cannot be reproduced from these
files", because no WeiDU log line carries a version and the manifest pins
nothing. That was true of the two input files and wrong as a conclusion: a
WeiDU mod declares its own version, and after installing we are holding it.

```
VERSION ~v9.2.1~
REQUIRE_PREDICATE GAME_IS ~bgee sod bg2ee eet~ @2
```

**Decision.** After a successful install, read the mod's `.tp2` (`iemod_fetch/tp2.py`)
and use what it says over what anything else guessed:

* **Version.** Recorded in the state file and shown in the report, preferred over
  the GitHub release tag. Mods fetched from a forum page — which have no tag at
  all — now have a recorded version for the first time.
* **Compatibility.** `GAME_IS` / `GAME_INCLUDES` / `ENGINE_IS` is what the mod
  itself requires, so it settles disagreements with the catalogue: it withdraws a
  false alarm (the catalogue's `games` list lags reality) or raises a
  better-founded one. A tp2 that declares nothing has no opinion — silence means
  "installs anywhere", never "incompatible".
* **Names.** The catalogue's `tp2` field is the mod's real tp2 name, which is how
  `Reflections` (WeiDU log) is matched to `Reflections_of_Destiny.tp2` (archive)
  with no manual configuration. Values that are plainly display names — "NSC
  Portraits" — are rejected: a tp2 has no spaces.

When a mod is accepted under a name other than the WeiDU folder, it is installed
under the name the **archive** uses, because that is what WeiDU requires, and the
rename is reported.

**Consequences.** `expect_tp2` remains in the manifest as an explicit override for
cases no catalogue knows, but is rarely needed. The parsing follows
`scripts/manager/tp2.py` in lcc-docs (MIT); its `GAME_IS` exclusion is anchored
with `.*` under DOTALL, so a single `? 1 : 0` anywhere in a file suppresses every
match in it — re-implemented here with the exclusion restricted to the adjacent
idiom, and a test pinning that.

---

## ADR-0013 — Checking the install, not just fetching it

**Status.** Accepted.

**Context.** The tool answered "can I obtain these mods?" but not "is this
install sound?" — and `WeiDU.log` already contains everything needed to answer
the second question offline: every component, in install order.

Two data sources exist for the rules:

* **The mods themselves.** A Project Infinity `[Metadata]` ini carries
  `Before=` / `After=` lists of tp2 names (`modmeta.py`). A mod shipping one
  needs no external data at all.
* **Community rule sets** in the BigWorldSetup-Next-Generation shape —
  `order.json`, `incompatibilities.json`, `dependencies.json`, ~850 rules,
  themselves largely harvested from those ini files. Syntax:
  `modA(-):modB(100)|modC(1,2)` with a direction and a severity, where `(-)`
  means any component.

**Decision.** Add a checker (`rules.py`) that reports and changes nothing.

* **One log is one game install.** Two logs — an EET game and a BGEE game — are
  never merged before checking. Merging them compared positions across separate
  installs and invented order violations that cannot exist; the first run
  against the real data produced two such false alarms.
* **Errors and warnings stay distinct.** A missing dependency or a known
  conflict is an error and sets a non-zero exit; an ordering rule is a warning,
  because ordering advice is heuristic and a knowingly unusual order is a
  legitimate choice.
* **An unparseable component list widens the rule** rather than dropping it. One
  real entry reads `(3183.4.1)`; a rule that is hard to read is not a rule that
  should be ignored.
* **`--check-only` touches no network at all** — logs plus rules, nothing else.
  It is the fast pre-flight before a long fetch, and it works on a machine with
  no connectivity.

**Consequences.** Against the supplied logs this finds 6 errors and 12 warnings,
including two the manifest could never have surfaced: `eet` is installed without
`EET_end` (EET installs in two parts), and `TDDz` is installed without `TDD`.
The rule sets are third-party data with their own cadence and are neither
bundled nor fetched — you pass `--rules`. Nothing is reordered or uninstalled:
WeiDU order is the user's to change, and a tool that silently rewrote an install
order would be far more dangerous than one that points at it.

---

## ADR-0014 — Rules go stale; say so rather than pretending otherwise

**Status.** Accepted; amends ADR-0013.

**Context.** A community rule set is a snapshot. If a mod author fixes a conflict
and ships a new version, the rule stays and the checker starts crying wolf. The
rule files carry no version qualifier — their keys are `rule`, `direction`,
`severity`, `description`, `translations` and occasionally `source_url` — so a
rule cannot say "fixed in v5.1". Left alone this decays into noise, and a
checker people learn to ignore is worse than no checker.

**Decision.** Four mechanisms, in descending order of reliability.

1. **A mod's own `[Metadata]` ini wins on ordering.** It travels inside the
   version you downloaded, so it cannot be stale about itself: a developer who
   fixes an ordering problem and updates the ini ships the correction with the
   next release. Community *ordering* rules for a mod that carries its own ini
   are dropped. This is the only genuinely self-updating channel — and it covers
   ordering only, because the PI ini format expresses `Before`/`After` and
   nothing about conflicts.

2. **Version-baseline staleness.** The rules' companion mod database records the
   version each mod was at when the rules were written; the installed mod
   declares its own version in its `.tp2` (ADR-0012). When the installed version
   is **newer** than the baseline, the finding is reported but **not counted** —
   it cannot gate an exit code — and is labelled with both versions and told to
   check the changelog. On the supplied install this correctly withholds two
   findings about `HiddenGameplayOptions` (v5.2 installed, rules written against
   5.0).

3. **Recorded verifications.** `--suppress` takes a JSON file of rules you have
   checked, each with a reason, a date, and optionally a `verified_version` that
   only takes effect once you are actually on the fixed release. Reviewable in a
   diff, like `aliases.json` and `corrections.json`.

4. **Visible age.** The rule set's own date is printed, and past 180 days it says
   so.

**Consequences.** Some real problems will be withheld because the mod moved on
without the rule being wrong. That is the correct trade: a false "not counted"
costs a line of output, a false error costs the user's trust in every other
finding. Version comparison refuses to rank pairs it cannot (`vEAOB.9` against
`Alpha 3`), and an unrankable pair never claims staleness.

**Deliberately not done.** Parsing a mod's readme or changelog for "fixed the
conflict with X". That is free prose; extracting a compatibility claim from it
would be exactly the guessing this project exists to remove. The tool points at
the mod and the two versions and lets a human read one changelog.

---

## ADR-0015 — Two rule sources, and where an unreleased build sits

**Status.** Accepted; extends ADR-0013 and ADR-0014.

**Context.** A second community data set exists (krion64.github.io): 814 per-mod
JSON files carrying `conflicts` and `dependencies` inline, ~1,020 conflict and
135 dependency entries, plus an `ord` install-order category and a version per
mod. It overlaps BigWorldSetup-Next-Generation but is not a duplicate of it.

Run against the supplied install the two disagree instructively. BWS-NG raises
18 findings; krion64 raises **none** by default. Neither is broken: BWS-NG rules
mostly say `(-)` — *any* component of mod A conflicts with *any* of mod B —
while krion64 names exact components (`#1500 #1510`). The precise rules correctly
decline to fire because those particular components are not installed. Coarse
rules catch more and cry wolf more; precise rules do the opposite.

**Decision.**

* **Load both, auto-detecting the shape.** `--rules` accepts either a rule-list
  file or a directory of per-mod records; the format is detected per file.
* **Optional integrations are off by default.** krion64 marks 96 dependencies
  `soft` — "Alternate portraits for X" is an enhancement, not a prerequisite.
  Eleven of those buried the one real missing prerequisite in the first run, so
  they need `--include-optional`.
* **An order-sensitive pair with no direction is counted, not guessed.** 375
  entries say two mods are order-sensitive without recording which way round.
  The count is reported; a direction is never invented.
* **`evidenceLevel` is carried into the message** so `mechanism-verified` reads
  differently from an unsourced claim.

**Version ordering for unreleased builds.** A repository that publishes no
release is fetched as a snapshot of its default branch, and the branch name is
recorded as the version (ADR-0011). The ordering is

    branch snapshot  <  alpha  <  beta  <  rc  <  a numbered release

This is a *stability* order, not a chronological one — `master` is usually newer
code than the last tag. Ranking it lowest is deliberate and conservative: under
ADR-0014 a newer installed version withholds a finding as possibly stale, so
treating a snapshot as "newer" would silently suppress real conflicts. A
snapshot never suppresses anything.

**Consequences.** Running both sources gives coarse coverage plus precise
detail, and their disagreements are visible rather than averaged away. Neither
is bundled; you pass the paths.

---

## ADR-0016 — Keeping conflict and install-order data current: BWS-NG rules, krion64 evidence

**Status**: accepted
**Date**: 2026-09-09

### Context

Two community databases describe the same problem space and neither is a superset
of the other.

**BWS-NG** (`Selphira/BigWorldSetup-Next-Generation`, `data/rules/*.json`) is a
*curated rule set*: 851 pairwise statements in one grammar —
`order.json` (`direction: before|after`), `incompatibilities.json`,
`dependencies.json`. Its strength is that a rule is a decision somebody made and
can be argued with. Its weakness is that a rule carries no version qualifier, so
it cannot say "true before v5.1, fixed since", and nothing in the file records
when it was last looked at.

**krion64** (`krion64/krion64.github.io`, `data/mods/*.json`) is an *evidence
database*: 814 mod records, 1,020 conflicts, 135 dependencies, each conflict
carrying `severity`, `reason`, `source`, `evidenceLevel`
(`mechanism-verified` / `speculative`), the affected component numbers
(`myComps` / `theirComps`), and often a date. It also carries the install-order
skeleton the rules do not: 26 ordered categories in `data/categories.json` plus a
per-mod `c` (category) and `ord` (position within it).

Its README states how it is built: six sources merged — the `install-EET-4`
guide (~3,400 component entries), the EET Mod Install Order Guide sheet,
real `WeiDU.log` files, k4thos's EET compatibility list, Endarire's Infinity
Insanity guide, and `EE-Mod-Setup`'s 168 component conflict rules and 105
dependency rules lifted from the EET `Game.ini`. On top of that sit its
`scripts/`: `tp2_to_modjson.py` and `scan_subcomponents.py` derive components
from the tp2 itself, `scan_versions.py` tracks versions, and
`audit_tp2_drift.py` / `drift_scan_all.py` re-read each mod's extracted tp2 and
flag every component whose name has moved since the record was written.

That last mechanism is the important one, and it is the honest answer to "how
does anyone keep this current?". Nobody re-reads 1,020 conflicts by hand. What
you *can* automate is detecting that a rule's subject has changed underneath it.

### Decision

Use both, in the roles each is actually good at, and never merge them into one
undifferentiated blob.

1. **BWS-NG is the constraint source.** Its `direction`ed order rules are what
   the planner turns into edges. They are terse, unambiguous, and already in a
   grammar the solver can consume.
2. **krion64 is the ordering skeleton and the second opinion.** Its
   `categories.json` + `c`/`ord` supply the *global* reference order that BWS-NG
   has no equivalent for — pairwise rules can only say "A before B", never
   "engine mods before tweaks before tactical". Its conflicts load through the
   same `RuleSet` as a second rule source (ADR-0015), with `evidenceLevel:
   speculative` and soft dependencies demoted so they advise rather than block.
3. **Drift, not age, decides whether a rule is still true.** `--mod-db` already
   records the version each rule was written against; `tp2.py` already reads the
   version and component list out of the installed mod. A rule whose subject has
   moved on gets `stale_risk` and stops blocking. This is the same idea as
   krion's `audit_tp2_drift.py`, applied at check time to the mods the operator
   actually has rather than at build time to a maintainer's extraction tree.
4. **A developer's own metadata outranks both.** `.iemod` / `.ini` `Before` and
   `After` come from the person who fixed the incompatibility, so
   `add_metadata_order()` folds them into the same `RuleSet`. When a mod ships
   ordering metadata, third-party rules about it are the older claim.
5. **Suppressions are the escape hatch of last resort**, and they are a file the
   operator writes and dates, not a flag.

### Consequences

* No single upstream has to be right. A rule that only BWS-NG knows still
  constrains the plan; a conflict that only krion knows still warns.
* The refresh procedure is "git pull both repositories" — neither is vendored,
  both are passed by path. Rules are data, never code.
* What this does **not** give you: a guarantee that a rule is current. A conflict
  quietly fixed in a mod that changed neither its version nor its component names
  is undetectable by any of the above, and will keep warning until somebody
  updates the upstream or writes a suppression. Saying otherwise would be a lie
  about what automated drift detection can see.

---

## ADR-0017 — Rewriting the WeiDU logs as an install plan

**Status**: accepted
**Date**: 2026-09-09

### Context

Checking reports 19 order violations across an install of 796 components. A
report is not an answer to "so what order *should* I use?", and hand-sorting 146
mods against 851 rules is not work a person should do.

### Decision

`--plan-order DIR` re-sorts the components already in the logs and writes a fresh
`WeiDU.log` + `WeiDU-BGEE.log` pair, with these boundaries:

* **Rules are constraints, the catalogue is a preference.** Kahn's algorithm over
  the order-rule edges, ties broken by krion's `(category rank, ord)`. The result
  is the closest thing to the reference order that satisfies every rule — not the
  reference order with rules applied afterwards.
* **A dependency is not an ordering constraint.** BWS-NG records both
  `EET: EET_end` and `EET_end: EET`; read as ordering that is a cycle, and the
  first implementation duly pushed the EET core to the end of the install. Only
  `order` rules become edges. Dependencies are checked, never sorted on.
* **The tp2, not the folder, is a mod's identity.** `eet\EET.TP2` and
  `eet\EET_end\EET_end.tp2` share a folder and sit at opposite ends of the
  install. Keying by folder made every `EET_end` rule silently match nothing.
* **Nothing is invented, dropped, or reworded.** Output lines are input lines,
  reordered. A test asserts the multiset of 796 lines is identical.
* **An unknown mod keeps its place**, inheriting the priority of the last ranked
  mod before it, instead of being swept to the end.
* **The phase is not changed silently.** Moving a mod between the two logs
  changes which game it installs onto. It is reported; `--reassign-phase` acts.
* **An incompatibility is not resolved.** Reordering does not change which mods
  are present. Which one to lose is the operator's decision.
* **The output is checked against the rules it claims to satisfy**, and reports
  `NOT COMPLIANT` with the surviving findings when the rules contradict
  themselves, rather than shipping a file with a compliance claim on it.

### Consequences

* On the real install: 6 mods out of place, 0 cycles, plan verified against 132
  constraints; 4 incompatibilities and 1 missing prerequisite reported as things
  reordering cannot fix.
* **A rewritten log is an install plan for a FRESH install**, consumable by
  mod_installer or Project Infinity. WeiDU installs in file order, so an already
  installed game has to be reinstalled for the new order to mean anything.
  The tool says this in its own output; it is the single most important caveat.
* Ordering is at mod granularity, as Project Infinity's sorting order is. A rule
  that constrains one component of a mod against another component of the same
  mod cannot be expressed by reordering and is reported instead.

---

## ADR-0018 — Component-level conflict reporting

**Status**: accepted
**Date**: 2026-09-09

### Context

Ordering answers "in what sequence". It does not answer the question that
follows: *which component of which mod fights which component of which other mod
— or of itself — and what is the smallest thing I can change?*

The raw material is there. BWS-NG writes `cdtweaks(1251,1252):cdtweaks(1257)`.
krion64 records `myComps` / `theirComps` per conflict, grades each claim
`mechanism-verified` or `speculative`, names its `source`, and carries 58 per-mod
known issues (`ki`) that no pairwise rule can express — a 256-entry `SPLSTATE.IDS`
limit, an EEex build tied to an engine version, two `cdtweaks` components that
cost frame rate under EEex. None of that was reaching the operator: the checker
flattened `evidenceLevel` into a prose string, ignored `advisories` and `ki`
entirely, and reported findings as "mod A and mod B are incompatible".

### Decision

A separate `conflicts.py` builds a component-level report from the same
violations, with four rules of its own.

1. **Report the component intersection, not the rule.** A rule's component list
   is a claim about a version of the mod; what matters is which of those
   components you installed. On the real install, 84 (mod-pair, install) pairs
   carry a conflict rule and 79 are clear once intersected. A report that fired
   on all of them would be worse than none.
2. **Name the components, using the operator's own log.** WeiDU already writes
   `// Allow Thieving in Heavy Armor` next to `#2100`. That is a better source
   than any catalogue: it describes *their* install, not some version of the mod.
   Catalogue names are the fallback for components a rule names but nobody has.
3. **Keep provenance structured.** `evidence`, `source`, `workaround` and the
   upstream's own severity word are fields on `Rule`, not text folded into a
   message. A `speculative` finding renders as `SPECULATIVE: not verified, judge
   it yourself`. krion's `advisories` channel loads at `note` severity and is
   withheld unless `--show-advisories` is passed: reading it at conflict weight
   would bury the verified findings, and not reading it discards thousands of
   real component-level observations.
4. **Give the narrowest remedy.** "infinity_ui and stratagems are incompatible"
   is not actionable; "deselect stratagems #4115 (alternative: drop infinity_ui)"
   is. Where a rule pins one side to components and condemns the other
   wholesale, the pinned side is always the cheaper fix. Where it pins neither,
   the report says the rules do not narrow it — rather than inventing a
   preference.

Findings the ordering plan already resolves are marked `FIXED by --plan-order`
instead of being listed as outstanding work; on the real install that turns all
46 order findings from complaints into confirmations.

The report also prints how much was examined — rules evaluated, pairs where both
mods are installed, pairs cleared by the component intersection, order-sensitive
pairs upstream never gave a direction for (439 of them). Without those numbers
"no conflicts found" is unfalsifiable: it reads identically whether the install
is clean or the rule set matched nothing.

### Consequences

* On the real 796-component install: 4 incompatibilities, 1 missing prerequisite,
  13 known issues, 46 order findings all fixed by the plan. Every one names the
  exact components and, where upstream recorded it, the forum thread it came from.
* `--conflict-report PATH` writes the whole thing as JSON, including the findings
  the terminal truncates.
* **What it still cannot do**: `translations.en_US` is preferred over
  `description`, but many BWS-NG rules carry only a French `description`. Those
  reasons print in French. Translating them would be inventing content; the
  alternative is showing nothing. Upstream is the place to fix it.
* A rule whose severity upstream never graded defaults to `warning`, never to
  `error`. Blocking an install on an ungraded claim is not a decision this tool
  gets to make.

---

## ADR-0019 — Testing beyond TDD: properties, mutation, and static analysis

**Status**: accepted
**Date**: 2026-09-10

### Context

561 example-based tests, written test-first, and every defect that actually hurt
this project was a case nobody thought to write: a `? 1 : 0` anywhere in a tp2
suppressing every `GAME_IS` match; twenty mods resolving to the same URL because
a nav link scored just high enough; `EET_END.json` sorting before `eet.json` in
ASCII and claiming the EET core's ordering slot.

TDD gives a test for every case you imagined. It cannot give you the one you did
not, and "write more tests" does not change the shape of that limitation.

### Decision

Four techniques added, each aimed at a class of defect examples cannot reach.
`docs/TESTING.md` is the full account; the decisions are:

1. **Property-based testing (Hypothesis) where a law exists.** Not everywhere —
   most functions have no law worth stating. But the safety predicates are
   total, `normalize_key` is idempotent, version comparison is a strict weak
   ordering, and every parser is total over arbitrary text. Those are laws, and
   Hypothesis searches for counterexamples and shrinks them.

   It skips rather than fails when Hypothesis is absent, because ADR-0002
   promises `python3 -m pytest` works with nothing installed.

2. **Architecture contracts (import-linter) as a CI gate.** A layering diagram
   in a document drifts from the code within two refactors. Four contracts
   instead: the core imports nothing from the shell, the runtime imports no
   third-party package, nothing imports the CLI, and the stack holds.

3. **Static analysis as a gate, not a suggestion.** `mypy` (a subset that
   catches bugs rather than missing annotations), `ruff` with an explicitly
   chosen rule set, `bandit` with every skip carrying its reason in-file, and
   `-W error` in pytest so a stdlib `DeprecationWarning` is the earliest
   possible notice that a future Python breaks this.

4. **Mutation testing, nightly, reporting and never gating.** Coverage says a
   line ran; mutation testing says the tests would have noticed if it were
   wrong, which is what coverage is routinely mistaken for. It reports because a
   surviving mutant is a question, not a defect, and sometimes "it does not
   matter" is the right answer.

### Consequences

Turning them on found four defects the same day:

| Found by | Defect |
|---|---|
| Hypothesis, first run | `compare("master","main")` and `compare("main","master")` both returned 1 — `is_newer` true in both directions, so a default-branch rename could mark a rule stale |
| bandit (B202, high) | `extractall` was handed a member list after validation: the names validated and the paths the library resolves were two separate facts |
| bandit (B101) | a manifest invariant was an `assert`, which `python -O` strips |
| import-linter | `catalogues → resolvers` via a function-local import to dodge a cycle — a pure function trapped in an impure module, now `urls.py` |

Plus 16 typing defects, one of which was a live `NameError` in the extraction
path, and two tests leaking file handles.

**The cost, stated honestly:** four more tools in the developer toolchain, a
slower nightly, and a set of ignore-lists that must carry their reasons or they
rot. The properties took longer to write than the equivalent examples would
have. The first one paid for all of it.

**What is still not covered:** the live GitHub API has never been exercised from
CI. Everything about it is tested against a hand-written double encoding what I
believe the API does. That is the largest untested surface and it is item A on
the roadmap.

---

## ADR-0020 — Functional core, imperative shell — and no pattern apparatus

**Status**: accepted
**Date**: 2026-09-10

### Context

Making the project repository-ready invited the question of whether it should
adopt a recognised architecture — clean architecture, hexagonal, a service
layer, dependency injection, repository interfaces.

### Decision

No. The structure is **functional core / imperative shell**, plus "parse, don't
validate" at the boundaries, typed errors, and dataclasses as values. That is
the entire paradigm budget, and each item is there because a specific failure
argued for it.

The argument against the alternatives is not that they are bad ideas; it is that
this codebase does not have the problems they solve. There is no database to
abstract, one delivery mechanism, and no plausible second implementation of
anything. A `ManifestRepository` with exactly one implementation, an abstract
resolver factory, or a service layer wrapping a pure function would each add a
file, an indirection and a test double, and would prevent no defect that has
ever occurred here. Indirection you cannot point at a failure for is cost
without benefit.

What HAS caused defects is a decision that cannot be tested without a mock, and
a pure function trapped inside an impure module. The core/shell split addresses
both, and `import-linter` makes it a gate rather than an intention.

### Consequences

- Every parser, comparator, rule check, order solve and report render is a
  function of its inputs, testable with no network, no temporary directory and
  no clock. 582 tests run offline in about thirteen seconds.
- Dependency injection happens by passing an argument. `Runner` takes a client;
  `OrderIndex.load` takes a path. There is no container, and the "interfaces"
  are two `Protocol`s introduced only where the checker needed one.
- The contract is falsifiable: `lint-imports` says which import broke it.
- **The honest cost:** the shell is thin but not tested as thoroughly as the
  core, because testing it well needs a network. That is the trade — the
  interesting logic is where the tests are strongest, and the untested part is
  the part with the least logic in it.

---

## ADR-0021 — Conflict resolution: only what the rules decide, only in the plan

**Status**: accepted (amends ADR-0017's "an incompatibility is not resolved")
**Date**: 2026-10-20

### Context

ADR-0018 made every finding name its narrowest remedy — "deselect stratagems
#4115 (alternative: drop infinity_ui)". Operators then did by hand, for every
finding, exactly what the report told them. Where the rule itself decides which
side goes, that manual step adds nothing but typos. Where it does not, an
automatic choice would be a guess with a delete key.

The Infinity Orchestrator draws the same line: kinds such as `included`,
`mismatch` and `not_compatible` disable a component automatically; `conflict` is
only flagged. BWS-NG's own UI does the same.

### Decision

`--resolve-conflicts` (opt-in, requires `--plan-order`) removes components from
the **plan** — never from the operator's logs — for a finding that is:

1. an incompatibility,
2. graded `error` by its rule set,
3. not graded `speculative`,
4. between two different mods,
5. pinned to components on at least one side.

The side removed is the one the report already names as cheaper (a pinned side
is always cheaper than a wholesale one; between two pinned sides, the fewer
components). Exactly the components the rule named and the plan contains are
removed; a mod left with none leaves the plan.

Everything else — whole mod vs whole mod, same-mod option groups, missing
dependencies, warnings, speculative claims — is listed under "left for you to
decide" with the reason, and the plan is re-verified afterwards. The decision
record is written beside the plan as `RESOLUTION.json`.

### Consequences

- The input check still reports the conflict and still exits non-zero: the
  operator's install has not changed. The plan has.
- A mod key that names two tp2s in one folder (`eet`: EET and EET_end) is
  refused rather than resolved, because which one the rule meant is ambiguous.
- Tested both ways: each class of refusal has a test that it removes nothing.

---

## ADR-0022 — Installing the plan: generate scripts for mod_installer, never run them

**Status**: accepted
**Date**: 2026-10-20

### Context

The tool stopped at a planned `WeiDU.log` pair. Turning that into an installed
EET game means running WeiDU against two game directories in order, batching
consecutive components, answering prompts, and handing EET's core the BGEE
path — then doing the same on Windows and Linux.

That is solved. dark0dave's
[mod_installer](https://github.com/dark0dave/mod_installer) (GPL-3.0) takes
exactly such a log pair: `mod_installer eet -1 <BGEE> -y <bgee log> -2 <BG2EE>
-z <eet log>`. Born2BSalty's Infinity Orchestrator builds no WeiDU command line
of its own; it writes the logs and runs mod_installer. Reading mod_installer's
source showed one hard requirement: it recognises the EET core by the log
comment `EET core (resource importation)`, and only then passes the BGEE path.

### Decision

`--emit-installer` writes `install-eet.sh` + `install-eet.cmd` (or `install.sh`
+ `install.cmd` for a single game) next to the plan. Each script:

- refuses a directory without `chitin.key`, and a game that already has mods
  (`ALLOW_EXISTING=1` overrides) — a plan is for a fresh install (ADR-0017);
- resolves mod_installer and WeiDU, or says which one is missing;
- makes one mod_installer call, with `DRY_RUN=1` to print it instead.

At generation time the plan is checked for what would otherwise fail forty
minutes in: the EET core's comment, EET_end last, and every mod folder present
in the staging directory.

**iemod-fetch never executes the scripts, WeiDU or mod_installer.** ADR-0006
("nothing downloaded is executed") stays literally true; the operator reads and
runs a 40-line script. mod_installer is invoked, never vendored, so its GPL
does not reach this MIT repository.

### Consequences

- The full path is: fetch → `--plan-order --resolve-conflicts --emit-installer`
  → run one script → play. Same artefacts on Windows and Linux.
- The shell script is executed in the test suite against a stand-in
  mod_installer; the `.cmd` script is executed on the Windows CI runners.
- Verified against the real thing: the generated `install-eet.sh` was run with
  the mod_installer 16.0.0 binary built from source and a stand-in WeiDU that
  records its calls. mod_installer installed the BGEE log in the BGEE folder,
  then the EET core, the EET mods and EET_end in BG2EE — and passed WeiDU
  lower-cased paths (`eet/eet.tp2`). That last fact is why the Linux script
  refuses mixed-case mods before anything runs, unless `--casefold` is passed.
- **What is not verified here:** a real WeiDU install against real game data.
  That needs the games, which no CI runner has.
- mod_installer marks its EET mode BETA. That is its maturity, inherited
  honestly, and the guide says so.

**Amendment (2026-10-21) — ties, same-mod conflicts, WeiDU subcomponents.**
A tie (both sides pin the same number of components) is no longer resolved by
taking the left side: that was a guess, and it is now left to the operator. A
same-mod conflict with an unequal split is resolved like a cross-mod one (the
group with fewer components goes). Two options of one WeiDU SUBCOMPONENT group
(`// Group -> Option` in the log) are detected without any rule set and resolved
by keeping the last one — what WeiDU itself ends with, since installing the
second uninstalls the first. On the real install: 3 resolved, 1 tie left.

---

## ADR-0023 — Component-level install order

**Status**: accepted (closes ROADMAP 2026-09 item C)
**Date**: 2026-10-21

### Context

A mod is not one thing. krion64 files stratagems #1500 under SPELL MODS and
#4100 under POST EET (`co[].cat`); BWS-NG's curated EET order splits stratagems
into four separate runs; rules name components
(`stratagems(5900):cdtweaks`). The planner sorted whole mods, so none of that
could be honoured. And the checker judged "A before B" on the *first* component
of each — and numbered components by the parser's per-mod grouping rather than
by log line, so a mod's components always looked adjacent.

### Decision

- **The checker** judges every named component: "A before B" means the last of
  A's named components precedes the first of B's, by real log line.
- **The planner** splits a mod into contiguous parts where the catalogue
  (`co[].cat`) or a component-naming order rule distinguishes its components.
  A mod nothing distinguishes stays one unit, exactly as before. Parts share the
  mod's catalogue position and are tie-broken by log line, so they keep their
  original order unless a rule says otherwise. A rule between two components of
  the same mod is honoured when they fall in different parts.
- Like krion64's own export, a moved component takes its new category and the
  MOD's `ord`; the component `ord` field, which krion64 does not read, is not
  read here either.

### Consequences

- On the real install the old checker's 46 order findings included **34 false
  positives** ("X should be installed before EET_end", with EET_end logged
  last); the fixed checker reports 14, two of them new and real. The plan
  splits 6 mods and verifies against 158 constraints.
- The plan still contains exactly the input lines (tested).
- mod_installer installs whatever order the log gives, batching consecutive
  components of one mod, so a split plan needs nothing new downstream.

---

## ADR-0024 — Preferred installation language, with fallback

**Status**: accepted
**Date**: 2026-10-21

### Context

A log line's `#lang` is an index into that mod's own LANGUAGE declarations:
1 is Italian in one mod and French in the next. mod_installer passes it
through unchanged. The community tools differ: krion64 uses one language then
English; BIO one locale then English, probing `--list-languages`; BWS-NG keeps
an ordered preference list, takes the first a mod offers, and reads the tp2's
LANGUAGE declarations through an alias table.

### Decision

BWS-NG's model. `--language-preference it_IT,en_US` (names work too) rewrites
each planned line's `#lang` to the first preferred language the staged mod's tp2
declares, matched on the declaration's language directory and then the first
word of its display name, through an alias table — without BWS-NG's
"dutch → German" slip. The index is the declaration's position, duplicates
included. The game language passed to mod_installer defaults to the first
preference.

### Consequences

- A mod offering none of the preferences keeps its logged index and is listed
  with what it does offer; a mod not staged yet is listed too. Nothing guessed.
- It needs the mods fetched first (it reads their tp2), so it belongs to the
  planning step after the fetch, as the guide's chapter 10 orders it.

---

## ADR-0025 — The mods' own tp2 constraints, and an install simulation

**Status**: accepted
**Date**: 2026-10-21

### Context

A plan that passes every community rule can still stop mod_installer halfway:
WeiDU itself refuses a component whose own tp2 says no. A mock EET install
built from verbatim upstream tp2 excerpts (`tests/data/eetmock`) shows the
traps: DlcMerger aborts on anything but BGEE; EEFixPack declares
`!GAME_IS ~eet~`; a Tweaks component installed on BGEE makes EET refuse the
merge (`tbl/compatibility.tbl` is an allow-list of 27 BG:EE mods, and EET.tp2
also fails on two wrong options); Tweaks #4010 is BG2EE-only and stops holding
the moment the EET core turns BG2EE into EET; Ascension FORBIDs SCS #5900.

The community handles this metadata in two ways. BWS-NG copies it by hand into
`order.json` / `incompatibilities.json` (SCS's `FORBID_COMPONENT` against
Tweaks #2370 becomes `stratagems(4100):cdtweaks(2370,2372,4020)`), which lags
behind the mod version actually downloaded. The Infinity Orchestrator parses
`REQUIRE_COMPONENT`/`FORBID_COMPONENT` from the tp2 and puts a required
component first. Neither simulates the install.

### Decision

1. **Read the staged tp2s** (`constraints.py`): per component, REQUIRE_COMPONENT,
   FORBID_COMPONENT and the simple REQUIRE_PREDICATE forms (GAME_IS, ENGINE_IS,
   GAME_INCLUDES, MOD_IS_INSTALLED, negated), plus a body-level
   `ACTION_IF NOT GAME_IS … ABORT`. Compound predicates are counted as unread,
   never guessed.
2. **Turn them into rules**, origin `mod tp2`:
   * REQUIRE → the required component first (the Orchestrator's reading), plus
     a dependency; both error.
   * one-sided FORBID → the declaring component first (WeiDU checks a FORBID
     only against what is already installed), error; plus a *warning*
     incompatibility, because the tp2 does not say whether the two coexist
     (EET's means "install me first", SCS's against Tweaks means "never
     together" per BWS-NG). A warning is never auto-resolved; a community rule
     graded error decides.
   * mutual FORBID → an incompatibility, error: no order installs both.
3. **Read EET's merge check from the staged EET** (`compatibility.tbl` and the
   `COUNT_REGEXP_INSTANCES … PATCH_FAIL` blocks).
4. **Simulate** (`simulate.py`, `--simulate`): walk the plan in order; the BGEE
   log on BGEE (+SoD), the EET log on BG2EE that becomes EET after `eet #0`.
   BGEE-phase mods do not count for MOD_IS_INSTALLED on EET: EET.tp2 copies the
   BG:EE log to `WeiDU-BGEE.log`, not into `WeiDU.log`.
5. **`--resolve-conflicts` drops what WeiDU would refuse**, with WeiDU's reason,
   re-simulating until nothing is refused (8 rounds at most). For a refused EET
   merge it drops the BG:EE mods outside the table, or the wrong option. The EET
   core is never dropped: any other refusal of it is left for the operator.

### Consequences

- The mock EET install goes from "EET refuses the merge" to "0 would be
  refused", each removal explained; the generated installer is then run
  against a stand-in mod_installer.
- Only what WeiDU's flags express is checked. A mod that fails inside its own
  body for a reason no flag states is not caught; compound predicates are
  counted, not evaluated. Mods not staged are reported as unchecked.
- EET's M flag (merge anyway) is not modelled as an option: the plan never
  depends on overriding the author's check.

---

## ADR-0026 — Verified game folders, reorder before removing, and the real WeiDU as the test oracle

**Status**: accepted
**Date**: 2026-10-21

### Context

ADR-0025's simulator was checked only against itself. Four questions remained:
are the game folders the plan installs onto really BG:EE and a clean BG2:EE;
when WeiDU would refuse a component, is removing it the right fix or is there
an order that keeps it; can the result be tested against the real WeiDU without
copyrighted game data; and which tool and mod versions does the plan assume.

Primary sources: WeiDU's `src/tppe.ml` (PE_GameIs) identifies a game by marker
resources — `oh1000.are` BG:EE, `oh6000.are` BG2:EE, `eet.flag` EET — looked up
in override/ and chitin.key. EET's readme: the core needs "a clean BG2:EE
installation with latest patch (currently v2.6.6.0) and (optionally) the
Enhanced Edition Fixpack", and BG:EE with SoD (checked through
`movies/sodcin05.wbm`); GOG/Steam ship SoD as a DLC archive DlcMerger must merge
first. EET.tp2:2797 writes `override/EET.flag`. BWS-NG's `games/eet.json`
orders `eefixpack:0-2` before `eet:0` in its bg2ee sequence, and lists the mods
allowed on the BG:EE side.

### Decision

1. **Game folders** (`gamedir.py`, `--bgee-dir` / `--bg2ee-dir`): identify each
   folder with WeiDU's own rule, reading chitin.key; refuse a swapped pair, the
   same folder twice, an already-EET game, a modded BG2:EE, and a BG:EE without
   SoD; require DlcMerger in the plan when SoD is still a `sod-dlc` archive.
   Read only, never written. The patch level and the integrity of the game data
   are reported as not checked.
2. **Reorder before removing.** A refusal that a documented order fixes is fixed
   by that order: EEFixPack refused on EET moves before the EET core, where the
   game is still BG2:EE. The list of what may precede the core is EET's own
   (EEFixPack), confirmed by BWS-NG; nothing is moved on inference. Everything
   else WeiDU would refuse is still removed with its reason.
3. **The real WeiDU is the oracle** (`tests/test_real_weidu.py`): two synthetic
   game folders — an empty chitin.key, an empty dialog.tlk, the marker file —
   are enough for WeiDU to evaluate GAME_IS, REQUIRE and FORBID. The mock mods
   run from their verbatim excerpts (complete one-line flags only). Asserted:
   real WeiDU refuses exactly what the simulator says on the raw logs; it
   installs the resolved plan to the last component; and the generated
   `install-eet.sh` runs through the real mod_installer into both games, the EET
   core writing `EET.flag` between them. A CI job runs it on every push.
4. **Pinned toolchain.** WeiDU v251.00 (official Linux release, sha256
   recorded); mod_installer at commit `3b6827a` (Cargo 16.0.0 — its tags stop
   at v12.1.1, so a commit, not a tag, is the pin). Mods: a release tag plus
   sha256 through `--emit-pinned-manifest`; a mod without releases is pinned by
   the archive's sha256. "Latest" or a branch head is never a pin. The games:
   v2.6.6.0, as EET requires; not verifiable from the folder, so stated.

### Considered and not adopted

- **GemRB** (an open-source reimplementation of the Infinity Engine). Its
  KEY/BIFF readers and its free demo data are the community's answer to "tests
  without game data". But WeiDU, not the engine, decides what installs; booting
  the result in GemRB would test GemRB's engine, not the install, and needs the
  same game data. The synthetic-folder approach tests the real installer instead.
- **BWS-NG's per-game order lists** as the source of truth: hand-maintained,
  they lag behind the downloaded mods. Read as rules (ADR-0017), cross-checked
  against each mod's own tp2 (ADR-0025).

### Consequences

- Two fixture bugs and one parser bug were found by real WeiDU on the first run:
  a `BEGIN` inside an inlined file (`<<<<<<<< … >>>>>>>>`) counted as a
  component, which hid EET_end's requirement on the EET core; and EET_end
  staged where WeiDU 251 does not look for it.
- Still not covered: real game data (patch level, the merge itself, mods whose
  bodies fail on content). That needs a self-hosted runner with owned copies
  (ROADMAP F5).

---

## ADR-0027 — Releases are tagged and published by the merge, not by a person

**Status**: accepted
**Date**: 2026-10-21

### Context

The release process (RELEASING.md) ended with "tag and push", a step done by
hand on a machine with push rights. It was never done for 2.1.0 or 2.2.0, so the
releases existed only in the changelog. The workflow behind it had never run:
it called `ci.yml`, which was not reusable.

Two approaches in the maintainer's own repositories: R-studioConf (ADR-0006)
tags and releases from the newest CHANGELOG.md section on every push to main;
Proxmox_biome_log_collector releases on a pushed tag, plus a manual trigger for
tags made before the workflow existed. Elsewhere, release-please and
semantic-release derive the version from commit messages. This project already
writes its changelog by hand and reviews it in the pull request.

### Decision

R-studioConf's model, plus Proxmox_biome_log_collector's manual trigger:

- the newest `## [X.Y.Z]` section of CHANGELOG.md is the release; an existing
  tag means it is done;
- the commit released is the first main-line commit where `__version__` says
  X.Y.Z, which is the merge of the release pull request (`tools/release_plan.py`,
  tested on a scratch repository);
- the release workflow creates the tag together with the release. A tag pushed
  with GITHUB_TOKEN would start no workflow, so it cannot be a separate step;
- releases are published, not left as drafts: the notes were reviewed in the
  pull request. PyPI stays opt-in (`PYPI_PUBLISH`) and keeps its environment
  gate.

release-please and semantic-release are not adopted. They would replace a
hand-written, reviewed changelog with one generated from commit messages.

### Consequences

- Merging a version bump is the release; there is no step left to forget.
- A changelog section whose `__version__` never reached main makes the workflow
  fail and say so, instead of tagging the wrong commit.
- The CI gate a release re-runs is main's current code. A back-filled older
  version, such as 2.1.0, relies on the CI its own pull request passed.
- GITHUB_TOKEN cannot create a tag on a commit whose workflow files differ from
  main's; it can never hold the `workflows` permission. Seen on the first runs:
  403 at the release step for both 2.2.0 and 2.1.0. So when nothing shipped
  (`iemod_fetch/`, `pyproject.toml`, `build.py`, README, LICENSE) changed since
  the version commit, main's head is tagged, which gives the same artifacts. A
  true back-fill stops at planning with the two ways out: a tag pushed by hand
  and then released by a manual run naming that version (a tag push alone runs
  the tagged commit's own, older workflow), or an optional `RELEASE_TOKEN`
  secret.
- No step needs a person except creating that secret. Corrected notes reach
  their release on the next push to main; editing a release creates no ref.
  Listed back-fills are released by the automatic run once the secret exists.
  The session that maintains this repository can merge but cannot start a
  workflow or push a tag, so everything after a merge has to happen inside the
  workflow.
- For the same reason a change to the pipeline is rehearsed on its own pull
  request (gate, build, attestation; never notes, tag or publish): a manual dry
  run is not available to that session, and an action bump used only at
  release time would otherwise first run on a real release.

---

## ADR-0028 — Dependencies: Dependabot for what it sees, an issue for what it cannot

**Status**: accepted
**Date**: 2026-10-21

### Context

Dependabot was configured for the developer tools (pip) and the pinned actions,
but had never opened a pull request. On a fork its version updates stay off
until they are switched on in the repository's settings. The CI logs warn that
the pinned actions still run on Node 20. The test toolchain added in ADR-0026
(a WeiDU release zip with a sha256, a mod_installer commit) is invisible to
Dependabot in any case. The tool itself ships with no dependencies (ADR-0002).

### Decision

- Dependabot keeps the pip and github-actions ecosystems. Action updates are
  grouped into one weekly pull request, the same way the developer tools are.
  It is switched on in the repository settings; that is a setting, not code.
- `upstream-versions.yml` (`tools/upstream_versions.py`) compares the pinned
  WeiDU and mod_installer with upstream every week. For WeiDU that is the newest
  release tag, excluding nightlies and release candidates. For mod_installer it
  is the Cargo.toml version, because its tags stop at v12.1.1. One issue opens
  per tool behind, and the run stays red until the pin moves. This is the
  method of Proxmox_biome_log_collector.
- No automatic pull request for those two, and no auto-merge. A new digest is
  only as trustworthy as whoever verified it. Auto-merge without required
  status checks on main would merge before CI finished.
- The supported Python versions are a product decision, not a dependency:
  Dependabot does not move them. CI keeps testing the floor and the newest
  release. Raising the floor from 3.9 is roadmap item E6, a major version.

### Consequences

- Updates arrive as reviewable pull requests or issues. None of them is a
  release on its own: a release still needs a changelog section (ADR-0027).
- A person switches Dependabot on once, and verifies each new WeiDU digest.

---

## ADR-0029 — A UI on top of the CLI: a phased wizard that ends by installing

**Status**: accepted
**Date**: 2026-10-21

### Context

ROADMAP 2.3 ruled out a GUI ("Project Infinity is the GUI") and running WeiDU
(ADR-0003). The owner now wants a complete tool in the style of
BigWorldSetup-NG, Infinity Mod Forge/Runner and BIO: pick mods and components,
see updates, get the order and conflicts resolved, then install. The audit in
[GUI-AUDIT.md](GUI-AUDIT.md) found the core strong (verified downloads, a
computed order, automatic resolution) and the CLI not yet usable as a backend.

### Decision

- A UI is in scope. It is a client of a public API (`iemod_fetch.api`) and has
  no logic of its own. The CLI is the other client, and everything the UI can
  do the CLI can do too.
- The UI is a wizard in phases, the order BWS-NG uses: **game and folders →
  backup → mod selection → install order → download → extraction →
  installation**. Each phase can be left and resumed, and each one writes a
  file the CLI also accepts (`selection.json`, the order, the staged folder).
- **Installing is in scope, as the last phase.** It replaces ADR-0003's "never
  runs WeiDU". It comes last in delivery (M4), after selection, order,
  conflicts and download are complete and tested, and it starts only on an
  explicit action, after a backup of the game folder has been offered.
- The CLI is made complete first (M1 and M2), and the UI starts only when
  their acceptance tests pass.
- No code or bundled data from GPL projects (BIO, BWS-NG, mod_installer).
  Their formats are read and written for interoperability.

### Consequences

- ADR-0003 is superseded on one point: the tool may run WeiDU or
  mod_installer, in the install phase only.
- `cli.py` loses its private orchestration to `api`. That refactor touches
  every entry point and needs the full test suite green throughout.
- Installing brings new failure modes (a half-installed game, WeiDU prompts,
  Windows paths). M4 has its own acceptance tests and real-WeiDU CI.

---

## ADR-0030 — A versioned JSON contract: selection in, reports and events out

**Status**: accepted
**Date**: 2026-10-21

### Context

The only selection format is WeiDU.log, the JSON reports carry no schema
version, and progress is printed text. A UI, or any other front end, needs a
contract it can depend on.

### Decision

- `selection.json` (`schema_version: 1`): game, mods, components, language and
  subcomponent choices. It turns into the same internal objects as a WeiDU.log.
- Every JSON output gets `schema_version`, and every finding a stable id.
  JSON Schema files are published in the repository, and tests validate the
  outputs against them.
- `--events jsonl` streams progress events (one JSON object per line). It is
  the same stream the API delivers to an `on_event` callback.
- Error records carry a stable `code`.
- A breaking change to any schema is a major version (the CLI's public surface
  already includes the JSON report, as CHANGELOG says).

### Consequences

- Front ends in any language can drive the tool through the CLI alone.
- Schemas become something to maintain and to version with care.

---

## ADR-0031 — The UI is a PySide6 desktop app, packaged apart from the CLI

**Status**: accepted
**Date**: 2026-10-21

### Context

ADR-0002 keeps the shipped tool to the standard library in one `.pyz`. The
options compared in the audit were Tkinter, PySide6/Qt, a local web page,
Textual, and a separate Tauri/egui front end. The owner chose the BWS-NG model:
a desktop wizard in PySide6, the UI the community already knows.

### Decision

- The GUI is a separate package, `iemod_fetch_gui`, in this repository. It
  depends on PySide6 (LGPL-3.0, used unmodified and dynamically linked, which
  an MIT application may do) and imports only `iemod_fetch.api`.
- The CLI is unchanged: still standard library only, still one `.pyz`.
  ADR-0002 holds for the CLI. `iemod_fetch` may never import the GUI, and
  import-linter enforces it.
- The GUI ships as its own download per OS, built with PyInstaller in the
  release workflow, attested like the `.pyz`, together with Qt's LGPL notice.
  `pip install iemod-fetch[gui]` also works.
- Screens follow BWS-NG's patterns as ideas, not code: a category column; a
  mod → component → choice tree with tri-state checkboxes, radio buttons for
  exclusive groups and drop-downs for prompts; search and "selected only /
  conflicts only / updates" filters; a details pane; a conflicts panel with
  one-click options; EET order as one tab per phase with drag to reorder.
- Long work (download, extraction, install) runs in a worker thread and reaches
  the UI through the ADR-0030 event stream, so the window never blocks and
  every phase can be cancelled.

### Consequences

- The GUI download is large (roughly 100-200 MB per OS). The `.pyz` stays small
  for those who want only the CLI.
- CI grows: GUI tests under pytest-qt with `QT_QPA_PLATFORM=offscreen`, and a
  PyInstaller build per OS at release time.
- Dependabot watches PySide6 and PyInstaller like the other dev tools; a Qt
  security update means a GUI release.

---

## ADR-0032 — The community data is refreshed automatically when a run starts

**Status**: accepted
**Date**: 2026-10-21
**Amends**: ADR-0009 (catalogues were read from a path and "never fetched
automatically")

### Context

Install order and conflicts are decided from three community databases:
lcc-docs (the mod list, status, rating), BigWorldSetup-NG (rules, per-mod
records) and krion64 (order categories, per-mod conflicts, release scan). Until
now each was a `git clone` the user had to make, pass by path and remember to
`git pull`. A clone nobody pulls goes stale silently, and every order and
conflict decision goes stale with it. The owner asked for this problem to be
solved for good: the data refreshed by itself when the program starts.

Measured: the files the tool reads are about 25 MB in total (lcc-docs
`db/mods.json` 2.4 MB; BWS-NG `data/` 3.4 MB; krion64 `data/` 14 MB, in a
487 MB repository that is mostly images).

### Decision

- A per-user cache (`$IEMOD_DATA_DIR`, else `%LOCALAPPDATA%\iemod-fetch\data`,
  `~/Library/Caches/iemod-fetch/data` or `~/.cache/iemod-fetch/data`) holds the
  three sources, each pinned to the commit it came from (`sources.json`).
- Every run refreshes it first, at most once per `--data-max-age` hours
  (default 24): one API call for the current commit; if it moved, one for its
  file list; then only the `.json` files under the paths the tool reads, and
  only those whose git blob hash changed, from raw.githubusercontent.com at
  that commit. Each file is checked against the hash GitHub listed before it is
  kept; the new copy is assembled beside the old one and swapped in whole.
- Offline, rate-limited or refused, a source keeps its last good copy and the
  run says how old it is. A refresh never stops a run.
- The cache stands in for `--catalogue`, `--rules`, `--mod-db` and
  `--order-catalogue` whenever those are not given. An explicit flag always
  wins. `--no-default-data` turns the stand-in off, `--no-update-data` (or
  `IEMOD_NO_UPDATE_DATA=1`) the network, and `--update-data` refreshes now and
  stops.
- Cached files carry the upstream commit date as their modification time, so
  the rule-staleness warnings judge upstream's age, not the download's.
- Still never bundled. The data keeps its licence (lcc-docs and krion64 MIT,
  BWS-NG GPL-3.0); the user's own run fetches it and the tool reads it as data.

### Consequences

- `--plan-order` no longer needs `--order-catalogue`, and a check uses the
  community rules without any setup. A run that passed with no rules given may
  now report findings: that is the point, and `--no-default-data` restores the
  old behaviour.
- A run makes up to six GitHub API calls a day; anonymous use allows 60 an hour.
  The first refresh downloads about 1,200 small files; later ones download what
  changed.
- The refresh trusts GitHub for the listing: the hash proves the file is the
  one GitHub listed at that commit, not who wrote it. The files are data read
  by size-limited parsers, never executed; paths that would leave the cache
  are refused.
- `.github/workflows/community-data.yml` runs the real refresh against GitHub
  on every pull request that changes it and every night.
- Every update is guarded before it is swapped in: valid JSON, readable by the
  tool's own parsers, and no count (mods, rules, order entries) at zero or
  below half of the last good copy's. A refused commit is remembered and not
  fetched again until upstream moves. An accepted update records what changed
  (counts, mods added and removed, versions and statuses), so an update that
  changes the advice the tool gives is never silent.

---

## ADR-0033 — Conflicts are answered with options; the player's answer wins

**Status**: accepted
**Date**: 2026-10-21

### Context

`--resolve-conflicts` applies the rules' own remedy only where they decide
(ADR-0021). Everything else - a tie, a warning, a whole mod against a whole
mod - is "left for you to decide", and until now deciding meant editing the
plan's WeiDU.log by hand and re-running without the flag. A GUI cannot do
that, and neither can a player who wants the same choice next time.

### Decision

- Every finding carries **options**: deselect one side (its cost is the
  number of chosen components lost), reorder (what the plan already does), or
  install a missing prerequisite (not applicable to a plan: it needs a fetch).
  Each has a stable id derived from the finding's id. `recommended` marks what
  `--resolve-conflicts` would do, and only where the rules decide.
- A **decisions.json** (schema v1) records the player's answers: `choose` an
  option, or `accept` a finding with a reason.
- `--decisions` applies them to the plan **before** `--resolve-conflicts`, which
  skips every decided finding. The plan is re-checked afterwards; the report
  marks a chosen finding fixed by the plan and an accepted one suppressed,
  with the reason.
- A decision whose finding is no longer in the report is **stale**: reported,
  never re-targeted. An option id that belongs to another finding is an error.

### Consequences

- The "left for you to decide" list becomes a set of buttons for the GUI and a
  file the CLI can replay; the WeiDU logs are still never edited.
- Ids are stable for the same selection. Changing the selection can make a
  decision stale; that is reported, and the player decides again.
- A player can accept a conflict the rules grade `error`. The report keeps it
  visible as accepted, with the reason they gave, rather than hiding it.

**Amended 2026-10-22 (M3 phase 2, the wizard's conflicts panel).**
`api.selection_conflicts` judges a selection before anything is downloaded,
with the rules, the staged tp2s and the planned order a run uses, and returns
the run's findings with their ids; the panel turns each option into a button
(deselect a side, choose a missing prerequisite the list knows, or write an
install-order choice or an acceptance to `decisions.json`). Building it found
that the run's own `--conflict-report` named each install by its log's file
name while `--decisions` names it by the plan's role, so any log not already
named `WeiDU.log` (EET) or `WeiDU-BGEE.log` - every `--selection` run - got
report ids no decision could match. The report now uses the plan's names when
there is a plan, and shows each log's own file name. Ids of a plain
`-w WeiDU.log:EET` run are unchanged. The panel always names installs by role,
so a decision saved before the order data arrives still matches a planned
run. A reorder is not offered as a decision on a finding the plan could not
settle: `--decisions` applies a reorder only by sorting, which already failed
for it, so recording it would mark the finding settled and change nothing.

---

## ADR-0034 — Engine limits are checked against primary sources, and warned on, never blocked

**Status**: accepted
**Date**: 2026-10-21

### Context

Big EE installs run out of three engine tables: kits, spell states and spell
ids per level. Infinity Mod Forge warns on them with constants (320 kits, 37
taken; 256 spell states, 128 taken; 50 spells per level) and per-component
counts from krion64's records. The owner asked to verify those values in the
original projects and forums, and not to tie anything to one game patch
(players are on 2.6.x and 2.7.x).

What the sources say (checked 2026-10-21):

- **Kits: 256.** WeiDU's ADD_KIT fails above kit number 256 on every EE game
  ("The game requires ToBEx or GemRB to support more than 256 kits",
  `src/tpaction.ml`; `check_enhanced_engine ... allow_bgee=false`). No source
  for 320 was found. BG2:EE's KITLIST.2DA has 40 kits (IESDP), not 37.
- **Spell states: ids 0-255** without EEex (EEex `EEex_Stats_Patch.lua`);
  about 133 are the game's (IESDP's BG:EE list). The limit is on id values,
  not on a count.
- **Spells: 50 per type and level** is WeiDU ADD_SPELL's allocation
  (`add_spell.tpa`, `tb#max_spell = 50`); 99 for innate and class spells.
- **No source says patch 2.5, 2.6 or 2.7 changed any of them**, and WeiDU
  treats every EE game alike.
- krion64's spell-state counts include ids a mod only reads: EE Fixpack is
  counted 19 and only looks existing states up (`IDS_OF_SYMBOL`). Summed over
  a real 148-mod EET install that plays, they reach 257/256.

Forum statements (a crash past kit row 256, a Beamdog developer on 256
spell states) could only be seen through search summaries here; they are
cited as reported, not verified.

krion64's method, audited before adopting it (its scripts, and its records
against 103 mod repositories):

- **Spells per level** come from `scripts/scan_spell_ids.js`, which reads only
  literal `APPEND spell.ids` lines. ADD_SPELL - WeiDU's own way, which picks
  a free slot - is not seen: NWNForBG adds 6 wizard spells with it and
  Region of Terror 4; krion64 records 0 for both. Entries with variables are
  left for "manual review", and the scan is per mod folder.
- **Spell states** (`ss`) count references, as above.
- **Kits** (`k`) are "the number of ADD_KIT calls", entered by hand; most
  mods add kits through function libraries (fl#add_kit_ee, Argent77's
  ADD_KIT_EX), which no scanner of theirs follows. Argent77's library has the
  same 256 limit, and exempts multiclass kits on EE 2.0+.
- Its records also join a mod folder's tp2s: EET and EET_end share `eet/`
  and component #0.

None of the three is exact, and a static scan of our own would not be either:
ADD_SPELL reuses an identifier SPELL.IDS already has, and conditions decide
which calls run. What is exact is the game folder itself.

### Decision

- `limits.py` counts, per install: kits against 256 with the game's 40;
  spell states against 256 with the game's 133; spells per type and level
  against 50 with the game's own count. Each table names its source, and
  where Infinity Mod Forge uses another number, that number too.
- Warnings only, never a refusal: a warning at 90% of a table, an error past
  its end. Nothing depends on the game's patch version.
- The spell-state table is shown and never warned on: its counts are an
  upper bound. With EEex installed its range is lifted.
- A mod krion64 has no counts for is named, and the totals read "at least".
- **Measured, not estimated, wherever the game folder is known**: a WeiDU.log
  beside a chitin.key is a game. Its tables are read by WeiDU's own rules,
  from override/ first, then from the BIFF chitin.key names: the last kit
  number in KITLIST.2DA (`get_next_kit_number`); a spell slot as taken when
  ADD_SPELL would skip it - an id in SPELL.IDS or ADD_SPELL.IDS, or an
  SPWI/SPPR file already there (`TB#ADD_SPELL_FIND_SLOT`); the ids 0-255 in
  SPLSTATE.IDS. krion64's counts then only add the chosen components the
  game's WeiDU.log does not list. A measured spell-state table is warned on.
- The measurement is tested against the real WeiDU (CI,
  `tests/test_real_weidu_limits.py`): on a synthetic BG2:EE with a real KEY
  and BIFF, ADD_KIT gives kit N+1 after N measured and refuses past 256, and
  ADD_SPELL takes exactly the slots measured as free.

### Consequences

- The conflict report (text and JSON, `engine_limits`) shows the three tables
  with who fills them, for the GUI's selection screen.
- A player told "kits 231/256" by this tool may see a different number in
  Infinity Mod Forge; the report says why.
- For an installed game the tables are exact; for a selection not installed
  yet they are krion64's estimates, labelled so: spell levels can be fuller
  than shown (ADD_SPELL is missed), spell states are an upper bound.
- A game whose BIFFs are compressed (BIFC, classic games), whose tables are
  XOR-encrypted (classic games) or damaged, falls back to the estimate, and says so by not being
  marked measured. Reading the game is read-only, size-capped, and a BIFF
  path from chitin.key that would leave the game folder is not followed.

---

## ADR-0035 — Components are chosen from the mod's own tp2, else from krion64's records

**Status**: accepted
**Date**: 2026-10-21

### Context

The wizard's mod selection (GUI-AUDIT item 16) offers components before
anything is downloaded, as BWS-NG does. The only exact list of a mod's
components is its tp2, read the way WeiDU reads it (`tra.describe`: 9,889 of
9,889 names identical to WeiDU's). A mod not yet downloaded has no tp2 here.
The catalogues the tool already reads differ: lcc-docs lists mods, not
components; krion64's per-mod records list components with WeiDU numbers
(`wc`), SUBCOMPONENT groups (`g`, named by `scn`), same-mod requirements
(`rd`) and removed components (`gone`).

Measured against WeiDU 251's own `--list-components` on 105 real mods
(`tools/krion_components_benchmark.py`): of 1,529 components WeiDU lists,
krion64 has 1,471 under the same number; 58 are missing from it (7 of them it
marks as removed though the tp2 still offers them), 13 it lists are not in the
tp2, and 85 mods are identical. 14 of the mods have no krion64 record.

### Decision

- `choices.py` gives each mod's components per tp2 and says where they came
  from: `tp2` - the staged mod's own tp2, which alone decides once the mod is
  staged - else `krion64`. A component removed (`gone`) or hidden
  (DEPRECATED) is not offered.
- `api.mod_choices(game, ...)` is list_mods' entry plus `tp2s`, filtered to
  the game (a mod whose games are unknown is kept), from the same community
  data cache a run uses.
- A mod with no known components cannot be chosen yet: a selection names
  components, and they are not guessed. Its row says so.
- The choice is `selection.json` (ADR-0030), written by `api.save_selection`
  through selection.json's own checks; the CLI reads it with `--selection`.

### Consequences

- About 4% of components are not offered before download, and a few offered
  ones no longer exist. A choice made from krion64's records is checked again
  against the tp2 once the mod is staged (the plan's own checks).
- The selection screen works offline from the last good data, and needs no
  download to start.

## ADR-0036 — Each community source is used for what it measures best

**Status**: accepted
**Date**: 2026-10-22

### Context

Three community projects describe the same mods, and the tool already reads
all three (ADR-0032): lcc-docs (the mod list, every known URL, a status and a
rating), krion64 (components, conflicts, install order, a scan of each
repository's latest release) and BigWorldSetup-NG (rules, and per mod an exact
file with size, platform and often a sha256, components, and the answers to
some WeiDU prompts). The question was whether downloads, and the wizard's
choices, should come from more than one of them, and from which for what.

Measured on 2026-10-22 over the mods for BGEE, SoD, BG2EE or EET (hidden and
absorbed ones left out), with `tools/download_sources_benchmark.py --bws ...
--probe` and `tools/krion_components_benchmark.py ORACLE KRION BWS`. Data:
lcc-docs 6d73f777df (last commit 2026-10-17), krion64 a8d17c4d5e
(2026-10-19), BWS-NG f7befca607 (2026-02-24, eight months old).

| | lcc-docs | krion64 | BWS-NG |
|---|---:|---:|---:|
| mods | 1,148 | 813 | 412 |
| with a GitHub repository | 852 | 651 | - |
| an exact file, and its sha256 | 11 direct archives without a repository | - | 409, 335 |

**Repositories** (lcc-docs and krion64, 665 mods both know): 428 name the
same one, 113 differ. Of those, krion64's is gone in 27 and lcc-docs' in
none; 23 are one repository under two names (a rename GitHub redirects); of
the 63 different live ones lcc-docs' has the newer last commit in 51,
krion64's in 11, one ties. The usual pattern is SHS's move from
`SpellholdStudios` to `Spellhold-Studios`. 148 mods only krion64 knows, 95 of
them with a repository. One krion64 record names a repository that cannot exist
(`...Lanthornhttps:`) while its URLs name the live one, so a record's `gh` is
read through the same URL check as any other URL.

**Exact files** (BWS-NG; tools with no tp2, such as WeiDU itself, left out):
279 of the 280 GitHub release tags it pins still exist (one repository is
gone). Against krion64's latest scanned release, the version it pins is the
same for 177 mods, older for 48 and newer for 3; 7 are spelled so they cannot
be compared ("8" against "v8_EE"), 35 are branch archives (always the newest)
and 142 have no scanned release.

**Components**, against WeiDU 251's own `--list-components` (ADR-0035): on
the 67 mods all three know (1,089 components), krion64 has 1,047 and BWS-NG
1,023; their union has 1,057 and brings 8 the tp2 does not have. Over every mod
it has a record for, krion64 has 1,471 of 1,529 (105 mods).

**Prompts**: only BWS-NG describes WeiDU prompts as data (`sub` components with
options and a default), for 4 components across its Enhanced Edition mods
(printed by the download tool).

### Decision

- **Where a mod is found** (repository, landing page): the manifest, then
  lcc-docs, as today. krion64's URLs are not added: on disagreement they are
  dead or older far more often.
- **Which file, and its checksum**: BWS-NG's exact file and sha256 verify the
  version they pin (as today). In the wizard's download phase BWS-NG's file
  becomes a candidate only when its version is the newest known; otherwise
  the repository's newest release wins and the BWS-NG checksum does not apply.
- **Components before download**: krion64, as ADR-0035. BWS-NG is not merged
  in: the union would add 10 of 1,089 components (0.9%) and 8 the mod does not
  offer.
- **Prompts**: BWS-NG is the only structured source, and covers 4 components.
  Drop-downs for prompts are built with M4, where recorded answers are used
  to install; a selection does not carry answers yet.
- **Rules and order**: BWS-NG's rules, krion64's records and order, as today.
- The 148 mods only krion64 knows are the case for using its repository as a
  third download candidate later, checked as any other (the archive must
  contain the right tp2).

### Consequences

- No behaviour change now. The measurements are reproducible with the two
  tools and go stale with the data; they are re-run before the download phase
  relies on them.
- 27 mods would resolve to a dead repository if krion64's URL were preferred,
  and 48 of the 228 comparable BWS-NG pins (one in five) would install an
  older release than the newest; both are avoided.
- BWS-NG's age (eight months at the time of writing) is reported by the data
  cache like any source's; it is a reason to prefer it for checksums of what it
  pins, not for what is newest.

---

## ADR-0037 — The authors' own install order is read before download

**Status**: accepted
**Date**: 2026-10-22

### Context

Project Infinity (PI, github.com/ALIENQuake/ProjectInfinity, 0.10.7; its wiki
pages "Adding metadata for mod", "Sorting Order feature", "Install Order
Groups") brings three ideas to install order:

1. A **metadata ini** beside the tp2 (`<tp2 name>.ini`, `[Metadata]`): identity
   and links, `LabelType`, and the author's own `Before`/`After` - other mods'
   tp2 names. It has no field for component conflicts.
2. A **Sorting Order** file the player writes: `Ascension *`, `Ascension 101
   102` - it sorts only what is chosen, and a component named on its own line
   leaves its mod's `*` line.
3. **Install Order Groups** the player arranges by hand: krion64's categories
   already play that part.

The tool read the metadata ini only from a staged mod (modmeta.py, ADR-0016).
But the order is planned, and the wizard judges conflicts, before anything is
downloaded; then only the community rule sets speak. LABELs are already read
(pi.py), so `LabelType` adds nothing.

Measured with `tools/pi_metadata_benchmark.py` on the 103 mods of the real
install (krion64 a8d17c4, BWS-NG f7befca): 85 ship a metadata ini; they state
314 order pairs. krion64's order agrees with 239; a rule (BWS-NG or krion64)
already covers 34 of the others; 22 span the two EET game phases; **19 are
known only to the author**: 7 contradict krion64's order (Region of Terror
after IWD1_EET and IWD2_EET; Kivan before Adrian; Deities of Faerun before
Tome and Blood; Homeward Bound before Crossmod BG2; JA#BGT AdvPack and
Transitions before Baldur's Seatower) and 12 name mods krion64 does not place.
Two of those name a mod by its display name ("Coran in BG2") and order nothing.

### Decision

- `premeta.py` fetches a planned mod's metadata ini before download: from the
  repository lcc-docs names (ADR-0036), else krion64's, at its default
  branch: beside the tp2, named after it with or without `setup-`, ignoring
  case. PI runs where case does not matter and GitHub does not: Region of
  Terror ships `RoT/rot.ini` beside `setup-RoT.tp2`, Deities of Faerun
  `Deitiesoffaerun.ini` beside `DeitiesOffaerun.tp2`, and a WeiDU log may spell
  `ASCENSION/ASCENSION.TP2`. The likely spellings are tried on
  raw.githubusercontent.com (no API quota); on a miss the folder is listed
  once (GitHub's contents API) and matched ignoring case, and only a listing
  records "no ini". At most 1 MiB, read as text with the same parser as a
  staged ini, never executed. Found and not-found are cached in the data
  cache, by mod and repository, for a week; an ini cached from another
  repository than the catalogue names today is not used.
- A network error is the network's, not the file's: nothing more is asked in
  that run, every mod still to ask backs off for an hour, and what was found
  before is kept. Requests are tried once with a short timeout, so the
  wizard's check, which asks after every change, costs seconds offline.
- `--fetch-metadata` asks for it in a run; the wizard's conflicts check asks
  for what is chosen. A fetched ini is used by every run once cached - its
  `Before`/`After` become order rules keyed by the tp2 name, with the
  author's file named as their origin - for the mods not staged; a staged
  mod's own ini wins. With `--no-default-data` the cache is used only when
  the run asked for it.
- `--sorting-order FILE` reads a PI Sorting Order file as order rules between
  consecutive lines of what is chosen; what is not chosen is skipped, nothing
  is added, and a component already placed by an earlier line stays there.
  It is the player's own: a staged mod's ini replaces the community's order
  rules about that mod, never these. A contradiction with another rule is
  reported as any order conflict is, not silently won.
- Install Order Groups and `LabelType` add nothing here and are not adopted.

### Consequences

- 19 order pairs per 314 (6%) reach the plan and the conflicts check before
  download; the 7 that contradict krion64 move mods where their authors put
  them.
- Per planned tp2, once a week: up to 8 small requests to
  raw.githubusercontent.com (the likely spellings; usually the first hits),
  and when none hits - an ini spelled otherwise, or no ini at all, the common
  case - a listing on GitHub's API of the root and of each level of the tp2's
  folder (two or three for the usual paths). That
  API allows 60 requests an hour without a credential (the tool's GitHub
  credential is used when it has one), so a large selection without one fills
  in over several hours: the quota is treated as the network being down, and
  what is left backs off for an hour. Offline, the cache is used; without it,
  the plan is what it was.
- One folder can hold several tp2s (EET's holds EET.tp2 and
  EET_end/EET_end.tp2); each has its own ini, wanted, cached and keyed by its
  own tp2 name. An error of one repository (a 451, a file over the cap) backs
  that tp2 off for an hour and keeps what it found before; it never stops the
  others. A 401 (a credential GitHub refuses) and a 403 or 429 (GitHub's
  quotas, the secondary one included) stop the run like a network failure.
- An author's ini can be wrong or old, like any rule source; its order rules
  carry the file as their origin, so a finding says whose claim it is.
- Component conflicts get nothing from PI: its format has no such field.
- *Amendment (2026-10-22).* The case-insensitive listing is checked against
  the real GitHub by `mod-metadata.yml` (`tools/premeta_live_check.py`), on
  pull requests that touch the fetch and weekly; until then it had been tested
  only with fake clients.

---

## ADR-0038 — The wizard's install order is the run's plan, and the player's order is a Sorting Order file

**Status**: accepted
**Date**: 2026-10-22

### Context

Phase 3 of the wizard (GUI-AUDIT item 17) shows the install order and lets
the player change it. Two things had to hold: what the page shows is what the
run will install, and a change the player makes reaches the command line too.

An EET build is two installs: mods for BG1 go on BG:EE before the conversion,
the rest on the EET game. The wizard saved one EET install, so the plan could
only report the BG1 mods as "in the wrong log", and splitting them later
would have renamed every finding's install - and with it every id a
decisions.json holds (ADR-0033).

### Decision

- **The selection is split where it is made.** For EET, `save_selection`,
  the conflicts check and the plan all build two installs - BGEE with the
  components krion64 files under a pre-EET category (per component where it
  places one apart), EET with the rest. Without krion64's data, one install,
  as before. The same selection is judged the same way everywhere.
- **The page is the plan.** `api.selection_plan` runs the planner a run with
  `--selection --plan-order` runs, on the same data, and returns each
  install's units in order: rule-placed ones marked (`constrained`), those an
  order rule still objects to marked (`flagged`), cycles and violations as
  text. A cycle names every unit left when it was broken, so it is reported,
  not marked.
- **The player's order is a Sorting Order file.** Dragging writes the whole
  order shown as `install-order.txt` in Project Infinity's format (ADR-0037)
  - `tp2 *`, or `tp2 N N` for a mod split across the order - and names it in
  the project's ini as `sorting_order` (read relative to the ini), so a run
  with that ini, `--selection selection.json` and `--plan-order` plans the
  same order. A test checks the page's order against the run's written logs.
  The ini is written first, so a project whose ini cannot be written keeps
  no order the command line would not see. The conflicts check of phase 2
  judges the same order. A rule-placed unit is one an order rule other than
  the player's own places: the hand order ties every unit to the next. It goes on top of the rules; a contradiction is shown as a
  violation or a cycle. "Use the computed order" deletes the file and the
  ini entry.
- Moving a mod between installs is not offered: which game it goes on is
  krion64's category, not a preference.

### Consequences

- The order the player sees, the order the CLI writes and the order PI would
  apply from the same file are one order.
- A hand order fixes every unit's place relative to its neighbours, so later
  rule changes show up as contradictions rather than silent moves; using the
  computed order again is one click.
- An EET selection.json now holds two installs; the selection page reads both
  back (a BGEE install alone is a BG:EE build, not EET's first phase).
- A finding's id names its install, so decisions saved by the unreleased
  phase-2 panel for mods of the BG:EE phase are reported stale once and must
  be made again. The panel offers to forget stale decisions (asked first;
  amendment, 2026-10-22), so they do not stay in the file for ever - only
  those the current, finished check calls stale, and none when no rule was
  checked (with no community data every decision would look stale).

---

## ADR-0039 — The wizard downloads through the command line's run, and with no manifest the community catalogue is the source

**Status**: accepted
**Date**: 2026-10-22

### Context

Phases 4 and 5 of the wizard (GUI-AUDIT item 18) are BWS-NG's Download and
Extraction. Two facts shaped them.

1. In the engine they are **one step per mod**. `Runner._attempt` downloads
   one archive, checks its sha256, unpacks it to a staging folder, checks it
   holds the tp2 it must, and only then moves it into the target. Extraction
   cannot start before its download ends and is not done for a mod apart from
   its download.
2. **A run needed a manifest** (`mod_downloads.json`). A wizard user has none:
   they chose mods from the catalogue, not from a file. Every mod the manifest
   lacks went to `unresolved`. With a catalogue the runner did try those mods
   through it (ADR-0009), but the run still refused to start without a
   manifest file.

A measurement found a third fact. lcc-docs records a mod that ships several
tp2s in one field, `EET;EET_end;EET_gui`, and the catalogue reader took that
as one name. **EET itself was never found in the catalogue**, by the
command line either.

### Decision

- **One page, "Download and extraction".** Each mod's row says which step it
  is at: downloading (bytes of total), extracting, done, already there,
  failed, no download found, cancelled. Splitting it into two pages would
  show a sequence the engine does not have. The phase list becomes Game and
  folders, Mod selection, Install order, Download and extraction,
  Installation (M4).
- **A new progress event**, `mod_extracting`, is emitted when a download is
  complete and verified and its archive is being unpacked. It is additive to
  events schema v1: a consumer that ignores unknown events is unaffected.
- **`api.download_selection(folder, on_event, cancel, only)`** is the run
  `iemod-fetch --config FOLDER/iemod-fetch.ini --selection
  FOLDER/selection.json` makes in FOLDER. `api.project_settings(folder)`
  builds those settings. The project ini's values go over the defaults, and
  its paths (target, manifest, catalogue, rules, ...) are read relative to the
  project. The selection is what is wanted: a WeiDU log or a list named in
  the ini is ignored. It is always a real download, never `check_only` or
  `dry_run`.
- **With no manifest, the community catalogue is the download source.**
  `Settings.manifest = None` (a project ini without `manifest`) gives an
  empty manifest, and every mod is found through lcc-docs from the data
  cache, then trusted-owner discovery. A candidate must still contain the
  right tp2. With neither a manifest nor a catalogue, the run stops with
  "no download source". The command line's default `mod_downloads.json`
  becomes optional in the same way: when that file is absent and a
  catalogue is present, the catalogue is the source, so the wizard and the
  command line agree in the same project. A manifest named on purpose
  (`-m FILE`) must exist; a typo is an error, never a silent switch.
- **What only a plan uses** (`language_preference`, `bgee_dir`,
  `bg2ee_dir`, `decisions`, ...) is refused without `--plan-order` only when
  given on the command line. The wizard's project ini holds the game folders
  and languages for every run in the project, and a BG:EE or BG2:EE project
  names one folder. Before this, every command-line run in a wizard project,
  and the wizard's own download, stopped on them. The download clears them,
  and the ini's `all_manifest_entries` and `only`: the selection is what is
  fetched.
- **A multi-tp2 catalogue record is found by each of its tp2s.** When several
  records share a tp2, the one whose repository is named after the mod wins
  (EET over EET_Android).
- **Nothing starts until the player clicks Download**, because it uses the
  network and the disk.
  - **Cancel** stops the downloads at their next chunk; what finished stays.
  - **Running again resumes**: a mod already there and verified is skipped.
  - **"Retry the failed"** runs `only` those mods.
  - **Next** is enabled once every mod is done or already there.
  - **Back** is locked while a download runs.
  - A **new selection** starts the phase again; a mod added since was never
    downloaded.
- **The run's events** come from its worker threads. They reach the page
  through a queued Qt signal, and each mod's byte count at most ten times a
  second, so a fast network cannot flood the window. Quitting cancels a
  running download before the application waits for its threads.

### Consequences

- The wizard and the command line fetch the same mods from the same sources
  into the same folder. Stopping in one and carrying on in the other works,
  because the state is the target folder.
- Measured on the supplied 145-mod EET WeiDU.log against lcc-docs alone
  (2026-10-22):
  - 138 mods have a candidate: 114 a GitHub repository, 1 a direct archive
    link, 23 only a landing page.
  - 7 have none. Their WeiDU folder is named otherwise in lcc-docs
    (`questpack` / `d0questpack`, `Reflections` / `Reflections_of_Destiny`,
    a typo `Brislelick`), or their record carries no URL.
  - Before the multi-tp2 fix, EET was among the misses.
  - The supplied manifest covers 135.
  - How many candidates hold the right mod can only be measured by
    downloading them. That needs the GitHub API, which this measurement's
    sandbox could not reach; it is not claimed.
- Landing pages are the weakest source: a scrape can find no archive. Those
  mods come back as "No download found", which the player can retry or fix
  with a manifest entry.
- `--list-mods` now lists EET, EET_end and EET_gui separately. Before, they
  appeared as one key that no tp2 had.
