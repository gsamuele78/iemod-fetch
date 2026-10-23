"""
Write a file whole or not at all (GUI-AUDIT M7 item 46).

Eight places wrote `path + ".tmp"` and renamed it over `path`. That fixed temp
name was shared: two runs saving the same file wrote into one temp, and a
crash left it behind. Here each write gets its own temp beside the target
(the rename stays on one file system), removed if anything fails, and the
target keeps the permissions it had.
"""
import contextlib
import os
import secrets


def write_text(path: str, text: str, *, private: bool = False,
               durable: bool = False) -> None:
    """
    Replace `path` with `text` (UTF-8) in one rename: a reader sees the old
    file or the new one, never half of it.

    private: a new file is readable by its owner only (a config holding a
        token); otherwise a new file gets the usual umask. An existing file
        keeps its own mode either way.
    durable: flush to disk before the rename, and the folder after it on
        POSIX, for state that must survive a power cut (what was installed).
    """
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o7777
    except OSError:
        mode = None
    temp = os.path.join(folder, f".{os.path.basename(path)}.{secrets.token_hex(6)}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                 0o600 if private else 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            if durable:
                fh.flush()
                os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise
    if durable and os.name == "posix":
        dir_fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
