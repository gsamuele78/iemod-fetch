#!/usr/bin/env python3
"""
The wizard's Windows zip as a per-user installer (ADR-0061): one setup.exe
that installs into %LOCALAPPDATA%\\Programs without asking for an
administrator, adds it to the Start menu and to "Installed apps", and
uninstalls cleanly.

    python packaging/gui_bundle.py --dist gui-dist          # the zip, checked
    python packaging/windows_installer.py gui-dist/iemod-fetch-gui-windows-x86_64.zip --dist gui-dist

The installer holds the same PyInstaller folder as the zip - the same
files, LICENSE, NOTICE-*.txt and licenses/ included, LICENSE shown on the
licence page - plus Inno Setup's licence and NOTICE-installer.txt. The zip stays in the release for whoever prefers it.

Inno Setup is downloaded at a pinned version, checked by sha256, and
installed for this build only, in its work folder. Its compiler builds the
installer from packaging/windows/. The installer's own code - the setup
program and unins000.exe - is Inno Setup's, under its licence (BSD-style):
its text goes into the installed folder, licenses/inno-setup/license.txt,
named by NOTICE-installer.txt.

The installer is then tried as a player would use it: a previous version
installed first, this one installed over it (one copy, one uninstaller,
this version registered), the installed program started once offscreen
with --check, uninstalled; the uninstaller must leave the data cache and
the project alone and unregister the program.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gui_bundle as shared  # noqa: E402

NAME = shared.NAME
SCRIPT = os.path.join(HERE, "windows", f"{NAME}.iss")
# Pinned, with its sha256 (measured 2026-11-16), from the project's own
# GitHub releases: jrsoftware.org is not reachable from every build machine.
INNO = (
    "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe",
    "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732")
INNO_VERSION = "6.7.3"
# What [Setup] DefaultDirName={autopf}\iemod-fetch-gui gives without administrator
INSTALL_DIR = os.path.join("Programs", NAME)
QUIET = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
# Where Windows lists it under "Installed apps": [Setup] AppId, per user
APP_ID = "{483B2769-37EB-4CC9-B7A8-410A2C01BCD1}"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
# The version the upgrade check installs first, then replaces; it carries
# one file more, in _internal, which the upgrade must take away
PREVIOUS = "0.0.0"
STALE = os.path.join("_internal", "left-by-the-previous-version.txt")
INSTALLER_NOTICE = f"""The installer this folder came from, and its uninstaller (unins000.exe),
are Inno Setup {INNO_VERSION}'s, by Jordan Russell and Martijn Laan, under the Inno
Setup License: its text is licenses/inno-setup/license.txt. Its source:
  https://github.com/jrsoftware/issrc/tree/is-{INNO_VERSION.replace(".", "_")}
