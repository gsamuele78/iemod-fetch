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

A restore deletes nothing (ADR-0007): what is in the way - a file or link
added since, or the current version of a file the backup has - is MOVED into
`<backup>/displaced-<time>/` under its own path (a folder no other restore
uses; nothing in it is ever replaced), then the copy is put back and checked
against its sha256. A file that changed but was not copied cannot be restored;
it is named, never passed over. A restore that stops half-way is finished by
running it again: the plan is made from what is on disk.

A restore only writes into a game folder (one with chitin.key), and only at
paths the manifest may name: relative, no `..`, no drive, no backslash -
a manifest is a file anyone could have edited (review of #48).

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

from .errors import ConfigError, VerificationFailed

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


def _scan(root: str):
    """(files, folders, links) under root, relative with '/': regular files
    {rel: full path}, every folder (empty ones too), and every link - to a
    file or a folder, dangling or not - which is never followed."""
    files: Dict[str, str] = {}
    folders: List[str] = []
    links: List[str] = []
    for here, dirs, names in os.walk(root):
        for name in sorted(dirs):
            full = os.path.join(here, name)
            (links if os.path.islink(full) else folders).append(_rel(full, root))
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(here, d)))
        for name in sorted(names):
            full = os.path.join(here, name)
            if os.path.islink(full):
                links.append(_rel(full, root))
            elif os.path.isfile(full):
                files[_rel(full, root)] = full
    return files, sorted(folders), sorted(links)


def _is_game(folder: str) -> bool:
    return any(os.path.isfile(os.path.join(folder, key)) and
               not os.path.islink(os.path.join(folder, key))
               for key in ("chitin.key", "CHITIN.KEY", "Chitin.key"))


def _safe_rel(rel) -> bool:
    """A path a manifest may name: relative, '/'-separated, nothing that
    leaves the folder it is joined to on any system."""
    if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel or "\0" in rel \
            or rel.startswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


def _join(root: str, rel: str) -> str:
    """root/rel, refused unless it stays inside root (links resolved)."""
    path = os.path.join(root, *rel.split("/"))
    if not _safe_rel(rel) or not _inside(os.path.dirname(path), root):
        raise VerificationFailed(f"{rel}: a path outside {root}, refused")
    return path


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
    _check_shape(backup, manifest)
    return manifest


def _check_shape(backup: str, manifest: dict) -> None:
    """Every field a restore reads, of the type it reads it as; every path
    one it may join (review of #48: a hand-edited manifest wrote outside the
    game folder)."""
    def bad(why: str):
        return VerificationFailed(f"{backup}: the backup's manifest is damaged ({why})")
    for key in ("name", "game_dir", "created"):
        if not isinstance(manifest.get(key), str):
            raise bad(f"no {key}")
    copied, inventory = manifest.get("copied"), manifest.get("inventory")
    folders, links = manifest.get("folders"), manifest.get("links")
    if not isinstance(copied, dict) or not isinstance(inventory, dict) or \
            not isinstance(folders, list) or not isinstance(links, list):
        raise bad("copied, inventory, folders or links missing")
    for rel, size in inventory.items():
        if not _safe_rel(rel) or not isinstance(size, int) or isinstance(size, bool):
            raise bad(f"inventory entry {rel!r}")
    for rel, meta in copied.items():
        if rel not in inventory or not isinstance(meta, dict) or \
                meta.get("size") != inventory[rel] or not isinstance(meta.get("sha256"), str) \
                or len(meta["sha256"]) != 64:
            raise bad(f"copied entry {rel!r}")
    for rel in folders + links:
        if not _safe_rel(rel):
            raise bad(f"folder or link {rel!r}")


# ------------------------------------------------------------------- create

