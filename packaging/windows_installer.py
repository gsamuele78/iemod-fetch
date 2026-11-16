#!/usr/bin/env python3
"""
The wizard's Windows zip as a per-user installer (ADR-0061): one setup.exe
that installs into %LOCALAPPDATA%\\Programs without asking for an
administrator, adds it to the Start menu and to "Installed apps", and
uninstalls cleanly.

    python packaging/gui_bundle.py --dist gui-dist          # the zip, checked
    python packaging/windows_installer.py gui-dist/iemod-fetch-gui-windows-x86_64.zip --dist gui-dist

The installer holds the same PyInstaller folder as the zip, unchanged: the
same files, LICENSE, NOTICE-*.txt and licenses/ included, LICENSE shown on
the licence page. The zip stays in the release for whoever prefers it.

Inno Setup (its own licence, free for any use) is downloaded at a pinned
version, checked by sha256, and installed for this build only, in its work
folder. Its compiler builds the installer from packaging/windows/.

The installer is then tried as a player would use it: installed silently,
the installed program started once offscreen with --check, uninstalled; the
uninstaller must leave the data cache and the project alone.
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
# What [Setup] DefaultDirName={autopf}\iemod-fetch-gui gives without administrator
INSTALL_DIR = os.path.join("Programs", NAME)
QUIET = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]


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


def build(zip_path: str, work: str, dist: str) -> str:
    source = source_dir(zip_path, work)
    name = f"{NAME}-{shared.tag()}-setup"
    subprocess.run(compile_args(inno(work), source, dist, name, version()),
                   check=True, timeout=1800)
    out = os.path.join(dist, name + ".exe")
    if not os.path.isfile(out):
        raise SystemExit(f"build aborted: the compiler made no {out}")
    return out


def _wait_gone(path: str, seconds: int = 180) -> None:
    """The uninstaller copies itself to %TEMP% and returns at once: wait for
    its work, not for the process."""
    end = time.monotonic() + seconds
    while os.path.exists(path):
        if time.monotonic() > end:
            raise SystemExit(f"the uninstaller left {path} behind")
        time.sleep(1)


def check(setup: str, work: str) -> None:
    """Install silently, start the installed program once, uninstall; what
    the player made must still be there."""
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    app = os.path.join(local, INSTALL_DIR)
    if os.path.exists(app):
        raise SystemExit(f"{app} exists already: this check installs there")
    subprocess.run([setup, *QUIET, f"/LOG={os.path.join(work, 'install.log')}"],
                   check=True, timeout=600)
    program = os.path.join(app, f"{NAME}.exe")
    for needed in (program, os.path.join(app, "LICENSE"), os.path.join(app, "licenses"),
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
    # what a player has made by now: the community-data cache and a project
    data = os.environ.get("IEMOD_DATA_DIR") or os.path.join(local, "iemod-fetch", "data")
    os.makedirs(data, exist_ok=True)
    markers = [os.path.join(data, "installer-check.marker"),
               os.path.join(project, "installer-check.marker")]
    for marker in markers:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("left by packaging/windows_installer.py\n")
    subprocess.run([os.path.join(app, "unins000.exe"), *QUIET], check=True, timeout=600)
    _wait_gone(program)
    lost = [m for m in markers if not os.path.isfile(m)]
    for marker in markers:
        if os.path.isfile(marker):
            os.remove(marker)
    if lost:
        raise SystemExit("the uninstaller removed what the player made: " + ", ".join(lost))


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
        out = build(os.path.abspath(args.zip), work, dist)
        if not args.no_check:
            check(out, work)
        shutil.rmtree(os.path.join(work, "inno"), ignore_errors=True)
    sys.stdout.write(f"{out} ({os.path.getsize(out):,} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
