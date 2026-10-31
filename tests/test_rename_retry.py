"""
A file held for a moment on Windows - an antivirus scanning what was just
written - is renamed once it is let go, not refused (GUI-AUDIT M8 item 66).
Retried 12 times, 10 ms doubling to 1 s (Chriz Easy BG's measure, the idea);
any other error, and every error off Windows, at once.
"""
import ast
import errno
import os
import pathlib

import pytest

from iemod_fetch import atomic

ROOT = pathlib.Path(__file__).resolve().parent.parent / "iemod_fetch"


def held(winerror):
    exc = PermissionError(errno.EACCES, "The process cannot access the file")
    exc.winerror = winerror
    return exc


class Flaky:
    """Fails `times` times with `error`, then works."""

    def __init__(self, times, error):
        self.times, self.error, self.calls = times, error, 0

    def __call__(self, *args):
        self.calls += 1
        if self.calls <= self.times:
            raise self.error
        return "done"


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_a_held_file_is_tried_again_until_it_is_let_go(winerror):
    waits = []
    flaky = Flaky(3, held(winerror))
    assert atomic.retried(flaky, windows=True, sleep=waits.append) == "done"
    assert flaky.calls == 4 and waits == [0.01, 0.02, 0.04]


def test_it_gives_up_after_twelve_tries_and_about_five_seconds():
    waits = []
    flaky = Flaky(99, held(32))
    with pytest.raises(PermissionError):
        atomic.retried(flaky, windows=True, sleep=waits.append)
    assert flaky.calls == 12 and len(waits) == 11
    assert waits[-1] == 1.0 and 5.0 < sum(waits) < 5.5


@pytest.mark.parametrize("error", [
    held(2),                                            # not a hold
    FileNotFoundError(errno.ENOENT, "gone"),
    OSError(errno.EXDEV, "cross-device"),
])
def test_any_other_error_is_raised_at_once(error):
    flaky = Flaky(1, error)
    with pytest.raises(type(error)):
        atomic.retried(flaky, windows=True, sleep=lambda _s: pytest.fail("waited"))
    assert flaky.calls == 1


def test_off_windows_nothing_is_retried():
    flaky = Flaky(1, held(32))
    with pytest.raises(PermissionError):
        atomic.retried(flaky, windows=False, sleep=lambda _s: pytest.fail("waited"))


def test_replace_and_move_do_the_rename(tmp_path):
    (tmp_path / "a").write_text("a")
    atomic.replace(str(tmp_path / "a"), str(tmp_path / "b"))
    assert (tmp_path / "b").read_text() == "a"
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f").write_text("f")
    atomic.move(str(tmp_path / "d"), str(tmp_path / "e"))
    assert (tmp_path / "e" / "f").read_text() == "f" and not (tmp_path / "d").exists()


def test_move_copies_only_across_file_systems(tmp_path, monkeypatch):
    calls = []

    def cross_device(_source, _target):
        raise OSError(errno.EXDEV, "Invalid cross-device link")
    monkeypatch.setattr(atomic.os, "replace", cross_device)
    monkeypatch.setattr(atomic.shutil, "move", lambda s, t: calls.append((s, t)))
    atomic.move("a", "b")
    assert calls == [("a", "b")]

    def held_file(_source, _target):
        raise held(5) if os.name == "nt" else PermissionError(errno.EACCES, "held")
    monkeypatch.setattr(atomic.os, "replace", held_file)
    monkeypatch.setattr(atomic, "retried", lambda op, *a, **k: op(*a))
    with pytest.raises(PermissionError):                # never a copy for a held file
        atomic.move("a", "b")
    assert calls == [("a", "b")]


def test_every_rename_in_the_tool_goes_through_atomic():
    """A new os.replace/os.rename/shutil.move would not wait out a held file."""
    direct = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name == "atomic.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and (node.func.value.id, node.func.attr) in {
                        ("os", "replace"), ("os", "rename"), ("shutil", "move")}):
                direct.append(f"{path.name}:{node.lineno}")
    assert direct == []
