#!/usr/bin/env python3
"""
The wizard's Linux zip as a Flatpak bundle (ADR-0064), experimental: one
file a player installs with `flatpak install --user`, the runtime coming
from Flathub.

    python packaging/gui_bundle.py --dist gui-dist          # the zip, checked
    python packaging/flatpak.py gui-dist/iemod-fetch-gui-linux-x86_64.zip --dist gui-dist

The Flatpak holds the same PyInstaller folder as the zip, unchanged, under
/app/lib/: Python 3.14 and Qt come with it, as in the zip and the AppImage.
The runtime is org.freedesktop.Platform, branch RUNTIME_VERSION, for the
graphics driver, X11/Wayland, fonts and bsdtar (libarchive) for RAR and 7z
mods. flatpak-builder takes the branch's current commit: it is printed, not
pinned (ADR-0064).

The sandbox gets FINISH_ARGS and no more: the network, a window, the GPU -
no folder of the player's. Game and project folders are chosen through the
file portal; a game folder seen that way is said in the first phase, with
the command that gives the Flatpak the folder itself (gamedir.portal_note).
The running game cannot be seen from the sandbox: the install asks the
player to confirm it is closed (ADR-0063).

The bundle is then installed, started once offscreen with --check inside
the sandbox, and removed.

Needs flatpak and flatpak-builder, and the flathub remote for the runtime.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gui_bundle as shared  # noqa: E402

NAME = shared.NAME
# Provisional: confirmed by the owner before any Flathub submission
# (docs/RELEASING.md). Once published it cannot change.
APP_ID = "io.github.gsamuele78.iemod_fetch"
RUNTIME = "org.freedesktop.Platform"
SDK = "org.freedesktop.Sdk"
RUNTIME_VERSION = "26.08"
FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
# What the sandbox may do, and nothing else (ADR-0064):
FINISH_ARGS = [
    "--share=network",          # the mods, the community data, the tools' downloads
    "--socket=wayland",         # the window, on Wayland
    "--socket=fallback-x11",    # ... or on X11 when there is no Wayland
    "--share=ipc",              # X11's shared memory
    "--device=dri",             # OpenGL, for Qt
]
SOURCE = os.path.join(HERE, "flatpak")


def version(root: str = shared.ROOT) -> str:
    with open(os.path.join(root, "iemod_fetch", "__init__.py"), encoding="utf-8") as fh:
        found = re.search(r'^__version__\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
    if not found:
        raise SystemExit("build aborted: no __version__ in iemod_fetch/__init__.py")
    return found.group(1)


def manifest(source: str) -> dict:
    """flatpak-builder's manifest: the prepared folder `source` (the zip's
    folder and the desktop files) installed as it is."""
    return {
        "app-id": APP_ID,
        "runtime": RUNTIME,
        "runtime-version": RUNTIME_VERSION,
        "sdk": SDK,
        "command": NAME,
        "finish-args": list(FINISH_ARGS),
        "modules": [{
            "name": NAME,
            "buildsystem": "simple",
            "build-commands": [
                "mkdir -p /app/lib /app/bin",
                f"cp -a {NAME} /app/lib/",
                f"ln -s ../lib/{NAME}/{NAME} /app/bin/{NAME}",
                f"install -Dm644 {APP_ID}.desktop /app/share/applications/{APP_ID}.desktop",
                (f"install -Dm644 {APP_ID}.metainfo.xml "
                f"/app/share/metainfo/{APP_ID}.metainfo.xml"),
                (f"install -Dm644 {APP_ID}.svg "
                f"/app/share/icons/hicolor/scalable/apps/{APP_ID}.svg"),
            ],
            "sources": [{"type": "dir", "path": source}],
        }],
    }


def metainfo(ver: str, day: str) -> str:
    """The committed metainfo with this version's release added."""
    with open(os.path.join(SOURCE, f"{APP_ID}.metainfo.xml"), encoding="utf-8") as fh:
        text = fh.read()
    release = f'  <releases>\n    <release version="{ver}" date="{day}"/>\n  </releases>\n'
    return text.replace("</component>", release + "</component>")


