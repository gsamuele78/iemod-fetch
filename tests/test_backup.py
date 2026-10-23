"""
A game folder's backup and restore (GUI-AUDIT M4 item 21, ADR-0042): what
WeiDU changes is copied and checked by sha256, the rest listed; a restore
deletes nothing - what is in the way is moved aside - and says what it could
not put back.
"""
import os
import pathlib
import threading

import pytest

from iemod_fetch import backup
from iemod_fetch.errors import ConfigError


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def game(tmp_path):
    root = tmp_path / "BG2EE"
    write(root / "chitin.key", b"KEY V1  original")
    write(root / "Baldur.exe", b"MZ" + b"\0" * 64)
    write(root / "override" / "spwi101.spl", b"SPL original")
    write(root / "lang" / "en_US" / "dialog.tlk", b"TLK english")
    write(root / "lang" / "de_DE" / "dialogF.tlk", b"TLK deutsch")
    write(root / "lang" / "en_US" / "fonts" / "font.ttf", b"font")   # listed only
    write(root / "data" / "AREA000A.bif", b"BIFF original")          # listed only
    write(root / "movies" / "intro.wbm", b"movie")                   # listed only
    (root / "empty").mkdir()                                         # stays empty
    return root


def install(root):
    """What an install does to a game folder."""
    write(root / "override" / "spwi101.spl", b"SPL patched by a mod")
    write(root / "override" / "newitem.itm", b"ITM added")
    write(root / "lang" / "en_US" / "dialog.tlk", b"TLK english with new strings")
    write(root / "chitin.key", b"KEY V1  with a new biff")
    write(root / "data" / "modded.bif", b"BIFF added")
    write(root / "WeiDU.log", b"~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // My mod\n")
    write(root / "mymod" / "setup-mymod.tp2", b"BACKUP ~mymod/backup~")
    write(root / "mymod" / "backup" / "0" / "spwi101.spl", b"SPL original")
    write(root / "data" / "AREA000A.bif", b"BIFF changed by a mod!")       # not copied
    os.remove(root / "movies" / "intro.wbm")                                # not copied


def test_what_wei_du_changes_is_copied_and_the_rest_listed(tmp_path):
    root = game(tmp_path)
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    manifest = backup.read_manifest(path)
    assert sorted(manifest["copied"]) == ["Baldur.exe", "chitin.key",
                                          "lang/de_DE/dialogF.tlk", "lang/en_US/dialog.tlk",
                                          "override/spwi101.spl"]
    assert "data/AREA000A.bif" in manifest["inventory"] and \
        "data/AREA000A.bif" not in manifest["copied"]
    assert manifest["copied"]["chitin.key"]["size"] == len(b"KEY V1  original")
    assert backup.verify(path) == {"ok": True, "files": 5, "problems": []}
    assert [b["name"] for b in backup.list_backups(str(tmp_path / "backups"))] == ["before"]


def test_a_restore_brings_the_game_back_and_deletes_nothing(tmp_path):
    root = game(tmp_path)
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    install(root)
    plan = backup.plan_restore(path, str(root))
    assert plan["put_back"] == ["chitin.key", "lang/en_US/dialog.tlk", "override/spwi101.spl"]
    assert plan["displace"] == ["WeiDU.log", "data/modded.bif", "mymod/backup/0/spwi101.spl",
                                "mymod/setup-mymod.tp2", "override/newitem.itm"]
    assert plan["cannot_restore"] == ["data/AREA000A.bif: changed, and not in the backup",
                                      "movies/intro.wbm: missing, and not in the backup"]

    result = backup.restore(path, str(root))
    assert (root / "override" / "spwi101.spl").read_bytes() == b"SPL original"
    assert (root / "lang" / "en_US" / "dialog.tlk").read_bytes() == b"TLK english"
    assert (root / "chitin.key").read_bytes() == b"KEY V1  original"
    for gone in ("WeiDU.log", "data/modded.bif", "mymod", "override/newitem.itm"):
        assert not (root / gone).exists(), gone
    assert (root / "empty").is_dir()                 # it was empty before: kept
    aside = pathlib.Path(result["displaced_to"])
    # nothing deleted: every file moved away is in displaced-*/, under its path
    assert (aside / "override" / "spwi101.spl").read_bytes() == b"SPL patched by a mod"
    assert (aside / "mymod" / "setup-mymod.tp2").read_bytes() == b"BACKUP ~mymod/backup~"
    assert (aside / "WeiDU.log").read_bytes().startswith(b"~MYMOD")
    assert result["cannot_restore"] == plan["cannot_restore"]

    again = backup.plan_restore(path, str(root))     # finished: nothing left to do
    assert again["put_back"] == [] and again["displace"] == []