def create(game_dir: str, backups_dir: str, name: Optional[str] = None,
           on_progress: Progress = None, cancel: Optional[threading.Event] = None) -> str:
    """Back game_dir up into backups_dir/<name>; returns the backup's path.

    It is written as `<name>.partial` and renamed only once every copy is
    made and its manifest written: a backup that exists is complete."""
    game_dir = os.path.abspath(game_dir)
    if not _is_game(game_dir):
        raise ConfigError(f"{game_dir}: no chitin.key - not a game folder")
    backups_dir = os.path.abspath(backups_dir)
    if _inside(backups_dir, game_dir):
        raise ConfigError(f"{backups_dir} is inside the game folder: a backup there would "
                          f"back itself up and be displaced by its own restore")
    name = name or f"{os.path.basename(game_dir) or 'game'}-{time.strftime('%Y%m%dT%H%M%S')}"
    final = os.path.join(backups_dir, name)
    if os.path.exists(final):
        raise ConfigError(f"{final} exists already")
    present, folders, links = _scan(game_dir)
    for rel in links:
        root_file = "/" not in rel and not os.path.isdir(os.path.join(game_dir, rel))
        if root_file or any(rel.lower() == d or rel.lower().startswith(d + "/")
                            for d in ("lang",) + COPIED_DIRS):
            # what a backup must copy would be left out without a word
            raise ConfigError(f"{game_dir}/{rel} is a link: a backup would not hold what it "
                              f"points at; make it a real file or folder first")
    work = final + PARTIAL
    if os.path.exists(work):
        shutil.rmtree(work)                         # our own unfinished attempt
    os.makedirs(os.path.join(work, FILES))

    entries = sorted(present.items())
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
                "folders": folders, "links": links,
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
        path = _join(os.path.join(backup, FILES), rel)
        if not os.path.isfile(path) or os.path.islink(path):
            problems.append(f"{rel}: missing")
        elif os.path.getsize(path) != meta["size"] or _sha256(path) != meta["sha256"]:
            problems.append(f"{rel}: changed since the backup was made")
    return {"ok": not problems, "files": len(manifest["copied"]), "problems": problems}


# ------------------------------------------------------------------ restore

def plan_restore(backup: str, game_dir: str) -> dict:
    """What restore() would do, from what is on disk now; changes nothing.

    - put_back: copied files missing or different now (they will be copied
      back; a current version is displaced first);
    - displace: files and links the backup does not know (added since),
      anywhere - matched by exact name: on a case-sensitive system a mod's
      `x.itm` beside a backed-up `X.ITM` is a file of its own (review of #48);
    - cannot_restore: files listed but not copied that are now missing or of
      another size - only their absence or change can be reported. A listed
      file whose name only changed case counts as present, so it is never
      moved away for want of a copy;
    - links: links the backup listed; left alone, never backed up."""
    manifest = read_manifest(backup)
    game_dir = os.path.abspath(game_dir)
    if not _is_game(game_dir):
        raise ConfigError(f"{game_dir}: no chitin.key - not a game folder, nothing to restore "
                          f"into")
    copied, inventory = manifest["copied"], manifest["inventory"]
    present, _folders, links_now = _scan(game_dir)
    # a listed, uncopied file found only under another case is that file
    uncopied_missing = {rel.lower(): rel for rel in inventory
                        if rel not in copied and rel not in present}
    renamed: Dict[str, str] = {}                       # listed rel -> its name now
    put_back, displace, cannot = [], [], []
    for rel in sorted(present):
        if rel in inventory:
            continue
        listed = uncopied_missing.pop(rel.lower(), None)
        if listed is not None:
            renamed[listed] = rel
        else:
            displace.append(rel)
    known_links = set(manifest["links"])
    displace = sorted(displace + [rel for rel in links_now if rel not in known_links])
    for rel, meta in sorted(copied.items()):
        now = present.get(rel)
        if now is None or os.path.getsize(now) != meta["size"] or _sha256(now) != meta["sha256"]:
            put_back.append(rel)
    for rel, size in sorted(inventory.items()):
        if rel in copied:
            continue
        now = present.get(renamed.get(rel, rel))
        if now is None:
            cannot.append(f"{rel}: missing, and not in the backup")
        elif os.path.getsize(now) != size:
            cannot.append(f"{rel}: changed, and not in the backup")
    return {"backup": os.path.abspath(backup), "game_dir": game_dir,
            "backed_up_from": manifest["game_dir"], "put_back": put_back,
            "displace": displace, "cannot_restore": cannot,
            "links": sorted(known_links & set(links_now))}


