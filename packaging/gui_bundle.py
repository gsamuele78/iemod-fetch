#!/usr/bin/env python3
"""
Build the wizard as a program that needs no Python (GUI-AUDIT item 20,
ADR-0040): PyInstaller, one folder, zipped as
`dist/iemod-fetch-gui-<os>-<arch>.zip`, then started once to prove it runs.

    pip install "iemod-fetch[gui]" pyinstaller
    python packaging/gui_bundle.py [--dist dist]

One folder, not one file: Qt is LGPL-3.0, and its libraries stay separate
files beside the program, which a user may replace with their own build of
Qt (LGPL-3.0 section 4). The folder carries this project's licence, the LGPL
and GPL texts and NOTICE-Qt.txt, which says where Qt's and PySide6's source
is. The command-line `.pyz` stays standard-library only; this is the wizard.

The zip is unpacked again and the program in it started with --check
(offscreen): a build, or a zip, that cannot open its window fails here, not on
a player's machine. On macOS the .app is signed again, ad hoc, once the licence
files are in it. Links stay links in the zip (a .app's frameworks, Linux's
library names), as `unzip` and desktop archive tools restore them: copies would
double Qt's size and leave two files to replace for one library.
"""
import argparse
import importlib.metadata
import os
import re
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "iemod-fetch-gui"
with open(os.path.join(ROOT, "requirements", "runtime.txt"), encoding="utf-8") as _fh:
    RUNTIME_PINS = dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", _fh.read(),
                                   re.MULTILINE))
RUNTIME = tuple(RUNTIME_PINS)
FIXED = (1980, 1, 1, 0, 0, 0)                 # every entry's date: same folder, same zip
ENTRY = "import sys\nfrom iemod_fetch_gui.app import main\n\nsys.exit(main())\n"
# Qt modules the wizard never uses: kept out to keep the download small.
EXCLUDE = ("tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
           "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.Qt3DCore")


def tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    return f"{system}-{machine}"


def notice(versions: dict) -> str:
    return f"""iemod-fetch-gui bundles third-party software.

Qt {versions['qt']} and PySide6 {versions['pyside6']} (with shiboken6) are used
under the GNU Lesser General Public License v3.0 (LGPL-3.0-only); its text is
licenses/LGPL-3.0-only.txt, and the GPL it extends is licenses/GPL-3.0-only.txt.
They are dynamically linked: Qt's and PySide6's libraries are separate files in
this folder (under _internal, or Contents/Frameworks in the macOS app), and you
may replace them with your own builds of the same versions.

Source code:
  Qt       https://download.qt.io/official_releases/qt/
  PySide6  https://download.qt.io/official_releases/QtForPython/pyside6/
           https://code.qt.io/cgit/pyside/pyside-setup.git/

The Python {versions['python']} runtime is under the PSF License Agreement
(https://docs.python.org/3/license.html). The program was built with
PyInstaller {versions['pyinstaller']}, whose bootloader exception allows this
distribution (https://pyinstaller.org/en/stable/license.html).

iemod-fetch itself is under the MIT License: LICENSE.
"""


def versions() -> dict:
    import PyInstaller
    import PySide6
    from PySide6 import QtCore
    return {"qt": QtCore.qVersion(), "pyside6": PySide6.__version__,
            "pyinstaller": PyInstaller.__version__,
            "python": platform.python_version()}


def build(work: str) -> str:
    entry = os.path.join(work, "iemod_fetch_gui_main.py")
    with open(entry, "w", encoding="utf-8") as fh:
        fh.write(ENTRY)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--windowed", "--name", NAME, "--distpath", os.path.join(work, "out"),
            "--workpath", os.path.join(work, "build"), "--specpath", work,
            "--paths", ROOT]
    for module in EXCLUDE:
        args += ["--exclude-module", module]
    # the runtime's libraries (ADR-0043) with their data and metadata: the
    # Public Suffix List is a data file PyInstaller does not see by itself;
    # the pinned version, as build.py checks for the .pyz
    for name, pinned in RUNTIME_PINS.items():
        installed = importlib.metadata.version(name)
        if installed != pinned:
            raise SystemExit(f"{name} {installed} is installed, requirements/runtime.txt "
                             f"pins {pinned}")
    for name in RUNTIME:
        args += ["--collect-data", name, "--copy-metadata", name]
    subprocess.run(args + [entry], check=True, cwd=work)
    folder = os.path.join(work, "out", NAME)
    if platform.system() == "Darwin" and os.path.isdir(os.path.join(work, "out",
                                                                     NAME + ".app")):
        folder = os.path.join(work, "out", NAME + ".app")
    return folder


def executable(folder: str) -> str:
    if folder.endswith(".app"):
        return os.path.join(folder, "Contents", "MacOS", NAME)
    return os.path.join(folder, NAME + (".exe" if os.name == "nt" else ""))


