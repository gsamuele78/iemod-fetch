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
