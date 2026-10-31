"""
Published release notes follow CHANGELOG.md (ADR-0027).

A correction to a released section is published by the next push to main:
the release's body is rebuilt from the section, keeping the "Verify this
download" block the release was built with (its digest belongs to the
artifacts, not to the changelog).
"""
from tools.release_notes import refreshed, section

CHANGELOG = """# Changelog

## [Unreleased]

## [2.2.0] - 2026-10-21
- **`--simulate`: walk the plan.** fixed

## [2.1.0] - 2026-10-20
- a
"""

VERIFY = ("\n\n### Verify this download\n```\nsha256  abc  iemod-fetch.pyz\n"
          "gh attestation verify iemod-fetch.pyz --repo o/r\n```\n")


def test_a_section_is_the_text_under_its_heading():
    assert section(CHANGELOG, "2.2.0") == "- **`--simulate`: walk the plan.** fixed"
    assert section(CHANGELOG, "2.1.0") == "- a"
    assert section(CHANGELOG, "9.9.9") is None


def test_a_cut_body_is_rebuilt_keeping_its_verify_block():
    body = ": walk the plan.** broken" + VERIFY
    assert refreshed(body, section(CHANGELOG, "2.2.0")) == (
        "- **`--simulate`: walk the plan.** fixed" + VERIFY)


def test_a_body_already_in_step_is_left_alone():
    body = "- **`--simulate`: walk the plan.** fixed" + VERIFY
    assert refreshed(body, section(CHANGELOG, "2.2.0")) is None


def test_a_body_without_a_verify_block_is_the_section():
    assert refreshed("old", "new") == "new"


# --------------------------------------------- "Latest" on the newest release
def test_the_newest_released_version_is_the_one_marked_latest():
    """A back-fill published after the newest release must not stay Latest."""
    from tools.release_notes import newest_released
    released = {"v2.1.0", "v2.2.0"}.__contains__
    assert newest_released(CHANGELOG, released) == "v2.2.0"


def test_an_unreleased_newest_section_is_skipped():
    from tools.release_notes import newest_released
    assert newest_released(CHANGELOG, {"v2.1.0"}.__contains__) == "v2.1.0"
    assert newest_released(CHANGELOG, set().__contains__) is None


def test_latest_marks_the_newest_release_only_when_it_is_not_already(monkeypatch):
    import subprocess
    from tools import release_notes
    calls = []

    def gh(*args):
        calls.append(args)
        if args[:2] == ("release", "view"):
            return subprocess.CompletedProcess(args, 0, "true\n", "")
        if args[0] == "api":
            return subprocess.CompletedProcess(args, 0, current["tag"] + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(release_notes, "_gh", gh)
    current = {"tag": "v2.1.0"}                 # a back-fill took Latest
    assert release_notes.latest(CHANGELOG) == 0
    assert ("release", "edit", "v2.2.0", "--latest") in calls
    calls.clear()
    current["tag"] = "v2.2.0"                   # already right: nothing edited
    assert release_notes.latest(CHANGELOG) == 0
    assert not any(c[:2] == ("release", "edit") for c in calls)
