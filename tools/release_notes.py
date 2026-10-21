#!/usr/bin/env python3
"""
Release notes from CHANGELOG.md, and kept in step with it (ADR-0027).

    python3 tools/release_notes.py notes VERSION   # print the section
    python3 tools/release_notes.py sync            # fix published bodies

`sync` runs in the release workflow on every push to main that touches the
changelog: each `## [X.Y.Z]` section with a published release vX.Y.Z is
compared with that release's body, and a body that no longer matches is
rebuilt from the section. The "Verify this download" block the release was
built with is kept, since its digest belongs to the artifacts. Editing a
release creates no ref, so GITHUB_TOKEN may do it.
"""
import re
import subprocess
import sys
from typing import List, Optional

VERIFY = "\n\n### Verify this download"
_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def versions(changelog: str) -> List[str]:
    return _HEADING.findall(changelog)


def section(changelog: str, version: str) -> Optional[str]:
    match = re.search(rf"^## \[{re.escape(version)}\].*?$(.*?)(?=^## \[|\Z)",
                      changelog, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else None


def refreshed(body: str, text: str) -> Optional[str]:
    """The body `text` calls for, or None when it already says that."""
    cut = body.find(VERIFY)
    wanted = text + (body[cut:] if cut >= 0 else "")
    return None if wanted.strip() == body.strip() else wanted


def _gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def sync(changelog: str) -> int:
    for version in versions(changelog):
        tag = f"v{version}"
        shown = _gh("release", "view", tag, "--json", "body", "--jq", ".body")
        if shown.returncode != 0:
            continue                                   # not released (yet)
        wanted = refreshed(shown.stdout.rstrip("\n"), section(changelog, version) or "")
        if wanted is None:
            continue
        edited = subprocess.run(["gh", "release", "edit", tag, "--notes-file", "-"],
                                input=wanted, text=True, check=False)
        if edited.returncode != 0:
            return edited.returncode
        print(f"{tag}: notes updated from CHANGELOG.md")
    return 0


def main(argv) -> int:
    with open("CHANGELOG.md", encoding="utf-8") as fh:
        changelog = fh.read()
    if len(argv) == 3 and argv[1] == "notes":
        version = argv[2].lstrip("v")
        print(section(changelog, version) or f"See CHANGELOG.md for {version}.")
        return 0
    if len(argv) == 2 and argv[1] == "sync":
        return sync(changelog)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