def test_a_damaged_backup_restores_nothing(tmp_path):
    root = game(tmp_path)
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    install(root)
    (tmp_path / "backups" / "before" / "files" / "chitin.key").write_bytes(b"tampered")
    assert not backup.verify(path)["ok"]
    with pytest.raises(ConfigError, match="damaged"):
        backup.restore(path, str(root))
    assert (root / "override" / "newitem.itm").exists()            # untouched


def test_a_restore_cut_short_is_finished_by_running_it_again(tmp_path):
    root = game(tmp_path)
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    install(root)
    cancel = threading.Event()
    seen = []

    def on_progress(event):
        seen.append(event["event"])
        if event["event"] == "restore_displaced":
            cancel.set()                               # stop after the first move
    with pytest.raises(InterruptedError):
        backup.restore(path, str(root), on_progress=on_progress, cancel=cancel)
    assert seen.count("restore_displaced") == 1
    backup.restore(path, str(root))
    assert (root / "override" / "spwi101.spl").read_bytes() == b"SPL original"
    assert not (root / "mymod").exists()


def test_a_backup_is_refused_where_it_cannot_work(tmp_path):
    root = game(tmp_path)
    with pytest.raises(ConfigError, match="inside the game folder"):
        backup.create(str(root), str(root / "backups"))
    (tmp_path / "notagame").mkdir()
    with pytest.raises(ConfigError, match="chitin.key"):
        backup.create(str(tmp_path / "notagame"), str(tmp_path / "backups"))
    backup.create(str(root), str(tmp_path / "backups"), name="once")
    with pytest.raises(ConfigError, match="exists already"):
        backup.create(str(root), str(tmp_path / "backups"), name="once")


def test_a_cancelled_backup_is_never_taken_for_a_finished_one(tmp_path):
    root = game(tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        backup.create(str(root), str(tmp_path / "backups"), name="half", cancel=cancel)
    assert not (tmp_path / "backups" / "half").exists()
    assert (tmp_path / "backups" / ("half" + backup.PARTIAL)).exists()
    assert backup.list_backups(str(tmp_path / "backups")) == []
    backup.create(str(root), str(tmp_path / "backups"), name="half")   # retried cleanly
    assert [b["name"] for b in backup.list_backups(str(tmp_path / "backups"))] == ["half"]


def test_the_command_line_backs_up_shows_then_restores(tmp_path, monkeypatch):
    import io

    from iemod_fetch import cli

    def run(*argv):
        out = io.StringIO()
        return cli.main(list(argv), stream=out), out.getvalue()

    def no_network(*_args, **_kwargs):
        raise AssertionError("a backup action reached for the network")
    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.chdir(tmp_path)
    root = game(tmp_path)
    store = tmp_path / "store"
    code, out = run("--backup", str(root), "--backup-to", str(store))
    assert code == 0 and "5 files copied" in out
    [made] = backup.list_backups(str(store))
    assert run("--verify-backup", made["path"])[0] == 0
    install(root)
    code, shown = run("--restore-backup", made["path"])               # shown only
    assert code == 0 and "move aside: 5 files" in shown and "--apply" in shown
    assert (root / "mymod").exists()
    # with --apply: restored; 1 because two changes could not be put back
    code, out = run("--restore-backup", made["path"], "--apply")
    assert code == 1 and "nothing was deleted" in out
    assert not (root / "mymod").exists()
