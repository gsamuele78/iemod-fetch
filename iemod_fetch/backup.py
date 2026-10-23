"""
A game folder's backup before mods are installed, and its restore (GUI-AUDIT
M4 item 21, ADR-0042).

What WeiDU changes is copied: `override/`, every `lang/*/dialog*.tlk`, and the
files at the folder's root (chitin.key, dialog.tlk on older games, WeiDU.log,
weidu.conf...). Everything else is only listed - path and size - in the
backup's inventory, so a restore can tell what an install ADDED anywhere (a mod
folder, a new BIFF in data/, a side folder) and what it CHANGED that was not
copied.

    backup = create(game_dir, backups_dir)     # <backups_dir>/<name>/
    verify(backup)                              # every copy against its sha256
    plan = plan_restore(backup, game_dir)       # what a restore would do
    restore(backup, game_dir)                   # do it

A restore deletes nothing (ADR-0007): what is in the way - a file added since,
or the current version of a file the backup has - is MOVED into
`<backup>/displaced-<time>/` under its own path, then the copy is put back and
checked against its sha256. A file that changed but was not copied cannot be
restored; it is named, never passed over. A restore that stops half-way is
finished by running it again: the plan is made from what is on disk.

Standard library only; nothing here runs WeiDU or anything downloaded.
"""
import contextlib
import hashlib
import json
import os
import shutil
import threading
import time
from typing import Callable, Dict, List, Optional

from .errors import ConfigError

SCHEMA_VERSION = 1
MANIFEST = "iemod-backup.json"
FILES = "files"
PARTIAL = ".partial"
DISPLACED = "displaced-"
COPIED_DIRS = ("override",)
_CHUNK = 1024 * 1024

Progress = Optional[Callable[[dict], None]]


# ------------------------------------------------------------------ helpers

def _rel(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _is_copied(rel: str) -> bool:
    """Whether a path (relative, '/') is in what a backup copies."""
    parts = rel.split("/")
    if len(parts) == 1:
        return True                                   # a file at the root
    if parts[0].lower() in COPIED_DIRS:
        return True
    return (len(parts) == 3 and parts[0].lower() == "lang"
            and parts[2].lower().startswith("dialog") and parts[2].lower().endswith(".tlk"))


def _walk(root: str):
    """Every regular file under root, relative; links are not followed."""
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(here, d)))
        for name in sorted(files):
            full = os.path.join(here, name)
            if os.path.isfile(full) and not os.path.islink(full):
                yield _rel(full, root), full


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: str, folder: str) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return os.path.normcase(path) == os.path.normcase(folder) or \
        os.path.normcase(path).startswith(os.path.normcase(folder) + os.sep)


def _check_cancel(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise InterruptedError("cancelled")


def _emit(on_progress: Progress, **event) -> None:
    if on_progress is not None:
        on_progress(event)


def read_manifest(backup: str) -> dict:
    path = os.path.join(backup, MANIFEST)
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{backup}: not a readable backup ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"{backup}: not a backup this version can read")
    return manifest


# ------------------------------------------------------------------- create

