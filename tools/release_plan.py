#!/usr/bin/env python3
"""
Decide what the release workflow tags, and on which commit (ADR-0027).

Adopted from R-studioConf's ADR-0006: the newest `## [X.Y.Z]` section of
CHANGELOG.md names the release. It is tagged `vX.Y.Z` on the main-line
(first-parent) commit where `iemod_fetch/__init__.py` first says
`__version__ = "X.Y.Z"` - the merge of the release pull request, so every fix
made during its review is in, and nothing merged afterwards is. A tag that
already exists means already released.

    python3 tools/release_plan.py [VERSION]

prints `release=`, `tag=` and `sha=` lines for $GITHUB_OUTPUT; with no VERSION
the newest released section of CHANGELOG.md is used.
"""
import re
import subprocess
import sys
from typing import Dict, Optional

VERSION_FILE = "iemod_fetch/__init__.py"
_SECTION = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def newest_release(changelog: str) -> Optional[str]:
    """The first versioned section; `[Unreleased]` is not a release."""
    match = _SECTION.search(changelog)
    return match.group(1) if match else None


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def release_commit(repo: str, version: str) -> Optional[str]:
    """The oldest first-parent commit whose version file says `version`."""
    wanted = f'__version__ = "{version}"'
    commits = _git(repo, "rev-list", "--first-parent", "--reverse", "HEAD",
                   "--", VERSION_FILE).split()
    for sha in commits:
        text = subprocess.run(["git", "-C", repo, "show", f"{sha}:{VERSION_FILE}"],
                              capture_output=True, text=True, check=False).stdout
        if wanted in text.splitlines():
            return sha
    return None


def plan(repo: str, version: str) -> Dict[str, str]:
    tag = f"v{version}"
    exists = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify",
                             f"refs/tags/{tag}"], capture_output=True,
                            check=False).returncode == 0
    if exists:
        return {"release": "false", "tag": tag, "sha": ""}
    sha = release_commit(repo, version)
    if sha is None:
        raise SystemExit(f"{VERSION_FILE} never says __version__ = \"{version}\" on "
                         f"the main line: bump the version with the changelog")
    return {"release": "true", "tag": tag, "sha": sha}


def main(argv) -> int:
    if len(argv) > 1:
        version = argv[1].lstrip("v")
    else:
        with open("CHANGELOG.md", encoding="utf-8") as fh:
            found = newest_release(fh.read())
        if found is None:
            print("release=false")
            return 0
        version = found
    if not _SEMVER.match(version):
        raise SystemExit(f"not a version: {version!r}")
    for key, value in plan(".", version).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
