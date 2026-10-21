"""
The pinned WeiDU and mod_installer, compared with upstream (ADR-0028).

Dependabot cannot see them: WeiDU is a release zip with a sha256, mod_installer
a commit, both in ci.yml's `real-weidu` job. A weekly run compares them with
upstream and opens one issue per tool behind - never a pull request, because
a new digest must be checked by a person (the method of
Proxmox_biome_log_collector's upstream-versions.yml).
"""
from tools.upstream_versions import newest_weidu, pinned, verdicts

CI = """
    env:
      WEIDU_URL: https://github.com/WeiDUorg/weidu/releases/download/v251.00/WeiDU-Linux-251.zip
      WEIDU_SHA256: 3e1a34ec
      MOD_INSTALLER_REV: 3b6827a039db43e342be19f7610ecdd680fe0a62
      MOD_INSTALLER_VERSION: "16.0.0"
"""


def test_the_pins_are_read_from_ci_yml():
    assert pinned(CI) == {"weidu": "251.00", "mod_installer": "16.0.0"}


def test_nightlies_and_release_candidates_are_not_releases():
    tags = ["v249.00", "v251.00", "v251.06-rc5", "v252.01-nightly-5242d96", "v250.00"]
    assert newest_weidu(tags) == "251.00"
    assert newest_weidu(tags + ["v252.00"]) == "252.00"


def test_a_tool_behind_upstream_gets_an_issue_title():
    found = verdicts(pinned(CI), {"weidu": "252.00", "mod_installer": "16.0.0"})
    assert [(v.tool, v.latest) for v in found] == [("weidu", "252.00")]
    assert found[0].title == "WeiDU 252.00 is available (pinned 251.00)"


def test_nothing_is_reported_when_up_to_date_or_upstream_is_older():
    assert verdicts(pinned(CI), {"weidu": "251.00", "mod_installer": "15.2.0"}) == []
