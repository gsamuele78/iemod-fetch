#!/usr/bin/env python3
"""
Compare the pinned WeiDU and mod_installer with upstream (ADR-0028).

Dependabot cannot see these pins: WeiDU is a release zip with a sha256 and
mod_installer a commit, both in ci.yml's `real-weidu` job. This compares them
with upstream and opens one issue per tool that is behind. It never opens a
pull request: a new digest has to be checked by a person. This is the method of
Proxmox_biome_log_collector's upstream-versions.yml.

    python3 tools/upstream_versions.py     # needs gh, GH_TOKEN; exit 1 = behind

Upstream, read through the GitHub API:
* WeiDU: the newest WeiDUorg/weidu tag that is a release (vNNN.NN). Nightlies
  and release candidates are left out.
* mod_installer: `version` in Cargo.toml on dark0dave/mod_installer's default
  branch. Its git tags stop at v12.1.1, so the version is the only signal.
"""
import base64
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

CI = ".github/workflows/ci.yml"
_WEIDU_PIN = re.compile(r"WEIDU_URL:\s*\S*/releases/download/v(\d+\.\d+)/")
_MI_PIN = re.compile(r"MOD_INSTALLER_VERSION:\s*\"?(\d+\.\d+\.\d+)\"?")
_WEIDU_TAG = re.compile(r"^v(\d+\.\d+)$")
_CARGO_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)

NAMES = {"weidu": "WeiDU", "mod_installer": "mod_installer"}
WHERE = {"weidu": "https://github.com/WeiDUorg/weidu/releases",
         "mod_installer": "https://github.com/dark0dave/mod_installer"}


def _key(version: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def pinned(ci_yaml: str) -> Dict[str, str]:
    out = {}
    weidu, installer = _WEIDU_PIN.search(ci_yaml), _MI_PIN.search(ci_yaml)
    if weidu:
        out["weidu"] = weidu.group(1)
    if installer:
        out["mod_installer"] = installer.group(1)
    return out


def newest_weidu(tags: Iterable[str]) -> Optional[str]:
    releases = [m.group(1) for m in map(_WEIDU_TAG.match, tags) if m]
    return max(releases, key=_key) if releases else None


@dataclass
class Verdict:
    tool: str
    pinned: str
    latest: str

    @property
    def title(self) -> str:
        return f"{NAMES[self.tool]} {self.latest} is available (pinned {self.pinned})"

    @property
    def body(self) -> str:
        return (f"Upstream: {WHERE[self.tool]}\n\n"
                "To bump (docs/RELEASING.md, \"Pinned test toolchain\"):\n\n"
                + ("1. Download `WeiDU-Linux-<version>.zip` from the release yourself "
                   "and run `sha256sum`.\n2. Update `WEIDU_URL` and `WEIDU_SHA256` in "
                   "`.github/workflows/ci.yml`.\n"
                   if self.tool == "weidu" else
                   "1. Pick the commit whose Cargo.toml says the new version and read "
                   "its changes (command line, EET mode).\n2. Update `MOD_INSTALLER_REV` "
                   "and `MOD_INSTALLER_VERSION` in `.github/workflows/ci.yml`.\n")
                + "3. CI green - the real-WeiDU job installs the mock EET plan with it.\n")


def verdicts(pins: Dict[str, str], latest: Dict[str, str]) -> List[Verdict]:
    return [Verdict(tool, pins[tool], latest[tool]) for tool in ("weidu", "mod_installer")
            if tool in pins and latest.get(tool)
            and _key(latest[tool]) > _key(pins[tool])]


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          check=True).stdout


def _upstream() -> Dict[str, str]:
    tags = json.loads(_gh("api", "--paginate", "--slurp",
                          "repos/WeiDUorg/weidu/tags?per_page=100"))
    names = [tag["name"] for page in tags for tag in page]
    cargo = json.loads(_gh("api", "repos/dark0dave/mod_installer/contents/Cargo.toml"))
    text = base64.b64decode(cargo["content"]).decode("utf-8")
    version = _CARGO_VERSION.search(text)
    return {"weidu": newest_weidu(names) or "",
            "mod_installer": version.group(1) if version else ""}


def main() -> int:
    with open(CI, encoding="utf-8") as fh:
        pins = pinned(fh.read())
    latest = _upstream()
    for tool in ("weidu", "mod_installer"):
        print(f"{NAMES[tool]}: pinned {pins.get(tool)}, upstream {latest.get(tool)}")
    behind = verdicts(pins, latest)
    for verdict in behind:
        search = f'in:title "{NAMES[verdict.tool]} {verdict.latest} is available"'
        open_ = _gh("issue", "list", "--state", "open", "--search", search,
                    "--json", "number", "--jq", "length").strip()
        if open_ == "0":
            _gh("issue", "create", "--title", verdict.title, "--body", verdict.body)
            print(f"opened: {verdict.title}")
    return 1 if behind else 0            # a red run means something to bump


if __name__ == "__main__":
    sys.exit(main())
