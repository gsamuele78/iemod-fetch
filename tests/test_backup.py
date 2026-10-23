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
    from iemod_fetch.errors import VerificationFailed
    with pytest.raises(VerificationFailed, match="damaged"):
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
    # 1: two changes could not be put back, which the plan says already
    assert code == 1 and "move aside: 5 files" in shown and "--apply" in shown
    assert (root / "mymod").exists()
    # with --apply: restored; 1 because two changes could not be put back
    code, out = run("--restore-backup", made["path"], "--apply")
    assert code == 1 and "nothing was deleted" in out
    assert not (root / "mymod").exists()


# ------------------------------------------------- review of #48 (data safety)
def backed_up(tmp_path):
    root = game(tmp_path)
    return root, backup.create(str(root), str(tmp_path / "backups"), name="before")


def test_restores_never_share_a_displaced_folder(tmp_path, monkeypatch):
    """Two restores in one second used one displaced-<time>/ and the second's
    moves replaced the first's files."""
    monkeypatch.setattr(backup.time, "strftime", lambda *_a: "20261023T000000")
    root, path = backed_up(tmp_path)
    write(root / "override" / "user.itm", b"first")
    first = backup.restore(path, str(root))
    write(root / "override" / "user.itm", b"second")
    second = backup.restore(path, str(root))
    assert first["displaced_to"] != second["displaced_to"]
    assert (pathlib.Path(first["displaced_to"]) / "override" / "user.itm").read_bytes() == b"first"
    assert (pathlib.Path(second["displaced_to"]) / "override" / "user.itm").read_bytes() == b"second"


@pytest.mark.parametrize("rel", ["../../escape.txt", "/etc/escape.txt", "C:/escape.txt",
                                 "override\\..\\..\\escape.txt", "override/../../escape.txt"])
def test_a_manifest_naming_a_path_outside_is_refused(tmp_path, rel):
    import hashlib
    import json
    root, path = backed_up(tmp_path)
    manifest_path = pathlib.Path(path) / backup.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = b"echo pwned"
    manifest["copied"][rel] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest["inventory"][rel] = len(data)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    from iemod_fetch.errors import VerificationFailed
    with pytest.raises(VerificationFailed, match="damaged"):
        backup.verify(path)
    with pytest.raises(VerificationFailed):
        backup.restore(path, str(root))
    assert not (tmp_path / "escape.txt").exists()


def test_a_manifest_missing_a_field_is_an_error_not_a_traceback(tmp_path):
    import json
    _root, path = backed_up(tmp_path)
    manifest_path = pathlib.Path(path) / backup.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["copied"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    from iemod_fetch import cli
    import io
    assert cli.main(["--verify-backup", path], stream=io.StringIO()) == 1


def test_a_restore_writes_only_into_a_game_folder_and_the_one_backed_up(tmp_path):
    root, path = backed_up(tmp_path)
    documents = tmp_path / "Documents"
    write(documents / "thesis.docx", b"years of work")
    with pytest.raises(ConfigError, match="not a game folder"):
        backup.restore(path, str(documents), other_folder=True)
    assert (documents / "thesis.docx").read_bytes() == b"years of work"
    other = tmp_path / "BG2EE-copy"
    write(other / "chitin.key", b"KEY V1  another install")
    with pytest.raises(ConfigError, match="not the folder this backup was made of"):
        backup.restore(path, str(other))
    backup.restore(path, str(other), other_folder=True)              # named: allowed
    assert (other / "chitin.key").read_bytes() == b"KEY V1  original"


@pytest.mark.skipif(os.name == "nt", reason="names that differ only in case need a "
                    "case-sensitive file system")
def test_a_file_differing_only_in_case_is_moved_aside_once(tmp_path):
    root = game(tmp_path)
    write(root / "override" / "X.ITM", b"backed up")
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    write(root / "override" / "x.itm", b"a mod's")
    plan = backup.plan_restore(path, str(root))
    assert plan["put_back"] == [] and plan["displace"] == ["override/x.itm"]
    backup.restore(path, str(root))
    assert (root / "override" / "X.ITM").read_bytes() == b"backed up"
    assert not (root / "override" / "x.itm").exists()
    again = backup.plan_restore(path, str(root))
    assert again["put_back"] == [] and again["displace"] == []


def test_folders_the_backup_had_stay_even_when_they_were_empty(tmp_path):
    root = game(tmp_path)
    (root / "save").mkdir()
    (root / "override" / "empty_sub").mkdir()
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    write(root / "save" / "000000001-Quick-Save" / "BALDUR.gam", b"a save")
    write(root / "override" / "empty_sub" / "new.itm", b"added")
    backup.restore(path, str(root))
    assert (root / "save").is_dir() and (root / "override" / "empty_sub").is_dir()
    assert not (root / "save" / "000000001-Quick-Save").exists()     # added, emptied


def test_a_rerun_after_a_cut_removes_the_mod_folders_it_emptied(tmp_path):
    root, path = backed_up(tmp_path)
    install(root)
    cancel = threading.Event()

    def on_progress(event):
        if event["event"] == "restore_displaced" and event["file"].startswith("mymod/"):
            cancel.set()
    with pytest.raises(InterruptedError):
        backup.restore(path, str(root), on_progress=on_progress, cancel=cancel)
    backup.restore(path, str(root))
    assert not (root / "mymod").exists()


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
def test_links_are_never_followed(tmp_path):
    root = game(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, root / "movies-link")              # a link the backup lists
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    assert backup.read_manifest(path)["links"] == ["movies-link"]
    # a backed-up file replaced by a dangling link: moved aside, never written through
    os.remove(root / "override" / "spwi101.spl")
    os.symlink(tmp_path / "outside.spl", root / "override" / "spwi101.spl")
    plan = backup.restore(path, str(root))
    assert plan["links"] == ["movies-link"] and (root / "movies-link").is_symlink()
    assert not (tmp_path / "outside.spl").exists()
    assert (root / "override" / "spwi101.spl").read_bytes() == b"SPL original"
    assert not (root / "override" / "spwi101.spl").is_symlink()


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
def test_a_backup_refuses_an_override_that_is_a_link(tmp_path):
    root = game(tmp_path)
    real = tmp_path / "real-override"
    (root / "override").rename(real)
    os.symlink(real, root / "override")
    with pytest.raises(ConfigError, match="is a link"):
        backup.create(str(root), str(tmp_path / "backups"))


def test_the_command_line_takes_one_backup_action_at_a_time(tmp_path):
    import io

    from iemod_fetch import cli
    root, path = backed_up(tmp_path)
    for argv in (["--backup", str(root), "--restore-backup", path, "--apply"],
                 ["--verify-backup", path, "--restore-backup", path],
                 ["--verify-backup", path, "--apply"],
                 ["--verify-backup", path, "--backup-to", str(tmp_path)]):
        assert cli.main(argv, stream=io.StringIO()) == 2, argv


def test_a_damaged_backup_exits_1_with_a_message(tmp_path):
    import io

    from iemod_fetch import cli
    root, path = backed_up(tmp_path)
    (pathlib.Path(path) / "files" / "chitin.key").write_bytes(b"tampered")
    assert cli.main(["--restore-backup", path, "--apply"], stream=io.StringIO()) == 1
