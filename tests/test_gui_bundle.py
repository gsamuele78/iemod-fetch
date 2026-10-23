"""
packaging/gui_bundle.py (GUI-AUDIT item 20, ADR-0040): the helpers that do not
need PyInstaller - the zip's name, its licence files and its bytes, which are
the same for the same folder.
"""
import importlib.util
import os
import stat
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "gui_bundle", os.path.join(ROOT, "packaging", "gui_bundle.py"))
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)

VERSIONS = {"qt": "6.12.0", "pyside6": "6.12.0", "pyinstaller": "6.22.3",
            "python": "3.12.3"}


def program(tmp_path):
    folder = tmp_path / "out" / bundle.NAME
    (folder / "_internal" / "PySide6").mkdir(parents=True)
    (folder / bundle.NAME).write_bytes(b"\x7fELF program")
    (folder / "_internal" / "PySide6" / "libQt6Core.so.6").write_bytes(b"qt")
    return folder


@pytest.mark.parametrize("system,machine,expected", [
    ("Linux", "x86_64", "linux-x86_64"), ("Windows", "AMD64", "windows-x86_64"),
    ("Darwin", "arm64", "macos-arm64"), ("Linux", "aarch64", "linux-arm64")])
def test_the_zip_is_named_for_its_system(monkeypatch, system, machine, expected):
    monkeypatch.setattr(bundle.platform, "system", lambda: system)
    monkeypatch.setattr(bundle.platform, "machine", lambda: machine)
    assert bundle.tag() == expected


def test_the_qt_notice_names_the_licence_versions_and_source():
    text = bundle.notice(VERSIONS)
    assert "LGPL-3.0-only" in text and "Qt 6.12.0" in text and "PySide6 6.12.0" in text
    assert "https://download.qt.io/official_releases/qt/" in text
    assert "licenses/LGPL-3.0-only.txt" in text and "licenses/GPL-3.0-only.txt" in text


def test_the_folder_carries_the_licences(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "versions", lambda: VERSIONS)
    folder = program(tmp_path)
    bundle.add_licences(str(folder))
    assert (folder / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert sorted(os.listdir(folder / "licenses")) == ["GPL-3.0-only.txt",
                                                       "LGPL-3.0-only.txt"]
    lgpl = (folder / "licenses" / "LGPL-3.0-only.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl and "Version 3" in lgpl
    assert "Qt 6.12.0" in (folder / "NOTICE-Qt.txt").read_text(encoding="utf-8")


def test_the_same_folder_zips_to_the_same_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "tag", lambda: "linux-x86_64")
    folder = program(tmp_path)
    first = bundle.pack(str(folder), str(tmp_path / "a"))
    os.utime(folder / bundle.NAME, (1_900_000_000, 1_900_000_000))
    second = bundle.pack(str(folder), str(tmp_path / "b"))
    with open(first, "rb") as a, open(second, "rb") as b:
        assert a.read() == b.read()
    assert os.path.basename(first) == "iemod-fetch-gui-linux-x86_64.zip"
    with zipfile.ZipFile(first) as zf:
        assert zf.namelist() == [f"{bundle.NAME}/{bundle.NAME}",
                                 f"{bundle.NAME}/_internal/PySide6/libQt6Core.so.6"]


def links(base):
    """Qt's framework links as a macOS .app holds them; skip where none can be made."""
    if os.name == "nt":             # Windows builds hold no links; its links take no '/'
        pytest.skip("links are a macOS and Linux matter")
    versions = base / "QtCore.framework" / "Versions"
    (versions / "A").mkdir(parents=True)
    (versions / "A" / "QtCore").write_bytes(b"qt")
    try:
        os.symlink("A", versions / "Current", target_is_directory=True)
        os.symlink("Versions/Current/QtCore", versions.parent / "QtCore")
    except OSError:                 # Windows without the privilege to make links
        pytest.skip("cannot make a symbolic link here")


def test_links_in_a_macos_app_stay_links(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "tag", lambda: "macos-arm64")
    app = tmp_path / "out" / f"{bundle.NAME}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / bundle.NAME).write_bytes(b"program")
    links(app / "Contents" / "Frameworks")
    path = bundle.pack(str(app), str(tmp_path / "dist"))
    with zipfile.ZipFile(path) as zf:
        entries = {i.filename: i for i in zf.infolist()}
        prefix = f"{bundle.NAME}.app/Contents/Frameworks/QtCore.framework/"
        for name, target in ((prefix + "Versions/Current", b"A"),
                             (prefix + "QtCore", b"Versions/Current/QtCore")):
            assert stat.S_ISLNK(entries[name].external_attr >> 16)
            assert zf.read(name) == target
        assert prefix + "Versions/Current/QtCore" not in entries     # not a copy


def test_linux_links_stay_links_and_unpack_as_links(tmp_path, monkeypatch):
    # Review of #42: following them doubled Qt in the zip (60 to 89 MB), and a
    # library replaced as NOTICE-Qt.txt says still loaded from its other copy
    monkeypatch.setattr(bundle, "tag", lambda: "linux-x86_64")
    monkeypatch.setattr(bundle.platform, "system", lambda: "Linux")
    folder = program(tmp_path)
    links(folder / "_internal")
    path = bundle.pack(str(folder), str(tmp_path / "dist"))
    with zipfile.ZipFile(path) as zf:
        prefix = f"{bundle.NAME}/_internal/QtCore.framework/"
        assert stat.S_ISLNK(zf.getinfo(prefix + "QtCore").external_attr >> 16)
    bundle.unpack(path, str(tmp_path / "unpacked"))
    unpacked = tmp_path / "unpacked" / bundle.NAME / "_internal" / "QtCore.framework"
    assert os.path.islink(unpacked / "QtCore")
    assert (unpacked / "QtCore").read_bytes() == b"qt"


@pytest.mark.skipif(os.name == "nt", reason="file modes are POSIX")
def test_the_unpacked_program_is_still_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "tag", lambda: "linux-x86_64")
    monkeypatch.setattr(bundle.platform, "system", lambda: "Linux")
    folder = program(tmp_path)
    os.chmod(folder / bundle.NAME, 0o700)
    path = bundle.pack(str(folder), str(tmp_path / "dist"))
    bundle.unpack(path, str(tmp_path / "unpacked"))
    unpacked = tmp_path / "unpacked" / bundle.NAME / bundle.NAME
    assert unpacked.read_bytes() == b"\x7fELF program"
    assert os.stat(unpacked).st_mode & 0o100