The program itself is iemod-fetch-gui's folder, with its own licences and notices
(LICENSE, NOTICE-*.txt, licenses/).
"""


def version(root: str = shared.ROOT) -> str:
    """iemod-fetch's version, read from the package without importing it."""
    with open(os.path.join(root, "iemod_fetch", "__init__.py"), encoding="utf-8") as fh:
        found = re.search(r'^__version__\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
    if not found:
        raise SystemExit("build aborted: no __version__ in iemod_fetch/__init__.py")
    return found.group(1)


def fetch(url: str, digest: str, path: str) -> str:
    """`url` saved at `path`, refused unless its sha256 is `digest`."""
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (pinned https)
        data = response.read()
    found = hashlib.sha256(data).hexdigest()
    if found != digest:
        raise SystemExit(f"build aborted: {url} has sha256 {found}, not the pinned {digest}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def source_dir(zip_path: str, work: str) -> str:
    """The zip's folder, unpacked as a player would."""
    into = os.path.join(work, "zip")
    shared.unpack(zip_path, into)
    folder = os.path.join(into, NAME)
    for needed in (f"{NAME}.exe", "LICENSE", "licenses"):
        if not os.path.exists(os.path.join(folder, needed)):
            raise SystemExit(f"build aborted: {zip_path} holds no {NAME}/{needed}")
    return folder


def inno_install_args(setup: str, target: str) -> list[str]:
    """Inno Setup's own installer, silent, for this user only, into `target`:
    portable, so nothing is registered on the build machine."""
    return [setup, *QUIET, "/CURRENTUSER", "/PORTABLE=1", "/NOICONS", f"/DIR={target}"]


def compile_args(iscc: str, source: str, out_dir: str, name: str, ver: str) -> list[str]:
    return [iscc, "/Qp", f"/DAppVersion={ver}", f"/DSourceDir={source}",
            f"/DOutputDir={out_dir}", f"/DOutputName={name}", SCRIPT]


def inno(work: str) -> str:
    """ISCC.exe of the pinned Inno Setup, installed in `work`."""
    setup = fetch(*INNO, os.path.join(work, "innosetup.exe"))
    target = os.path.join(work, "inno")
    subprocess.run(inno_install_args(setup, target), check=True, timeout=600)
    iscc = os.path.join(target, "ISCC.exe")
    if not os.path.isfile(iscc):
        raise SystemExit(f"build aborted: Inno Setup installed no {iscc}")
    return iscc


def add_inno_licence(source: str, iscc: str) -> None:
    """Inno Setup's licence, from the copy that compiles this installer, and
    a notice naming it, into the folder the installer installs."""
    text = os.path.join(os.path.dirname(iscc), "license.txt")
    if not os.path.isfile(text):
        raise SystemExit(f"build aborted: no Inno Setup licence at {text}")
    with open(text, encoding="utf-8", errors="replace") as fh:
        if "Inno Setup License" not in fh.read():
            raise SystemExit(f"build aborted: {text} is not Inno Setup's licence")
    target = os.path.join(source, "licenses", "inno-setup")
    os.makedirs(target, exist_ok=True)
    shutil.copyfile(text, os.path.join(target, "license.txt"))
    with open(os.path.join(source, "NOTICE-installer.txt"), "w", encoding="utf-8") as fh:
        fh.write(INSTALLER_NOTICE)


def compile_setup(iscc: str, source: str, out_dir: str, name: str, ver: str) -> str:
    subprocess.run(compile_args(iscc, source, out_dir, name, ver), check=True, timeout=1800)
    out = os.path.join(out_dir, name + ".exe")
    if not os.path.isfile(out):
        raise SystemExit(f"build aborted: the compiler made no {out}")
    return out


def build(zip_path: str, work: str, dist: str, *, previous: bool) -> tuple[str, str | None]:
    """The installer in `dist`; with `previous`, also one of the same folder
    as version PREVIOUS, in `work`, for the upgrade check."""
    source = source_dir(zip_path, work)
    iscc = inno(work)
    add_inno_licence(source, iscc)
    out = compile_setup(iscc, source, dist, f"{NAME}-{shared.tag()}-setup", version())
    if not previous:
        return out, None
    older = os.path.join(work, "previous-source")
    shutil.copytree(source, older, symlinks=True)
    with open(os.path.join(older, STALE), "w", encoding="utf-8") as fh:
        fh.write("only in the previous version: an upgrade must remove it\n")
    return out, compile_setup(iscc, older, work, "previous-setup", PREVIOUS)


def registered_version() -> str | None:
    """The version "Installed apps" lists for this user, None if none."""
    import winreg  # Windows only
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return str(winreg.QueryValueEx(key, "DisplayVersion")[0])
    except FileNotFoundError:
        return None


def _wait_uninstalled(program: str, seconds: int = 180) -> None:
    """The uninstaller copies itself to %TEMP% and returns at once: wait for
    its work, not for the process - the program gone, then the
    "Installed apps" entry, which it removes last."""
    end = time.monotonic() + seconds
    while os.path.exists(program) or registered_version() is not None:
        if time.monotonic() > end:
            left = program if os.path.exists(program) else "the program in Installed apps"
            raise SystemExit(f"the uninstaller left {left} behind")
        time.sleep(1)


def say(text: str) -> None:
    sys.stdout.write(f"windows_installer: {text}\n")
    sys.stdout.flush()


def _install(setup: str, work: str, log: str) -> None:
    subprocess.run([setup, *QUIET, f"/LOG={os.path.join(work, log)}"], check=True,
                   timeout=600)


def check(setup: str, previous: str, work: str, ver: str) -> None:
    """Install the previous version, this one over it, start the installed
    program once, uninstall; one copy at a time, and what the player made
    must still be there."""
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    app = os.path.join(local, INSTALL_DIR)
    if os.path.exists(app) or registered_version() is not None:
        raise SystemExit(f"{app} exists already, or is registered: this check installs there")
    _install(previous, work, "install-previous.log")
    if registered_version() != PREVIOUS:
        raise SystemExit(f"the previous version registered {registered_version()!r}, "
                         f"not {PREVIOUS!r}")
    if not os.path.isfile(os.path.join(app, STALE)):
        raise SystemExit(f"the previous version did not install {STALE}")
    say(f"installed {PREVIOUS} in {app}")
    _install(setup, work, "install.log")
    # an upgrade replaces: the same folder, one uninstaller, this version
    # listed, and nothing of the previous version's _internal left
    if registered_version() != ver:
        raise SystemExit(f"after the upgrade, Installed apps lists {registered_version()!r}, "
                         f"not {ver!r}")
    if os.path.exists(os.path.join(app, "unins001.exe")):
        raise SystemExit("the upgrade installed beside the previous version (unins001.exe)")
    if os.path.exists(os.path.join(app, STALE)):
        raise SystemExit(f"the upgrade left the previous version's {STALE}")
    say(f"upgraded to {ver}: one entry in Installed apps, {STALE} removed")
    program = os.path.join(app, f"{NAME}.exe")
    for needed in (program, os.path.join(app, "LICENSE"), os.path.join(app, "licenses"),
                   os.path.join(app, "NOTICE-installer.txt"),
                   os.path.join(app, "licenses", "inno-setup", "license.txt"),
                   os.path.join(app, "unins000.exe")):
        if not os.path.exists(needed):
            raise SystemExit(f"the installer did not put {needed} in place")
    project = os.path.join(work, "project")
    os.makedirs(project, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run([program, "--check", "--project", project], env=env,
                          capture_output=True, text=True, timeout=180, check=False)
    if done.returncode != 0 or "ok" not in done.stdout:
        raise SystemExit(f"the installed program does not start (exit {done.returncode}):\n"
                         f"{done.stdout}\n{done.stderr}")
    say("the installed program started: --check ok")
    # what a player has made by now: the community-data cache and a project
    data = os.environ.get("IEMOD_DATA_DIR") or os.path.join(local, "iemod-fetch", "data")
    os.makedirs(data, exist_ok=True)
    markers = [os.path.join(data, "installer-check.marker"),
               os.path.join(project, "installer-check.marker")]
    for marker in markers:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("left by packaging/windows_installer.py\n")
    subprocess.run([os.path.join(app, "unins000.exe"), *QUIET], check=True, timeout=600)
    _wait_uninstalled(program)
    lost = [m for m in markers if not os.path.isfile(m)]
    for marker in markers:
        if os.path.isfile(marker):
            os.remove(marker)
    if lost:
        raise SystemExit("the uninstaller removed what the player made: " + ", ".join(lost))
    say("uninstalled: program and Installed apps entry gone, data cache and project kept")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("zip", help="the wizard's Windows zip, as gui_bundle.py made it")
    parser.add_argument("--dist", default=os.path.join(shared.ROOT, "dist"))
    parser.add_argument("--no-check", action="store_true",
                        help="build only; skip install, start and uninstall")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        raise SystemExit("the installer is built on Windows: Inno Setup's compiler is a Windows program")
    dist = os.path.abspath(args.dist)
    os.makedirs(dist, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="iemod-setup-") as work:
        out, previous = build(os.path.abspath(args.zip), work, dist,
                              previous=not args.no_check)
        if previous:
            check(out, previous, work, version())
        shutil.rmtree(os.path.join(work, "inno"), ignore_errors=True)
    sys.stdout.write(f"{out} ({os.path.getsize(out):,} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