def add_licences(folder: str) -> None:
    target = folder if not folder.endswith(".app") else os.path.join(
        folder, "Contents", "Resources")
    shutil.copy(os.path.join(ROOT, "LICENSE"), os.path.join(target, "LICENSE"))
    licences = os.path.join(target, "licenses")
    os.makedirs(licences, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(ROOT, "packaging", "licenses"))):
        shutil.copy(os.path.join(ROOT, "packaging", "licenses", name), licences)
    for name in RUNTIME:                     # publicsuffixlist MPL-2.0, filelock MIT
        dist = importlib.metadata.distribution(name)
        if dist.metadata.get("License-Expression") == "MPL-2.0":
            # MPL-2.0 3.2(a): where the Source Code Form of what ships compiled is
            urls = dict(url.split(", ", 1) for url in dist.metadata.get_all("Project-URL") or ())
            with open(os.path.join(target, f"NOTICE-{name}.txt"), "w", encoding="utf-8") as fh:
                fh.write(f"{name} {dist.version}, unmodified, is part of this program, under "
                         f"the Mozilla Public License 2.0 (licenses/{name}-LICENSE).\n"
                         f"Its source code: https://pypi.org/project/{name}/{dist.version}/#files"
                         + (f" and {urls['Homepage']}" if "Homepage" in urls else "") + "\n")
        for entry in dist.files or ():
            if "licenses" in str(entry).replace("\\", "/").split("/") or \
                    entry.name.startswith(("LICENSE", "COPYING")):
                shutil.copy(str(entry.locate()),
                            os.path.join(licences, f"{name}-{entry.name}"))
    with open(os.path.join(target, "NOTICE-Qt.txt"), "w", encoding="utf-8") as fh:
        fh.write(notice(versions()))


def sign(folder: str) -> None:
    """Re-sign a macOS .app ad hoc: the licence files added after PyInstaller
    signed it would otherwise break its signature, and macOS refuses it."""
    if folder.endswith(".app"):
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", folder], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", folder], check=True)


def check(folder: str, work: str) -> None:
    """Start the built program once, offscreen, as a player would."""
    project = os.path.join(work, "project")
    os.makedirs(project, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run([executable(folder), "--check", "--project", project],
                          env=env, capture_output=True, text=True, timeout=120,
                          check=False)
    if done.returncode != 0 or "ok" not in done.stdout:
        raise SystemExit(f"the built program does not start (exit {done.returncode}):\n"
                         f"{done.stdout}\n{done.stderr}")


def unpack(path: str, into: str) -> None:
    """Unzip as a player would: ditto on macOS; elsewhere as `unzip` does, links
    made again and the files' modes restored, so the program stays executable."""
    os.makedirs(into, exist_ok=True)
    if platform.system() == "Darwin":
        subprocess.run(["ditto", "-x", "-k", path, into], check=True)
        return
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            mode = info.external_attr >> 16
            target = os.path.join(into, *info.filename.split("/"))
            if stat.S_ISLNK(mode):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(zf.read(info).decode("utf-8"), target)
                continue
            zf.extract(info, into)
            if mode & 0o777:
                os.chmod(target, mode & 0o777)


def pack(folder: str, dist: str) -> str:
    os.makedirs(dist, exist_ok=True)
    path = os.path.join(dist, f"{NAME}-{tag()}.zip")
    base = os.path.dirname(folder)
    # Links stay links: a macOS .app's frameworks (Versions/Current) would lose
    # their layout and signature as copies, and Linux's links to Qt's libraries
    # would become second copies - the zip 48% bigger, and a library replaced
    # in one place still loaded from the other. Windows builds hold none.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for here, dirs, files in os.walk(folder):
            dirs.sort()
            for name in [d for d in dirs if os.path.islink(os.path.join(here, d))]:
                link(zf, os.path.join(here, name), base)
            for name in sorted(files):
                full = os.path.join(here, name)
                if os.path.islink(full):
                    link(zf, full, base)
                    continue
                info = zipfile.ZipInfo.from_file(full, os.path.relpath(full, base))
                info.date_time = FIXED
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)
    return path


def link(zf: zipfile.ZipFile, full: str, base: str) -> None:
    info = zipfile.ZipInfo(os.path.relpath(full, base).replace(os.sep, "/"), FIXED)
    info.create_system = 3                              # Unix, so the mode is read
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    zf.writestr(info, os.readlink(full))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dist", default=os.path.join(ROOT, "dist"))
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="iemod-gui-") as work:
        folder = build(work)
        add_licences(folder)
        sign(folder)
        path = pack(folder, os.path.abspath(args.dist))
        unpacked = os.path.join(work, "unpacked")
        unpack(path, unpacked)
        check(os.path.join(unpacked, os.path.basename(folder)), work)
    sys.stdout.write(f"{path} ({os.path.getsize(path):,} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
