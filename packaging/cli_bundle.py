#!/usr/bin/env python3
"""
Build the command line as a program that needs no Python (GUI-AUDIT item 36,
ADR-0043): PyInstaller, one folder, zipped as
`dist/iemod-fetch-cli-<os>-<arch>.zip`, then unzipped and run once.

    pip install --require-hashes -r requirements/runtime.txt
    pip install . pyinstaller
    python packaging/cli_bundle.py [--dist dist]

4.0.0 needs Python 3.14. Ubuntu 24.04 has 3.12, Debian 12 and 13 older ones,
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
import shutil
import subprocess
import sys
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


def notice(versions: dict) -> str:
    return f"""iemod-fetch, the command line, as a program that needs no Python.

The Python {versions['python']} runtime is under the PSF License Agreement
(https://docs.python.org/3/license.html). The program was built with
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


def add_licences(folder: str) -> None:
    shutil.copy(os.path.join(ROOT, "LICENSE"), os.path.join(folder, "LICENSE"))
    shared.add_runtime_licences(folder)
    with open(os.path.join(folder, "NOTICE.txt"), "w", encoding="utf-8") as fh:
        fh.write(notice(versions()))


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
        add_licences(folder)
        path = shared.pack(folder, os.path.abspath(args.dist), ZIP)
        unpacked = os.path.join(work, "unpacked")
        shared.unpack(path, unpacked)
        check(os.path.join(unpacked, os.path.basename(folder)), work)
    sys.stdout.write(f"{path} ({os.path.getsize(path):,} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
