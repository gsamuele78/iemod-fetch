"""
What the release workflow tags, and where (ADR-0027).

The rule, adopted from R-studioConf's ADR-0006: the newest `## [X.Y.Z]` section
of CHANGELOG.md is the release; it is tagged on the main-line commit where
`__version__` first became X.Y.Z - the merge of the release pull request, so
every fix in that pull request is in, and nothing merged after it is. An
existing tag means already released: nothing to do.
"""
import subprocess

import pytest

from tools.release_plan import newest_release, plan, release_commit

CHANGELOG = """# Changelog

## [Unreleased]

## [2.2.0] - 2026-10-21
- b

## [2.1.0] - 2026-10-20
- a
"""


def test_the_newest_released_section_is_the_release():
    assert newest_release(CHANGELOG) == "2.2.0"


def test_a_changelog_with_only_unreleased_has_no_release():
    assert newest_release("## [Unreleased]\n- x\n") is None


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, version, message):
    (repo / "iemod_fetch").mkdir(exist_ok=True)
    (repo / "iemod_fetch" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (repo / "notes.txt").write_text(message)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """main: 2.0.0, then a release branch bumping to 2.1.0 plus a later fix,
    merged; then an unrelated commit still at 2.1.0."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.org")
    git(tmp_path, "config", "user.name", "t")
    commit(tmp_path, "2.0.0", "start")
    git(tmp_path, "checkout", "-q", "-b", "release")
    commit(tmp_path, "2.1.0", "bump")
    commit(tmp_path, "2.1.0", "fix found in review")
    git(tmp_path, "checkout", "-q", "main")
    git(tmp_path, "merge", "-q", "--no-ff", "-m", "Release 2.1.0 (#1)", "release")
    merge = git(tmp_path, "rev-parse", "HEAD")
    commit(tmp_path, "2.1.0", "docs after the release")
    return tmp_path, merge


def test_the_release_is_the_main_line_commit_where_the_version_appeared(repo):
    path, merge = repo
    assert release_commit(str(path), "2.1.0") == merge


def test_a_version_never_set_has_no_commit(repo):
    path, _merge = repo
    assert release_commit(str(path), "9.9.9") is None


def test_the_plan_skips_a_version_already_tagged(repo):
    path, merge = repo
    assert plan(str(path), "2.1.0") == {"release": "true", "tag": "v2.1.0",
                                        "sha": merge}
    git(path, "tag", "v2.1.0", merge)
    assert plan(str(path), "2.1.0")["release"] == "false"
