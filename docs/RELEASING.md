# Releasing

## What a release is

A git tag `vX.Y.Z`, and everything else is automated. The tag is the only manual
step, and there is no release script anyone has to run on a laptop with the
right credentials.

## Versioning

Semantic versioning, where **the public surface is the CLI** — its flags, its
exit codes, and the schema of `--json-report` and `--conflict-report`. The
Python API is internal and can change in a patch release.

- **Major** — a flag is removed or changes meaning; a JSON field is removed or
  its type changes; the tool starts refusing something it used to accept.
- **Minor** — a new flag, a new report section, a new catalogue format read.
- **Patch** — a fix, with no change to what a correct invocation produces.

A rule-data change is never a version bump: rule data lives in other people's
repositories and is refreshed with `git pull`.

## Cutting one — there is no tagging step

A release is a pull request. Nobody tags by hand (ADR-0027):

```bash
# 1. The changelog: move Unreleased into a dated heading, `## [2.3.0] - YYYY-MM-DD`.
# 2. The version, in two places that must agree:
$EDITOR iemod_fetch/__init__.py     # __version__ = "2.3.0"
$EDITOR pyproject.toml              # [project] version
# 3. Green locally, then open the pull request as usual.
make check && make cover && make audit && make build
```

Merging it is the release. The push to `main` changes `CHANGELOG.md`, so the
release workflow runs `tools/release_plan.py`. It reads the newest `## [X.Y.Z]`
section, and if `vX.Y.Z` does not exist yet it picks the commit to release: the
main-line merge where `__version__` first became X.Y.Z, so the pull request's
review fixes are in and nothing merged later is. Then, in order:

1. re-runs the entire CI gate, including the real-WeiDU job;
2. builds that commit: sdist, wheel and `.pyz`, after checking that its
   `__version__` matches the tag; records `SHA256SUMS`; writes a CycloneDX SBOM;
3. attests build provenance through Sigstore keyless signing;
4. **creates the tag `vX.Y.Z` and publishes the GitHub release**. The notes are
   that changelog section plus the verification commands;
5. publishes to PyPI through OIDC trusted publishing. This step is opt-in: it
   runs only once the repository variable `PYPI_PUBLISH` is `true`, and it is
   still gated by the `pypi` environment.

The workflow creates the tag itself, with its own `GITHUB_TOKEN`. A tag pushed
with that token starts no workflow, so creating the tag elsewhere would leave
nothing to build it. A version that is already tagged is skipped, which makes
re-runs and edits to old changelog sections harmless.

**An older version without a release** (v2.1.0 was merged before this
existed): *Actions → Release → Run workflow*, with `version` = `2.1.0`. It is
released on its own merge commit and not marked "latest".

**A tag pushed by hand** still works: that exact commit is released.

**Dry run**: *Run workflow* with `dry_run` checked builds and attests but
publishes nothing.

## What the operator can verify

Every release carries the three things needed to check that the download matches
the source:

```bash
# The digest, against SHA256SUMS in the release.
sha256sum iemod-fetch.pyz

# The provenance: which workflow, at which commit, produced these bytes.
gh attestation verify iemod-fetch.pyz --repo gsamuele78/iemod-fetch

# And the build is reproducible, so it can be checked from scratch.
git checkout v2.1.0 && python3 build.py && cmp iemod-fetch.pyz <downloaded>
```

That last one is why CI builds twice and compares. Reproducibility is what turns
a signature from "someone signed something" into "this artifact is that source".

## No long-lived secrets

There is no PyPI token in the repository settings and no signing key anywhere.
PyPI is reached with a short-lived OIDC token minted for that one workflow run,
and the signing identity *is* the workflow. Nothing exists to be exfiltrated
from a compromised action, which is the point.

## If a release is wrong

Yank it and cut a new patch. Do not move a tag: somebody has already downloaded
the artifact it pointed at, and an attestation that no longer matches its tag is
worse than a bad release.
