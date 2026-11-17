"""
The wizard's Linux zip as a Flatpak (ADR-0064): the sandbox gets the
network, a window and the GPU and no folder of the player's; the runtime is
the pinned branch; the desktop entry, metainfo and icon all carry the one
app ID; the folder installed is the zip's, unchanged.

flatpak-builder needs Flathub and a user namespace: CI builds and starts
the real bundle (release.yml, job flatpak). Here, on any system, the
manifest and the files.
"""
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGING = os.path.join(HERE, os.pardir, "packaging")
sys.path.insert(0, PACKAGING)
SPEC = importlib.util.spec_from_file_location("flatpak", os.path.join(PACKAGING, "flatpak.py"))
assert SPEC and SPEC.loader
flatpak = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flatpak)

APP_ID, NAME = flatpak.APP_ID, flatpak.NAME
FILES = os.path.join(PACKAGING, "flatpak")


def test_the_sandbox_gets_the_network_a_window_and_the_gpu_and_nothing_else():
    assert sorted(flatpak.FINISH_ARGS) == sorted([
        "--share=network", "--socket=wayland", "--socket=fallback-x11", "--share=ipc",
        "--device=dri"])
    joined = " ".join(flatpak.FINISH_ARGS)
    # no folder of the player's: the portal chooses (ADR-0064); no way out of
    # the sandbox (ADR-0063)
    assert "--filesystem" not in joined and "--talk-name" not in joined
    assert "--device=all" not in joined and "--socket=x11" not in joined.split()


def test_the_manifest_is_the_pinned_runtime_and_the_zips_folder(tmp_path):
    data = flatpak.manifest(str(tmp_path))
    assert data["app-id"] == APP_ID and data["command"] == NAME
    assert (data["runtime"], data["runtime-version"], data["sdk"]) == (
        "org.freedesktop.Platform", "26.08", "org.freedesktop.Sdk")
    assert data["finish-args"] == flatpak.FINISH_ARGS
    (module,) = data["modules"]
    assert module["sources"] == [{"type": "dir", "path": str(tmp_path)}]
    # the zip's folder unchanged: not stripped (review of #135)
    assert module["build-options"] == {"strip": False, "no-debuginfo": True}
    commands = "\n".join(module["build-commands"])
    assert f"cp -a {NAME} /app/lib/" in commands
    assert f"ln -s ../lib/{NAME}/{NAME} /app/bin/{NAME}" in commands
    for kind in ("applications", "metainfo", "icons/hicolor/scalable/apps"):
        assert f"/app/share/{kind}/{APP_ID}." in commands


def test_the_app_id_is_one_constant_and_every_file_carries_it():
    assert sorted(os.listdir(FILES)) == sorted(
        [f"{APP_ID}.desktop", f"{APP_ID}.metainfo.xml", f"{APP_ID}.svg"])
    with open(os.path.join(FILES, f"{APP_ID}.desktop"), encoding="utf-8") as fh:
        entry = dict(line.strip().split("=", 1) for line in fh if "=" in line)
    # no %F: the wizard takes no file to open (argparse would exit 2)
    assert entry["Icon"] == APP_ID and entry["Exec"] == NAME
    root = ET.parse(os.path.join(FILES, f"{APP_ID}.metainfo.xml")).getroot()
    assert root.findtext("id") == APP_ID
    assert root.findtext("launchable") == f"{APP_ID}.desktop"
    assert root.findtext("project_license") == "MIT AND LGPL-3.0-only AND GPL-3.0-only"
    # one place in the code: the module's constant
    with open(os.path.join(PACKAGING, "flatpak.py"), encoding="utf-8") as fh:
        assert fh.read().count(APP_ID) == 1


def test_the_metainfo_says_it_is_experimental():
    root = ET.parse(os.path.join(FILES, f"{APP_ID}.metainfo.xml")).getroot()
    text = " ".join(p.text or "" for p in root.iter("p"))
    assert "experimental" in text


def test_the_release_is_added_to_the_metainfo():
    root = ET.fromstring(flatpak.metainfo("4.2.0", "2026-11-17"))
    (release,) = root.iter("release")
    assert release.attrib == {"version": "4.2.0", "date": "2026-11-17"}