def create(game_dir: str, backups_dir: str, name: Optional[str] = None,
           on_progress: Progress = None, cancel: Optional[threading.Event] = None) -> str:
    """Back game_dir up into backups_dir/<name>; returns the backup's path.

    It is written as `<name>.partial` and renamed only once every copy is
    made and its manifest written: a backup that exists is complete."""
    game_dir = os.path.abspath(game_dir)
    if not os.path.isfile(os.path.join(game_dir, "chitin.key")) and \
            not os.path.isfile(os.path.join(game_dir, "CHITIN.KEY")):
        raise ConfigError(f"{game_dir}: no chitin.key - not a game folder")
    backups_dir = os.path.abspath(backups_dir)
    if _inside(backups_dir, game_dir):
        raise ConfigError(f"{backups_dir} is inside the game folder: a backup there would "
                          f"back itself up and be displaced by its own restore")
    name = name or f"{os.path.basename(game_dir) or 'game'}-{time.strftime('%Y%m%dT%H%M%S')}"
    final = os.path.join(backups_dir, name)
    if os.path.exists(final):
        raise ConfigError(f"{final} exists already")
    work = final + PARTIAL
    if os.path.exists(work):
        shutil.rmtree(work)                         # our own unfinished attempt
    os.makedirs(os.path.join(work, FILES))

    entries = list(_walk(game_dir))
    copied = [(rel, full) for rel, full in entries if _is_copied(rel)]
    total = sum(os.path.getsize(full) for _, full in copied)
    _emit(on_progress, event="backup_started", files=len(copied), bytes=total)
    inventory: Dict[str, int] = {}
    hashes: Dict[str, dict] = {}
    done = 0
    for rel, full in entries:
        _check_cancel(cancel)
        size = os.path.getsize(full)
        inventory[rel] = size
        if not _is_copied(rel):
            continue
        target = os.path.join(work, FILES, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(full, target)
        hashes[rel] = {"size": size, "sha256": _sha256(target)}
        done += size
        _emit(on_progress, event="backup_progress", file=rel, bytes=done, total=total)
    manifest = {"schema_version": SCHEMA_VERSION, "name": name, "game_dir": game_dir,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "top_level": sorted(os.listdir(game_dir)),
                "copied": hashes, "inventory": inventory}
    with open(os.path.join(work, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    os.replace(work, final)
    _emit(on_progress, event="backup_finished", path=final, files=len(hashes), bytes=total)
    return final


# ------------------------------------------------------------------- verify

def verify(backup: str) -> dict:
    """Every copied file against its size and sha256."""
    manifest = read_manifest(backup)
    problems = []
    for rel, meta in sorted(manifest["copied"].items()):
        path = os.path.join(backup, FILES, *rel.split("/"))
        if not os.path.isfile(path):
            problems.append(f"{rel}: missing")
        elif os.path.getsize(path) != meta["size"] or _sha256(path) != meta["sha256"]:
            problems.append(f"{rel}: changed since the backup was made")
    return {"ok": not problems, "files": len(manifest["copied"]), "problems": problems}


# ------------------------------------------------------------------ restore

def plan_restore(backup: str, game_dir: str) -> dict:
    """What restore() would do, from what is on disk now; changes nothing.

    - put_back: copied files missing or different now (they will be copied
      back; a current version is displaced first);
    - displace: files the backup does not know (added since), anywhere;
    - cannot_restore: files listed but not copied that are now missing or of
      another size - only their absence or change can be reported."""
    manifest = read_manifest(backup)
    game_dir = os.path.abspath(game_dir)
    copied, inventory = manifest["copied"], manifest["inventory"]
    known_lower = {rel.lower(): rel for rel in inventory}
    present: Dict[str, str] = dict(_walk(game_dir))
    present_lower = {rel.lower(): rel for rel in present}

    put_back, displace, cannot = [], [], []
    for rel, meta in sorted(copied.items()):
        now = present_lower.get(rel.lower())
        if now is None or os.path.getsize(present[now]) != meta["size"] or \
                _sha256(present[now]) != meta["sha256"]:
            put_back.append(rel)
    for rel in sorted(present):
        if rel.lower() not in known_lower:
            displace.append(rel)
    for rel, size in sorted(inventory.items()):
        if rel in copied:
            continue
        now = present_lower.get(rel.lower())
        if now is None:
            cannot.append(f"{rel}: missing, and not in the backup")
        elif os.path.getsize(present[now]) != size:
            cannot.append(f"{rel}: changed, and not in the backup")
    return {"backup": os.path.abspath(backup), "game_dir": game_dir,
            "backed_up_from": manifest["game_dir"], "put_back": put_back,
            "displace": displace, "cannot_restore": cannot}


def restore(backup: str, game_dir: str, on_progress: Progress = None,
            cancel: Optional[threading.Event] = None) -> dict:
    """Bring game_dir back to the backup, deleting nothing (module doc)."""
    check = verify(backup)
    if not check["ok"]:
        raise ConfigError(f"{backup}: the backup itself is damaged, nothing restored: "
                          + "; ".join(check["problems"][:5]))
    plan = plan_restore(backup, game_dir)
    game_dir = plan["game_dir"]
    if _inside(backup, game_dir):
        raise ConfigError(f"{backup} is inside the game folder")
    manifest = read_manifest(backup)
    moves = plan["displace"] + [rel for rel in plan["put_back"]
                                if os.path.exists(os.path.join(game_dir, *rel.split("/")))]
    aside = os.path.join(backup, DISPLACED + time.strftime("%Y%m%dT%H%M%S"))
    _emit(on_progress, event="restore_started", displace=len(moves),
          put_back=len(plan["put_back"]))
    for rel in moves:
        _check_cancel(cancel)
        source = os.path.join(game_dir, *rel.split("/"))
        target = os.path.join(aside, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(source, target)
        _emit(on_progress, event="restore_displaced", file=rel)
    for rel in plan["put_back"]:
        _check_cancel(cancel)
        source = os.path.join(backup, FILES, *rel.split("/"))
        target = os.path.join(game_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        if _sha256(target) != manifest["copied"][rel]["sha256"]:
            raise OSError(f"{target}: the copy put back does not match the backup")
        _emit(on_progress, event="restore_put_back", file=rel)
    _remove_emptied(game_dir, moves, keep=set(_dirs_of(manifest["inventory"])))
    result = {**plan, "displaced_to": aside if moves else None}
    _emit(on_progress, event="restore_finished", **{k: result[k] for k in
                                                  ("displaced_to", "cannot_restore")})
    return result


def _dirs_of(inventory: Dict[str, int]):
    for rel in inventory:
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            yield "/".join(parts[:i]).lower()


def _remove_emptied(game_dir: str, moved: List[str], keep: set) -> None:
    """The folders this restore emptied by moving files out, when the backup
    did not have them: never a folder that was empty already."""
    folders = set()
    for rel in moved:
        parts = rel.split("/")[:-1]
        for i in range(len(parts), 0, -1):
            folders.add("/".join(parts[:i]))
    for rel in sorted(folders, key=lambda f: f.count("/"), reverse=True):
        if rel.lower() in keep:
            continue
        with contextlib.suppress(OSError):                      # only when empty
            os.rmdir(os.path.join(game_dir, *rel.split("/")))


def list_backups(backups_dir: str) -> List[dict]:
    """The finished backups in a folder, newest first."""
    found: List[dict] = []
    if not os.path.isdir(backups_dir):
        return found
    for name in os.listdir(backups_dir):
        path = os.path.join(backups_dir, name)
        if name.endswith(PARTIAL) or not os.path.isfile(os.path.join(path, MANIFEST)):
            continue
        try:
            manifest = read_manifest(path)
        except ConfigError:
            continue
        found.append({"path": path, "name": manifest["name"], "created": manifest["created"],
                      "game_dir": manifest["game_dir"], "files": len(manifest["copied"]),
                      "bytes": sum(m["size"] for m in manifest["copied"].values())})
    return sorted(found, key=lambda b: b["created"], reverse=True)
