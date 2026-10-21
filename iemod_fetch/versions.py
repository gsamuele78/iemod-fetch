"""
Comparing mod version strings, honestly.

Mod versions in this ecosystem are not semver: `v14.1`, `Alpha 3`,
`v0.11.0-alpha`, `vEAOB.9`, `2.8`, `v.4.6.4`, `20.2`. Any comparator will meet
pairs it cannot rank, and guessing there would be worse than admitting it — so
`compare` returns None for those, and every caller must handle None as
"unknown", never as "equal".
"""
import re
from typing import Optional, Tuple

# Stability ordering, least stable first:
#     branch snapshot  <  alpha  <  beta  <  rc  <  a numbered release
# A snapshot of master is what you get when a repository publishes no release at
# all, so it ranks lowest. Note this is a *stability* order, not a chronological
# one - master is often newer code than the last tag. Ranking it lowest is the
# conservative choice: it never lets a snapshot suppress a rule as "stale".
_PRERELEASE = {
    "master": -6, "main": -6, "head": -6, "trunk": -6, "default": -6,
    "snapshot": -5, "nightly": -5, "git": -5, "dev": -4, "devel": -4,
    "alpha": -3, "a": -3,
    "beta": -2, "b": -2,
    "rc": -1, "pre": -1, "prerelease": -1,
}
# `v1.2`, `V.1.2`, `Version 6.1`, `ver 2`: the word says nothing about order.
_TRIM = re.compile(r"^(?:(?:version|ver)(?=[\s._\d-])|[vV])\.?\s*", re.IGNORECASE)
_SPLIT = re.compile(r"[^0-9A-Za-z]+")


def parse_version(text: Optional[str]) -> Optional[Tuple]:
    """Split a version into comparable parts, or None if there is nothing to compare."""
    if not text:
        return None
    cleaned = _TRIM.sub("", str(text).strip())
    parts = []
    for chunk in _SPLIT.split(cleaned):
        if not chunk:
            continue
        for piece in re.findall(r"\d+|[A-Za-z]+", chunk):
            parts.append(int(piece) if piece.isdigit() else piece.lower())
    return tuple(parts) or None


def compare(left: Optional[str], right: Optional[str]) -> Optional[int]:
    """
    -1 / 0 / 1 if `left` is older / same / newer than `right`; None if unknown.
    """
    a, b = parse_version(left), parse_version(right)
    if not a or not b:
        return None
    for x, y in zip(a, b):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return -1 if x < y else 1
        # a pre-release marker sorts before the release it qualifies
        if isinstance(x, str) and isinstance(y, int):
            return -1 if x in _PRERELEASE else None
        if isinstance(x, int) and isinstance(y, str):
            return 1 if y in _PRERELEASE else None
        if x in _PRERELEASE and y in _PRERELEASE:
            if _PRERELEASE[x] == _PRERELEASE[y]:
                # Two spellings of the same stability level - `master`/`main`,
                # `alpha`/`a`, `rc`/`pre`. Returning 1 here (as this did) made
                # the comparator claim BOTH that master is newer than main and
                # that main is newer than master, so `is_newer` was true in both
                # directions and a synonym rename upstream could mark a rule
                # stale. They are equal at this position; the next one decides.
                continue
            return -1 if _PRERELEASE[x] < _PRERELEASE[y] else 1
        # One pre-release marker against an arbitrary word ("EAOB" vs "Alpha")
        # is not rankable either. Saying so is the point.
        return None
    if len(a) == len(b):
        return 0
    longer, sign = (a, 1) if len(a) > len(b) else (b, -1)
    rest = [p for p in longer[min(len(a), len(b)):] if p != 0]
    if not rest:
        return 0                         # 1.0 is 1: a trailing zero is no release
    tail = rest[0]
    if isinstance(tail, str) and tail in _PRERELEASE:
        return -sign                     # 1.0-alpha is older than 1.0
    return sign


def is_newer(candidate: Optional[str], baseline: Optional[str]) -> Optional[bool]:
    result = compare(candidate, baseline)
    return None if result is None else result > 0


def _digits(text: str) -> str:
    return "".join(re.findall(r"\d", text))


_BEFORE = re.compile(r"^pre[-_ .]*(?=v?\d)", re.IGNORECASE)


def compare_published(left: Optional[str], right: Optional[str]) -> Optional[int]:
    """
    `compare`, for two spellings of a release by different hands: an author's
    tp2 VERSION, its GitHub tag, a database's record of it. Measured on 95 mods
    (docs/TESTING.md); elsewhere the plain comparison stands.

    * A tag often drops the dots its tp2 keeps - `v071` for 0.71, `V19` for
      1.9, `v2.02` for 2.0.2. Same digits in the same order, same words, and
      either one side is a single number or both start with the same one:
      the same release.
    * `pre-v6.0` is the work towards 6.0: newer than 5.0, older than 6.0.
    """
    if left and _BEFORE.match(left):
        result = compare_published(_BEFORE.sub("", left), right)
        return -1 if result == 0 else result
    if right and _BEFORE.match(right):
        result = compare_published(left, _BEFORE.sub("", right))
        return 1 if result == 0 else result
    result = compare(left, right)
    if result in (None, 0) or not left or not right:
        return result
    a, b = parse_version(left) or (), parse_version(right) or ()
    numbers_a = [p for p in a if isinstance(p, int)]
    numbers_b = [p for p in b if isinstance(p, int)]
    same_words = [p for p in a if isinstance(p, str)] == [p for p in b if isinstance(p, str)]
    alike = ((len(numbers_a) == 1) != (len(numbers_b) == 1)
             or (numbers_a[:1] == numbers_b[:1] and len(numbers_a) != len(numbers_b)))
    if alike and same_words and _digits(left).lstrip("0") == _digits(right).lstrip("0"):
        return 0
    return result
