#!/usr/bin/env python3
"""
The wizard's Linux zip as an AppImage (ADR-0060): one file a player makes
executable and starts, with a desktop entry and an icon, nothing installed.

    python packaging/gui_bundle.py --dist gui-dist          # the zip, checked
    python packaging/appimage.py gui-dist/iemod-fetch-gui-linux-x86_64.zip --dist gui-dist

The AppImage holds the same PyInstaller folder as the zip, unchanged, under
usr/lib/: the same libraries, the same licence files, NOTICE-system-libraries
included. What a player's system must still give is what every AppImage
leaves to it - the graphics driver (libGL, libEGL), X11/xcb, fontconfig and
freetype (AppImage's excludelist) - and FUSE to mount it, or
--appimage-extract-and-run without.

appimagetool and the AppImage runtime are downloaded at pinned versions and
checked by sha256. The runtime becomes the first bytes of the AppImage: it is
MIT, with libfuse (LGPL-2.1), squashfuse (BSD) and zstd (BSD) linked in
statically; NOTICE-AppImage-runtime.txt says so and where its source is.

The AppImage is then started once, offscreen, with --check, as the zip is.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gui_bundle as shared  # noqa: E402

NAME = shared.NAME
# Pinned, with their sha256 (measured 2026-11-16). The runtime's only dated
# release; "continuous" moves and would not hold a digest.
APPIMAGETOOL = (
    ("https://github.com/AppImage/appimagetool/releases/download/1.9.0/"
     "appimagetool-x86_64.AppImage"),
    "46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1")
RUNTIME_TAG = "20251108"
RUNTIME = (
    (f"https://github.com/AppImage/type2-runtime/releases/download/{RUNTIME_TAG}/"
     "runtime-x86_64"),
    "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d")
RUNTIME_NOTICE = f"""The first part of this AppImage, the program that mounts it, is the AppImage
type2-runtime ({RUNTIME_TAG}), under the MIT License, with these libraries linked
in statically: libfuse (GNU Lesser General Public License v2.1, LGPL-2.1), squashfuse
(BSD-2-Clause) and zstd (BSD-3-Clause).

Its source, and the exact sources it was built from:
  https://github.com/AppImage/type2-runtime/tree/{RUNTIME_TAG}
  https://github.com/AppImage/type2-runtime/releases/tag/{RUNTIME_TAG}
The rest of the AppImage is iemod-fetch-gui's folder, with its own licences
and notices (LICENSE, NOTICE-*.txt, licenses/).
"""


def fetch(url: str, digest: str, path: str) -> str:
    """`url` saved at `path`, refused unless its sha256 is `digest`."""
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (pinned https)
        data = response.read()
    found = hashlib.sha256(data).hexdigest()
    if found != digest:
        raise SystemExit(f"build aborted: {url} has sha256 {found}, not the pinned {digest}")
    with open(path, "wb") as fh:
        fh.write(data)
    os.chmod(path, 0o755)                   # noqa: S103 (a program, run here)
    return path


def app_dir(zip_path: str, work: str) -> str:
    """The AppDir: AppRun, the desktop entry, the icon, and the zip's folder
    unpacked as it is (links kept) under usr/lib/."""
    root = os.path.join(work, f"{NAME}.AppDir")
    lib = os.path.join(root, "usr", "lib")
    os.makedirs(lib)
    shared.unpack(zip_path, lib)
    if not os.path.isfile(os.path.join(lib, NAME, NAME)):
        raise SystemExit(f"build aborted: {zip_path} holds no {NAME}/{NAME}")
    source = os.path.join(HERE, "appimage")
    for name in ("AppRun", f"{NAME}.desktop", f"{NAME}.svg"):
        shutil.copy2(os.path.join(source, name), os.path.join(root, name))
    os.chmod(os.path.join(root, "AppRun"), 0o755)  # noqa: S103 (AppImage's entry point)
    os.symlink(f"{NAME}.svg", os.path.join(root, ".DirIcon"))
    with open(os.path.join(lib, NAME, "NOTICE-AppImage-runtime.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(RUNTIME_NOTICE)
    return root


def build(root: str, work: str, out: str) -> str:
    tool = fetch(*APPIMAGETOOL, os.path.join(work, "appimagetool"))
    runtime = fetch(*RUNTIME, os.path.join(work, "runtime"))
    # no FUSE needed to run appimagetool itself (CI containers have none)
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    subprocess.run([tool, "--no-appstream", "--runtime-file", runtime, root, out],
                   check=True, env=env, cwd=work)
    return out


def check(appimage: str, work: str) -> None:
    """Start it once, offscreen, without FUSE, as a player's --check would."""
    project = os.path.join(work, "project")
    os.makedirs(project, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", APPIMAGE_EXTRACT_AND_RUN="1")
    done = subprocess.run([appimage, "--check", "--project", project], env=env, cwd=work,
                          capture_output=True, text=True, timeout=180, check=False)
    if done.returncode != 0 or "ok" not in done.stdout:
        raise SystemExit(f"the AppImage does not start (exit {done.returncode}):\n"
                         f"{done.stdout}\n{done.stderr}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("zip", help="the wizard's Linux zip, as gui_bundle.py made it")
    parser.add_argument("--dist", default=os.path.join(shared.ROOT, "dist"))
    args = parser.parse_args(argv)
    os.makedirs(args.dist, exist_ok=True)
    out = os.path.join(os.path.abspath(args.dist), f"{NAME}-{shared.tag()}.AppImage")
    with tempfile.TemporaryDirectory(prefix="iemod-appimage-") as work:
        root = app_dir(os.path.abspath(args.zip), work)
        build(root, work, out)
        check(out, work)
    sys.stdout.write(f"{out} ({os.path.getsize(out):,} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