def _same_folder(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _new_aside(backup: str) -> str:
    """A displaced-<time> folder made now, by this restore alone: two restores
    in one second once shared one, and the second's moves replaced the
    first's files (review of #48)."""
    base = os.path.join(backup, DISPLACED + time.strftime("%Y%m%dT%H%M%S"))
    for n in range(1, 10000):
        path = base if n == 1 else f"{base}-{n}"
        try:
            os.makedirs(path)
            return path
        except FileExistsError:
            continue
    raise OSError(f"{backup}: no free displaced- folder name")


def restore(backup: str, game_dir: str, on_progress: Progress = None,
            cancel: Optional[threading.Event] = None, other_folder: bool = False) -> dict:
    """Bring game_dir back to the backup, deleting nothing (module doc).

    A folder other than the one backed up is restored only with other_folder
    (the caller named it): a moved or edited manifest must not point a restore
    at a folder the player did not choose."""
    check = verify(backup)
    if not check["ok"]:
        raise VerificationFailed(f"{backup}: the backup itself is damaged, nothing restored: "
                                 + "; ".join(check["problems"][:5]))
    plan = plan_restore(backup, game_dir)
    game_dir = plan["game_dir"]
    if not other_folder and not _same_folder(game_dir, plan["backed_up_from"]):
        raise ConfigError(f"{game_dir} is not the folder this backup was made of "
                          f"({plan['backed_up_from']}); name it as the target to restore there")
    if _inside(backup, game_dir) or _inside(game_dir, backup):
        raise ConfigError(f"{backup} and {game_dir} overlap")
    manifest = read_manifest(backup)
    asides: List[str] = []

    def move_aside(rel: str) -> None:
        source = _join(game_dir, rel)
        target = None
        for aside in asides:
            candidate = os.path.join(aside, *rel.split("/"))
            if not os.path.lexists(candidate) and not _blocked(aside, rel):
                target = candidate
                break
        if target is None:                 # first move, or a name that clashes
            asides.append(_new_aside(backup))
            target = os.path.join(asides[-1], *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.lexists(target):        # never replace what was moved aside
            raise OSError(f"{target} exists: nothing moved over it")
        shutil.move(source, target)
        _emit(on_progress, event="restore_displaced", file=rel)

    _emit(on_progress, event="restore_started", displace=len(plan["displace"]),
          put_back=len(plan["put_back"]))
    # what was added first - a link where a folder was included - so every
    # path put back below is a real folder of the game again
    for rel in plan["displace"]:
        _check_cancel(cancel)
        move_aside(rel)
    for rel in plan["put_back"]:
        _check_cancel(cancel)
        target = _join(game_dir, rel)
        if os.path.lexists(target):
            move_aside(rel)
        source = _join(os.path.join(backup, FILES), rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.lexists(target):
            raise OSError(f"{target} is still there: not written over")
        shutil.copy2(source, target, follow_symlinks=False)
        if _sha256(target) != manifest["copied"][rel]["sha256"]:
            raise VerificationFailed(f"{target}: the copy put back does not match the backup")
        _emit(on_progress, event="restore_put_back", file=rel)
    _remove_emptied(game_dir, keep={rel.lower() for rel in manifest["folders"]})
    result = {**plan, "displaced_to": asides[0] if asides else None, "displaced": asides}
    _emit(on_progress, event="restore_finished", **{k: result[k] for k in
                                                  ("displaced_to", "cannot_restore")})
    return result


def _blocked(aside: str, rel: str) -> bool:
    """Whether a parent of rel in aside is a file (a moved file where a
    folder is wanted now)."""
    parts = rel.split("/")[:-1]
    return any(os.path.lexists(p) and not os.path.isdir(p) or os.path.islink(p)
               for p in (os.path.join(aside, *parts[:i]) for i in range(1, len(parts) + 1)))


def _remove_emptied(game_dir: str, keep: set) -> None:
    """Empty folders the backup did not have, deepest first - including the
    ones a restore cut short left (review of #48); never a folder the backup
    had, empty or not, and never one holding anything."""
    _files, folders, _links = _scan(game_dir)
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
