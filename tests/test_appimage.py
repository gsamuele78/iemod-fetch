"""
The wizard's Linux zip as an AppImage (ADR-0060): the AppDir holds the zip's
folder unchanged, with AppRun, a valid desktop entry and an icon; the tools
it is packed with are refused unless their sha256 is the pinned one.
"""
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGING = os.path.join(HERE, os.pardir, "packaging")
sys.path.insert(0, PACKAGING)
SPEC = importlib.util.spec_from_file_location("appimage", os.path.join(PACKAGING, "appimage.py"))
assert SPEC and SPEC.loader
appimage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(appimage)

NAME = appimage.NAME


def a_zip(tmp_path, with_program=True):
    path = tmp_path / f"{NAME}-linux-x86_64.zip"
    with zipfile.ZipFile(path, "w") as zf:
        if with_program:
            info = zipfile.ZipInfo(f"{NAME}/{NAME}")
            info.external_attr = 0o755 << 16
            zf.writestr(info, "#!/bin/sh\necho ok\n")
        zf.writestr(f"{NAME}/NOTICE-system-libraries.txt", "libz.so.1 ...")
        zf.writestr(f"{NAME}/_internal/libz.so.1", "x")
    return str(path)


def test_the_appdir_holds_the_zips_folder_unchanged(tmp_path):
    root = appimage.app_dir(a_zip(tmp_path), str(tmp_path / "work"))
    names = set(os.listdir(root))
    assert {"AppRun", f"{NAME}.desktop", f"{NAME}.svg", ".DirIcon", "usr"} <= names
    folder = os.path.join(root, "usr", "lib", NAME)
    assert os.access(os.path.join(folder, NAME), os.X_OK)
    assert os.path.isfile(os.path.join(folder, "_internal", "libz.so.1"))
    assert os.path.isfile(os.path.join(folder, "NOTICE-system-libraries.txt"))
    with open(os.path.join(folder, "NOTICE-AppImage-runtime.txt"), encoding="utf-8") as fh:
        notice = fh.read()
    assert appimage.RUNTIME_TAG in notice and "LGPL" in notice and "MIT" in notice
    assert os.access(os.path.join(root, "AppRun"), os.X_OK)
    assert os.readlink(os.path.join(root, ".DirIcon")) == f"{NAME}.svg"


def test_apprun_starts_the_folders_program(tmp_path):
    root = appimage.app_dir(a_zip(tmp_path), str(tmp_path / "work"))
    done = subprocess.run([os.path.join(root, "AppRun")], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0 and done.stdout.strip() == "ok"


def test_a_zip_without_the_program_stops_the_build(tmp_path):
    with pytest.raises(SystemExit, match="holds no"):
        appimage.app_dir(a_zip(tmp_path, with_program=False), str(tmp_path / "work"))


def test_a_download_with_another_digest_is_refused(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"not the pinned tool"
    monkeypatch.setattr(appimage.urllib.request, "urlopen", lambda *a, **k: Response())
    with pytest.raises(SystemExit, match="not the pinned"):
        appimage.fetch("https://example.org/tool", "0" * 64, str(tmp_path / "tool"))
    assert not (tmp_path / "tool").exists()
    good = hashlib.sha256(b"not the pinned tool").hexdigest()
    path = appimage.fetch("https://example.org/tool", good, str(tmp_path / "tool"))
    assert os.access(path, os.X_OK)


def test_the_pins_are_https_and_sha256():
    for url, digest in (appimage.APPIMAGETOOL, appimage.RUNTIME):
        assert url.startswith("https://github.com/AppImage/") and "/continuous/" not in url
        assert len(digest) == 64 and int(digest, 16) >= 0


@pytest.mark.skipif(not shutil.which("desktop-file-validate"), reason="desktop-file-utils")
def test_the_desktop_entry_is_valid():
    path = os.path.join(PACKAGING, "appimage", f"{NAME}.desktop")
    done = subprocess.run(["desktop-file-validate", path], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0 and not done.stdout.strip(), done.stdout
