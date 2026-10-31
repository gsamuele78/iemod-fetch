"""
The game not running while it is installed into (GUI-AUDIT M8 item 67,
ADR-0051).

Two checks, before an install or a resume starts:

- no running program whose executable is in a game folder: the game itself,
  a launcher (InfinityLoader, EEex), a mod's own setup-*.exe or another
  WeiDU working on it;
- on Windows, every `dialog*.tlk` of the game opens with no sharing at all:
  a program holding one (the game, an editor such as Near Infinity) makes
  WeiDU fail when it writes it, at the end of a component.

mod_installer starts WeiDU for each batch itself, right after it logs the
batch (16.0.0: installers.rs L144, runner.rs L198), so nothing lets this
program check *before* a batch. During the run only the processes are looked
at again, at each batch, and a game started meanwhile is said, not stopped:
the dialog.tlk check cannot run then, WeiDU itself holds the file.

The idea, and the two checks, are Chriz Easy BG's (`engine/src/preflight.rs`
L399 and L735, MIT); the code is written here.

What is not seen: a process this user may not inspect (another account's,
an elevated one on Windows), and on macOS a game whose executable is outside
the folder given (an .app's Contents/MacOS when the folder is its
Contents/Resources). A listing that fails says nothing rather than refusing.
"""
import contextlib
import os
import subprocess
import sys
from collections.abc import Callable, Iterable

SHARING_VIOLATION, LOCK_VIOLATION = 32, 33


def _linux() -> list[str]:
    """The executables of the processes /proc lets this user read."""
    found = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            with contextlib.suppress(OSError):
                found.append(os.readlink(f"/proc/{pid}/exe"))
    return found


def _macos() -> list[str]:
    """ps's command paths (comm, full path on macOS)."""
    out = subprocess.run(["/bin/ps", "-axww", "-o", "comm="],  # noqa: S603 (fixed argv)
                         capture_output=True, text=True, timeout=10, check=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip().startswith("/")]


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _QUERY_LIMITED = 0x1000           # PROCESS_QUERY_LIMITED_INFORMATION
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        wintypes.DWORD, wintypes.HANDLE)
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _INVALID = wintypes.HANDLE(-1).value

    def _windows() -> list[str]:
        """Every process's image path that OpenProcess lets this user query."""
        pids = (wintypes.DWORD * 8192)()
        got = wintypes.DWORD()
        if not _kernel32.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(got)):
            raise ctypes.WinError(ctypes.get_last_error())
        found = []
        for pid in pids[:got.value // ctypes.sizeof(wintypes.DWORD)]:
            handle = _kernel32.OpenProcess(_QUERY_LIMITED, False, pid)
            if not handle:
                continue
            try:
                size = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(size.value)
                if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    found.append(buffer.value)
            finally:
                _kernel32.CloseHandle(handle)
        return found

    def _open_alone(path: str) -> int:
        """0 when `path` opens for reading and writing with no sharing, else
        the Windows error (32: another program has it open)."""
        handle = _kernel32.CreateFileW(path, 0xC0000000, 0, None, 3, 0x80, None)
        if handle == _INVALID or handle is None:
            return ctypes.get_last_error()
        _kernel32.CloseHandle(handle)
        return 0

# How this system lists its processes, and opens a file alone (Windows only:
# elsewhere nothing locks a file against WeiDU)
_LIST: Callable[[], list[str]]
_OPEN_ALONE: Callable[[str], int] | None = None
if sys.platform == "win32":
    _LIST, _OPEN_ALONE = _windows, _open_alone
elif sys.platform == "darwin":
    _LIST = _macos
else:
    _LIST = _linux                    # no /proc: an OSError, so None


def running_executables() -> list[str] | None:
    """The executables of the running processes this user can see; None
    when they could not be listed."""
    try:
        return _LIST()
    except (OSError, subprocess.SubprocessError):
        return None


def _under(path: str, folder: str) -> bool:
    try:
        path = os.path.normcase(os.path.realpath(path))
        folder = os.path.normcase(os.path.realpath(folder))
        return os.path.commonpath([path, folder]) == folder
    except (OSError, ValueError):     # another drive
        return False


def running_in(folders: dict[str, str], executables: Iterable[str] | None,
               ignore: Iterable[str] = ()) -> list[str]:
    """`name: executable` for each executable under one of the folders
    ({name: folder}), but those in `ignore` (this install's own tools)."""
    if executables is None:
        return []
    skip = {os.path.normcase(os.path.realpath(path)) for path in ignore if path}
    found = []
    for executable in sorted(set(executables)):
        if os.path.normcase(os.path.realpath(executable)) in skip:
            continue
        for name, folder in folders.items():
            if _under(executable, folder):
                found.append(f"{name}: {executable}")
                break
    return found


def _entries(folder: str) -> list[os.DirEntry]:
    try:
        with os.scandir(folder) as it:
            return list(it)
    except OSError:
        return []


def _tlks(folder: str) -> list[str]:
    return [entry.path for entry in _entries(folder)
            if entry.name.lower().startswith("dialog") and entry.name.lower().endswith(".tlk")
            and entry.is_file()]


def talk_tables(folder: str) -> list[str]:
    """The game's dialog*.tlk: in lang/*/ (the Enhanced Editions) and at its
    root, whatever the case of the names (Linux)."""
    found = _tlks(folder)
    for lang in _entries(folder):
        if lang.name.lower() == "lang" and lang.is_dir():
            for language in _entries(lang.path):
                if language.is_dir():
                    found += _tlks(language.path)
    return sorted(found)


def held_talk_tables(folders: dict[str, str],
                     open_alone: Callable[[str], int] | None = None) -> list[str]:
    """`name: path (why)` for each dialog*.tlk another program holds open.
    Windows only (elsewhere nothing locks a file against WeiDU), unless
    `open_alone` is given (tests)."""
    open_alone = open_alone or _OPEN_ALONE
    if open_alone is None:
        return []
    held = []
    for name, folder in folders.items():
        for path in talk_tables(folder):
            error = open_alone(path)
            if error in (SHARING_VIOLATION, LOCK_VIOLATION):
                held.append(f"{name}: {path} is open in another program")
            elif error:
                held.append(f"{name}: {path} cannot be opened for writing "
                            f"(Windows error {error})")
    return held


def problems(folders: dict[str, str],
             executables: Callable[[], list[str] | None] = running_executables,
             open_alone: Callable[[str], int] | None = None) -> list[str]:
    """What says the game is in use, in words; [] when nothing."""
    found = [f"{line} is running from the game folder - close it first"
             for line in running_in(folders, executables())]
    found += [f"{line} - close it first" for line in held_talk_tables(folders, open_alone)]
    return found