def prepare(zip_path: str, work: str, ver: str, day: str) -> str:
    """The folder flatpak-builder copies: the zip's folder unpacked as it is
    (links kept), and the desktop entry, metainfo and icon."""
    source = os.path.join(work, "source")
    shared.unpack(zip_path, source)
    if not os.path.isfile(os.path.join(source, NAME, NAME)):
        raise SystemExit(f"build aborted: {zip_path} holds no {NAME}/{NAME}")
    for name in (f"{APP_ID}.desktop", f"{APP_ID}.svg"):
        shutil.copy2(os.path.join(SOURCE, name), os.path.join(source, name))
    with open(os.path.join(source, f"{APP_ID}.metainfo.xml"), "w", encoding="utf-8") as fh:
        fh.write(metainfo(ver, day))
    return source


def _run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    sys.stdout.write("+ " + " ".join(argv) + "\n")
    sys.stdout.flush()
    return subprocess.run(argv, check=True, **kwargs)  # noqa: S603 (fixed tools)


def runtime_commit() -> str:
    """The runtime commit this build used: printed for the log (ADR-0064)."""
    done = subprocess.run(["flatpak", "info", "--user", "--show-commit",
                           f"{RUNTIME}//{RUNTIME_VERSION}"],
                          capture_output=True, text=True, check=False)
    return done.stdout.strip() or "unknown"


def build(source: str, work: str, out: str) -> str:
    path = os.path.join(work, f"{APP_ID}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest(source), fh, indent=2)
    repo = os.path.join(work, "repo")
    _run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB])
    _run(["flatpak-builder", "--user", "--install-deps-from=flathub", "--force-clean",
          "--disable-rofiles-fuse", f"--repo={repo}", os.path.join(work, "build"), path])
    sys.stdout.write(f"runtime {RUNTIME}//{RUNTIME_VERSION} at commit {runtime_commit()}\n")
    _run(["flatpak", "build-bundle", f"--runtime-repo={FLATHUB}", repo, out, APP_ID])
    return out


# Run inside the sandbox: the program starts offscreen, the sandbox is the
# one the finish-args make, and the runtime has bsdtar for RAR and 7z mods
CHECK = (f"test -f /.flatpak-info && command -v bsdtar >/dev/null && mkdir -p /tmp/project "
         f"&& QT_QPA_PLATFORM=offscreen {NAME} --check --project /tmp/project")


def check(bundle: str) -> None:
    """Install the bundle for this user, start it once in its sandbox,
    remove it."""
    _run(["flatpak", "install", "--user", "--noninteractive", "-y", "--bundle", bundle])
    try:
        done = subprocess.run(["flatpak", "run", "--command=sh", APP_ID, "-c", CHECK],
                              capture_output=True, text=True, timeout=300, check=False)
        if done.returncode != 0 or "ok" not in done.stdout:
            raise SystemExit(f"the Flatpak does not start (exit {done.returncode}):\n"
                             f"{done.stdout}\n{done.stderr}")
        shown = subprocess.run(["flatpak", "info", "--user", "--show-permissions", APP_ID],
                               capture_output=True, text=True, check=False).stdout
        sys.stdout.write(f"the Flatpak started in its sandbox; its permissions:\n{shown}")
    finally:
        subprocess.run(["flatpak", "uninstall", "--user", "--noninteractive", "-y", APP_ID],
                       check=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("zip", help="the wizard's Linux zip, as gui_bundle.py made it")
    parser.add_argument("--dist", default=os.path.join(shared.ROOT, "dist"))
    args = parser.parse_args(argv)
    for tool in ("flatpak", "flatpak-builder"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is needed to build the Flatpak")
    dist = os.path.abspath(args.dist)
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, f"{NAME}-{shared.tag()}.flatpak")
    day = time.strftime("%Y-%m-%d", time.gmtime(int(os.environ.get("SOURCE_DATE_EPOCH")
                                                    or time.time())))
    with tempfile.TemporaryDirectory(prefix="iemod-flatpak-") as work:
        source = prepare(os.path.abspath(args.zip), work, version(), day)
        build(source, work, out)
    check(out)
    sys.stdout.write(f"{out} ({os.path.getsize(out):,} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
