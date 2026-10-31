#!/usr/bin/env python3
"""
Build the command line as a program that needs no Python (GUI-AUDIT item 36,
ADR-0043): PyInstaller, one folder, zipped as
`dist/iemod-fetch-cli-<os>-<arch>.zip`, then unzipped and run once.

    pip install --require-hashes -r requirements/runtime.txt
    pip install . pyinstaller
    python packaging/cli_bundle.py [--dist dist]

4.0.0 needs Python 3.14. Ubuntu 24.04 has 3.12, Debian trixie 3.13,
macOS's /usr/bin/python3 3.9: there the .pyz does not start, and this bundle
does. One folder rather than one file: a one-file program unpacks itself into
a temporary folder on every start, which is slower and what antivirus software
on Windows most often flags. No Qt, so no LGPL: the folder carries this
project's licence, the runtime libraries' licences (and publicsuffixlist's
MPL-2.0 notice), and a NOTICE for Python and PyInstaller's bootloader.

The zip is unpacked as a player would and the program in it asked for its
version and, offline, its help: a build that cannot start fails here.
"""
import argparse
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location("gui_bundle", os.path.join(HERE, "gui_bundle.py"))
assert _SPEC and _SPEC.loader
shared = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(shared)

ROOT = shared.ROOT
NAME = "iemod-fetch"
ZIP = "iemod-fetch-cli"
ENTRY = "import sys\nfrom iemod_fetch.cli import main\n\nsys.exit(main())\n"
# The wizard and Qt are another program; tkinter is never used.
EXCLUDE = ("tkinter", "PySide6", "shiboken6", "iemod_fetch_gui")
# The newest glibc a Linux bundle may need: Debian trixie's, the minimum
# platform (ADR-0043 amendment of 2026-10-31). A Python built on a newer
# system needs a newer glibc (setup-python's 3.14 for ubuntu-24.04 needs
# 2.38, review of #70), and the bundle would not start on the floor - so the
# build stops instead. Ubuntu 24.04 has 2.39.
MAX_GLIBC = (2, 41)
_GLIBC = re.compile(rb"GLIBC_2\.(\d+)(?:\.(\d+))?\x00")
# A need that is not a version number: packed relative relocations (glibc 2.36).
_GLIBC_ABI = {b"GLIBC_ABI_DT_RELR\x00": (2, 36)}


def notice(versions: dict) -> str:
    return f"""iemod-fetch, the command line, as a program that needs no Python.

The Python {versions['python']} runtime is under the PSF License Agreement
(licenses/Python-LICENSE.txt). The libraries it was built with, which come
with it - OpenSSL, libffi, zlib, expat, bzip2, mpdecimal and others,
depending on the system - are listed with their licences at
https://docs.python.org/3/license.html. The program was built with
PyInstaller {versions['pyinstaller']}, whose bootloader exception allows this
distribution (https://pyinstaller.org/en/stable/license.html). The libraries
it carries are listed with their licences under licenses/.

iemod-fetch itself is under the MIT License: LICENSE.
"""


def versions() -> dict:
    import PyInstaller
    return {"pyinstaller": PyInstaller.__version__, "python": platform.python_version()}


def build(work: str) -> str:
    entry = os.path.join(work, "iemod_fetch_main.py")
    with open(entry, "w", encoding="utf-8") as fh:
        fh.write(ENTRY)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--console", "--name", NAME, "--distpath", os.path.join(work, "out"),
            "--workpath", os.path.join(work, "build"), "--specpath", work,
            "--paths", ROOT]
    for module in EXCLUDE:
        args += ["--exclude-module", module]
    args += shared.runtime_args()
    subprocess.run(args + [entry], check=True, cwd=work)
    return os.path.join(work, "out", NAME)


def executable(folder: str) -> str:
    return os.path.join(folder, NAME + (".exe" if os.name == "nt" else ""))


def python_licence() -> str:
    """The interpreter's own LICENSE.txt: beside the standard library on
    POSIX, in the installation's root on Windows."""
    for place in (sysconfig.get_paths()["stdlib"], sys.base_prefix):
        path = os.path.join(place, "LICENSE.txt")
        if os.path.isfile(path):
            return path
    raise SystemExit("build aborted: this Python has no LICENSE.txt to ship with it")


def add_licences(folder: str) -> None:
    shutil.copy(os.path.join(ROOT, "LICENSE"), os.path.join(folder, "LICENSE"))
    shared.add_runtime_licences(folder)
    shutil.copy(python_licence(), os.path.join(folder, "licenses", "Python-LICENSE.txt"))
    with open(os.path.join(folder, "NOTICE.txt"), "w", encoding="utf-8") as fh:
        fh.write(notice(versions()))


def glibc_needed(folder: str) -> tuple[int, int] | None:
    """The newest glibc symbol version any library or program in the folder
    asks for: the names in an ELF file's version-needs table. glibc itself is
    never bundled, so every one found is a need, not a definition."""
    newest = None
    for here, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(here, name)
            if os.path.islink(path):
                continue
            with open(path, "rb") as fh:
                if fh.read(4) != b"\x7fELF":
                    continue
                fh.seek(0)
                data = fh.read()
            found = [(2, int(m.group(1))) for m in _GLIBC.finditer(data)]
            found += [version for name, version in _GLIBC_ABI.items() if name in data]
            for version in found:
                newest = version if newest is None or version > newest else newest
    return newest


def check_glibc(folder: str, limit: tuple[int, int] = MAX_GLIBC) -> None:
    needed = glibc_needed(folder)
    if needed is not None and needed > limit:
        raise SystemExit(f"the bundle needs glibc {needed[0]}.{needed[1]}, newer than "
                         f"{limit[0]}.{limit[1]} (Debian trixie, the minimum platform): "
                         f"build it on an older system, it would not start there")


def check(folder: str, work: str) -> None:
    """Run the unzipped program as a player would: its version, then its help
    (neither touches the network), from a folder of its own."""
    run = os.path.join(work, "run")
    os.makedirs(run, exist_ok=True)
    for argv, expect in (["--version"], "iemod-fetch"), (["--help"], "usage"):
        done = subprocess.run([executable(folder), *argv], cwd=run, capture_output=True,
                              text=True, timeout=120, check=False)
        if done.returncode != 0 or expect not in done.stdout.lower():
            raise SystemExit(f"the built program does not run {' '.join(argv)} "
                             f"(exit {done.returncode}):\n{done.stdout}\n{done.stderr}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dist", default=os.path.join(ROOT, "dist"))
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="iemod-cli-") as work:
        folder = build(work)
        if platform.system() == "Linux":
            check_glibc(folder)
        add_licences(folder)
        path = shared.pack(folder, os.path.abspath(args.dist), ZIP)
        unpacked = os.path.join(work, "unpacked")
        shared.unpack(path, unpacked)
        check(os.path.join(unpacked, os.path.basename(folder)), work)
    sys.stdout.write(f"{path} ({os.path.getsize(path):,} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