def linux_zip(tmp_path, *, program=True):
    path = tmp_path / f"{NAME}-linux-x86_64.zip"
    with zipfile.ZipFile(path, "w") as zf:
        if program:
            info = zipfile.ZipInfo(f"{NAME}/{NAME}")
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            zf.writestr(info, "#!/bin/sh\n")
        zf.writestr(f"{NAME}/LICENSE", "MIT")
    return str(path)


def test_the_source_folder_is_the_zips_with_the_desktop_files(tmp_path):
    source = flatpak.prepare(linux_zip(tmp_path), str(tmp_path / "work"), "4.2.0",
                             "2026-11-17")
    assert sorted(os.listdir(source)) == sorted(
        [NAME, f"{APP_ID}.desktop", f"{APP_ID}.metainfo.xml", f"{APP_ID}.svg"])
    assert sorted(os.listdir(os.path.join(source, NAME))) == ["LICENSE", NAME]
    if sys.platform != "win32":
        assert os.access(os.path.join(source, NAME, NAME), os.X_OK)
    with open(os.path.join(source, f"{APP_ID}.metainfo.xml"), encoding="utf-8") as fh:
        assert 'version="4.2.0"' in fh.read()


def test_a_zip_without_the_program_stops_the_build(tmp_path):
    with pytest.raises(SystemExit, match=f"no {NAME}/{NAME}"):
        flatpak.prepare(linux_zip(tmp_path, program=False), str(tmp_path / "work"), "4.2.0",
                        "2026-11-17")


def test_the_check_runs_inside_the_sandbox_with_bsdtar_and_the_default_project():
    assert "/.flatpak-info" in flatpak.CHECK and "bsdtar" in flatpak.CHECK
    assert "QT_QPA_PLATFORM=offscreen" in flatpak.CHECK and "--check" in flatpak.CHECK
    # no --project: the default one, in the app's own data (review of #135)
    assert "--project" not in flatpak.CHECK
    assert '"$XDG_DATA_HOME" = "$HOME/.var/app/$FLATPAK_ID/data"' in flatpak.CHECK
    assert 'test -d "$XDG_DATA_HOME/project"' in flatpak.CHECK


def test_only_a_bundle_that_passed_its_check_reaches_dist(tmp_path, monkeypatch):
    monkeypatch.setattr(flatpak.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(flatpak, "prepare", lambda *a: str(tmp_path / "source"))

    def build(source, work, out):
        assert os.path.dirname(out) == work               # not in --dist
        with open(out, "wb") as fh:
            fh.write(b"bundle")
        return out
    monkeypatch.setattr(flatpak, "build", build)
    dist = tmp_path / "dist"

    def fails(bundle):
        raise SystemExit("the Flatpak does not start")
    monkeypatch.setattr(flatpak, "check", fails)
    with pytest.raises(SystemExit, match="does not start"):
        flatpak.main([linux_zip(tmp_path), "--dist", str(dist)])
    assert not list(dist.iterdir())                       # nothing to upload
    monkeypatch.setattr(flatpak, "check", lambda bundle: None)
    flatpak.main([linux_zip(tmp_path), "--dist", str(dist)])
    assert [p.name for p in dist.iterdir()] == [f"{NAME}-{flatpak.shared.tag()}.flatpak"]


@pytest.mark.skipif(not shutil.which("desktop-file-validate"), reason="desktop-file-utils")
def test_the_desktop_entry_is_valid():
    subprocess.run(["desktop-file-validate", os.path.join(FILES, f"{APP_ID}.desktop")],
                   check=True)


@pytest.mark.skipif(not shutil.which("appstreamcli"), reason="appstream")
def test_the_metainfo_is_valid(tmp_path):
    path = tmp_path / f"{APP_ID}.metainfo.xml"
    path.write_text(flatpak.metainfo("4.2.0", "2026-11-17"), encoding="utf-8")
    subprocess.run(["appstreamcli", "validate", "--no-net", "--explain", str(path)],
                   check=True)
