"""
iemod_fetch.atomic (GUI-AUDIT M7 item 46): a file is written whole or not at
all, through a temp of its own, and keeps the permissions it had.
"""
import os
import stat

import pytest

from iemod_fetch import atomic
from iemod_fetch.atomic import write_text


def leftovers(folder):
    return [n for n in os.listdir(folder) if n.endswith(".tmp")]


def test_a_new_file_is_written_whole(tmp_path):
    path = tmp_path / "sub" / "state.json"
    write_text(str(path), '{"a": 1}\n')
    assert path.read_text(encoding="utf-8") == '{"a": 1}\n'
    assert leftovers(path.parent) == []


def test_a_failed_write_leaves_the_old_file_and_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("old", encoding="utf-8")

    def broken(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(atomic.os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        write_text(str(path), "new")
    assert path.read_text(encoding="utf-8") == "old"
    assert leftovers(tmp_path) == []


def test_each_write_has_its_own_temp(tmp_path, monkeypatch):
    """The old `path + ".tmp"` was one name for every writer of the file."""
    temps = []
    replace = os.replace
    monkeypatch.setattr(atomic.os, "replace",
                        lambda src, dst: (temps.append(src), replace(src, dst)))
    path = str(tmp_path / "state.json")
    (tmp_path / "state.json.tmp").write_text("a crash's leftover", encoding="utf-8")
    write_text(path, "one")
    write_text(path, "two")
    assert len(set(temps)) == 2 and path + ".tmp" not in temps
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == "two"


def test_text_is_utf8(tmp_path):
    path = tmp_path / "c.ini"
    write_text(str(path), "C:/Giochi/Baldur’s Gate\n")
    assert path.read_bytes().decode("utf-8").startswith("C:/Giochi/Baldur’s")


@pytest.mark.skipif(os.name == "nt", reason="file modes are POSIX")
def test_permissions(tmp_path):
    kept = tmp_path / "kept.ini"
    kept.write_text("x", encoding="utf-8")
    os.chmod(kept, 0o640)
    write_text(str(kept), "y", private=True)
    assert stat.S_IMODE(os.stat(kept).st_mode) == 0o640       # its owner's choice

    secret = tmp_path / "token.ini"
    write_text(str(secret), "y", private=True)
    assert stat.S_IMODE(os.stat(secret).st_mode) == 0o600

    umask = os.umask(0o022)
    try:
        plain = tmp_path / "report.json"
        write_text(str(plain), "y")
    finally:
        os.umask(umask)
    assert stat.S_IMODE(os.stat(plain).st_mode) == 0o644      # as open() would


def test_durable_flushes_the_file(tmp_path, monkeypatch):
    synced = []
    fsync = os.fsync
    monkeypatch.setattr(atomic.os, "fsync", lambda fd: (synced.append(fd), fsync(fd)))
    write_text(str(tmp_path / "a"), "x")
    assert synced == []
    write_text(str(tmp_path / "b"), "x", durable=True)
    assert len(synced) == (2 if os.name == "posix" else 1)    # the file, then its folder
