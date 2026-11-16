"""
The wizard's Linux zip as an AppImage (ADR-0060): the AppDir holds the zip's
folder unchanged, with AppRun, a valid desktop entry and an icon; the tools
it is packed with are refused unless their sha256 is the pinned one.
"""
import hashlib
import importlib.util
import os
import shutil
import stat
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


@pytest.fixture(autouse=True)
def lgpl_text(tmp_path, monkeypatch):
    """The LGPL-2.1 text the runtime's libfuse ships with, wherever the
    test runs (a build reads /usr/share/common-licenses)."""
    path = tmp_path / "LGPL-2.1"
    path.write_text("GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1, February 1999\n")
    monkeypatch.setattr(appimage, "LGPL_21", str(path))
    defaults = list(appimage.app_dir.__defaults__)
    defaults[-1] = str(path)
    monkeypatch.setattr(appimage.app_dir, "__defaults__", tuple(defaults))
    return path


def a_zip(tmp_path, with_program=True):
    path = tmp_path / f"{NAME}-linux-x86_64.zip"
    with zipfile.ZipFile(path, "w") as zf:
        if with_program:
            info = zipfile.ZipInfo(f"{NAME}/{NAME}")
            # a regular file's full mode, as pack() writes it (ZipInfo.from_file):
            # macOS's ditto, which unpack() uses there, ignores a bare 0o755
            info.external_attr = (stat.S_IFREG | 0o755) << 16
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
    if sys.platform != "win32":               # no execute bit to keep there
        assert os.stat(os.path.join(root, "AppRun")).st_mode & 0o111 == 0o111
    assert os.readlink(os.path.join(root, ".DirIcon")) == f"{NAME}.svg"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="AppRun is a POSIX shell script; the AppImage is Linux-only")
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
    if sys.platform != "win32":
        assert os.stat(path).st_mode & 0o777 == 0o700     # the build's own user only


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


def test_apprun_is_committed_executable():
    """copy2 keeps the mode it has in the repository: 100755, not set at
    build time with a constant (CodeQL, review of #131)."""
    done = subprocess.run(["git", "ls-files", "-s", "packaging/appimage/AppRun"],
                          cwd=os.path.join(HERE, os.pardir), capture_output=True, text=True,
                          check=False)
    if done.returncode != 0 or not done.stdout:
        pytest.skip("not a git checkout")
    assert done.stdout.split()[0] == "100755"


def test_the_runtimes_lgpl_text_ships_and_its_absence_stops_the_build(tmp_path):
    """Review of #131: libfuse, in the runtime, is LGPL-2.1; its text goes in."""
    root = appimage.app_dir(a_zip(tmp_path), str(tmp_path / "work"))
    text = os.path.join(root, "usr", "lib", NAME, "licenses", "appimage-runtime", "LGPL-2.1")
    with open(text, encoding="utf-8") as fh:
        assert "LESSER GENERAL PUBLIC LICENSE" in fh.read()
    (tmp_path / "again").mkdir()
    with pytest.raises(SystemExit, match="LGPL-2.1"):
        appimage.app_dir(a_zip(tmp_path / "again"), str(tmp_path / "work2"),
                         lgpl=str(tmp_path / "missing"))


def test_the_runtime_notice_names_every_component():
    for part in ("MIT", "musl", "libfuse", "LGPL-2.1", "squashfuse", "zstd", "zlib",
                 "licenses/appimage-runtime/LGPL-2.1", appimage.RUNTIME_TAG):
        assert part in appimage.RUNTIME_NOTICE


def test_a_packed_programs_mode_survives_this_systems_unpack(tmp_path):
    """Review of #131: the real path, not the fixture's - pack() a folder with
    an executable and unpack() it the way this system does (ditto on macOS,
    zipfile elsewhere); the program must still be executable."""
    folder = tmp_path / NAME
    folder.mkdir()
    program = folder / NAME
    program.write_text("#!/bin/sh\necho ok\n")
    os.chmod(program, 0o700)
    path = appimage.shared.pack(str(folder), str(tmp_path / "dist"))
    appimage.shared.unpack(path, str(tmp_path / "out"))
    if sys.platform != "win32":
        assert os.stat(tmp_path / "out" / NAME / NAME).st_mode & 0o100
