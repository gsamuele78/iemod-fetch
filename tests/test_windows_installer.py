"""
The wizard's Windows zip as a per-user installer (ADR-0061): the Inno Setup
script installs for this user only and removes nothing it did not install;
Inno Setup is refused unless its sha256 is the pinned one; the check the
build runs fails when the installed program does not start or when the
uninstaller takes the player's data with it.

The compiler and the installer are Windows programs: CI builds and tries the
real one on windows-latest. Here, on any system, the script, the command
lines and the check's logic, with the installer played by a fake.
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
SPEC = importlib.util.spec_from_file_location(
    "windows_installer", os.path.join(PACKAGING, "windows_installer.py"))
assert SPEC and SPEC.loader
wi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wi)

NAME = wi.NAME


def script() -> str:
    with open(wi.SCRIPT, encoding="utf-8") as fh:
        return fh.read()


def setup_section() -> dict:
    lines, inside = {}, False
    for line in script().splitlines():
        line = line.strip()
        if line.startswith("["):
            inside = line == "[Setup]"
            continue
        if inside and "=" in line and not line.startswith(";"):
            key, value = line.split("=", 1)
            lines[key] = value
    return lines


def test_it_installs_for_this_user_without_an_administrator():
    setup = setup_section()
    assert setup["PrivilegesRequired"] == "lowest"
    assert "PrivilegesRequiredOverridesAllowed" not in setup     # no switch to all users
    assert setup["DefaultDirName"] == r"{autopf}\iemod-fetch-gui"
    assert os.path.join("Programs", NAME) == wi.INSTALL_DIR   # {autopf}, per user


def test_its_identity_is_fixed():
    # the AppId is how Windows finds the installed version to upgrade or
    # remove: changing it would install a second copy beside the first
    assert setup_section()["AppId"] == "{{483B2769-37EB-4CC9-B7A8-410A2C01BCD1}"
    assert setup_section()["ArchitecturesAllowed"] == "x64compatible"


def test_the_uninstaller_removes_only_what_it_installed():
    lines = [line.strip() for line in script().splitlines()
             if not line.lstrip().startswith(";")]
    sections = {line for line in lines if line.startswith("[")}
    assert sections == {"[Setup]", "[Tasks]", "[Files]", "[Icons]", "[Run]"}
    files = [line for line in lines if line.startswith("Source:")]
    assert files == [('Source: "{#SourceDir}\\*"; DestDir: "{app}"; '
                      "Flags: ignoreversion recursesubdirs createallsubdirs")]


def test_the_licence_is_shown_and_installed():
    assert setup_section()["LicenseFile"] == r"{#SourceDir}\LICENSE"
    # the whole folder is installed: LICENSE, NOTICE-*.txt and licenses\ with it


def test_the_installer_starts_the_program_only_when_a_player_watches():
    run = [line for line in script().splitlines() if line.startswith("Filename:")]
    assert len(run) == 1 and "postinstall" in run[0] and "skipifsilent" in run[0]


def test_the_version_is_the_packages():
    from iemod_fetch import __version__
    assert wi.version() == __version__


def test_the_pin_is_https_and_sha256():
    url, digest = wi.INNO
    assert url.startswith("https://github.com/jrsoftware/issrc/releases/download/")
    assert len(digest) == 64 and int(digest, 16) >= 0


def test_a_download_with_another_digest_is_refused(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"not the pinned setup"
    monkeypatch.setattr(wi.urllib.request, "urlopen", lambda *a, **k: Response())
    with pytest.raises(SystemExit, match="not the pinned"):
        wi.fetch("https://example.org/setup.exe", "0" * 64, str(tmp_path / "setup.exe"))
    assert not (tmp_path / "setup.exe").exists()
    good = hashlib.sha256(b"not the pinned setup").hexdigest()
    assert os.path.isfile(wi.fetch("https://example.org/setup.exe", good,
                                   str(tmp_path / "setup.exe")))


def test_inno_setup_is_installed_silently_for_this_build_only():
    args = wi.inno_install_args("innosetup.exe", r"C:\work\inno")
    assert args[0] == "innosetup.exe"
    for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                 "/PORTABLE=1", r"/DIR=C:\work\inno"):
        assert flag in args


def test_the_compiler_gets_every_define_the_script_needs():
    args = wi.compile_args("ISCC.exe", r"C:\w\zip\iemod-fetch-gui", r"C:\dist",
                           "iemod-fetch-gui-windows-x86_64-setup", "4.1.0")
    assert args[-1] == wi.SCRIPT
    defined = {a[2:].split("=", 1)[0] for a in args if a.startswith("/D")}
    used = set()
    for line in script().splitlines():
        if not line.lstrip().startswith(";"):
            used.update(part.split("}", 1)[0] for part in line.split("{#")[1:])
    assert used <= defined | {"AppVersion"}, used - defined
    assert defined == {"AppVersion", "SourceDir", "OutputDir", "OutputName"}


def windows_zip(tmp_path, *, without=()):
    path = tmp_path / f"{NAME}-windows-x86_64.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name in (f"{NAME}.exe", "LICENSE", "licenses/Python-LICENSE.txt"):
            if name.split("/")[0] not in without:
                zf.writestr(f"{NAME}/{name}", "x")
    return str(path)


def test_the_zips_folder_is_the_source(tmp_path):
    folder = wi.source_dir(windows_zip(tmp_path), str(tmp_path / "work"))
    assert sorted(os.listdir(folder)) == ["LICENSE", f"{NAME}.exe", "licenses"]


@pytest.mark.parametrize("missing", [f"{NAME}.exe", "LICENSE", "licenses"])
def test_a_zip_without_the_program_or_its_licences_stops_the_build(tmp_path, missing):
    with pytest.raises(SystemExit, match=missing):
        wi.source_dir(windows_zip(tmp_path, without=(missing,)), str(tmp_path / "work"))


class FakeWindows:
    """setup.exe, the installed program and unins000.exe, as subprocess.run
    sees them; `uninstall` says what the uninstaller removes."""

    def __init__(self, app, *, starts=True, uninstall=None):
        self.app, self.starts, self.calls = app, starts, []
        self.uninstall = uninstall or (lambda: shutil.rmtree(app))

    def __call__(self, args, **kwargs):
        self.calls.append(os.path.basename(args[0]))
        if args[0].endswith("setup.exe"):
            os.makedirs(os.path.join(self.app, "licenses"))
            for name in (f"{NAME}.exe", "LICENSE", "unins000.exe"):
                open(os.path.join(self.app, name), "w").close()
            return subprocess.CompletedProcess(args, 0)
        if args[0].endswith(f"{NAME}.exe"):
            assert kwargs["env"]["QT_QPA_PLATFORM"] == "offscreen"
            return subprocess.CompletedProcess(args, 0 if self.starts else 1,
                                               "ok\n" if self.starts else "", "")
        assert args[0].endswith("unins000.exe")
        self.uninstall()
        return subprocess.CompletedProcess(args, 0)


@pytest.fixture
def local(tmp_path, monkeypatch):
    path = tmp_path / "Local"
    path.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(path))
    monkeypatch.delenv("IEMOD_DATA_DIR", raising=False)
    return path


def test_the_check_installs_starts_and_uninstalls(tmp_path, local, monkeypatch):
    app = str(local / "Programs" / NAME)
    fake = FakeWindows(app)
    monkeypatch.setattr(wi.subprocess, "run", fake)
    work = tmp_path / "work"
    work.mkdir()
    wi.check(str(tmp_path / "setup.exe"), str(work))
    assert fake.calls == ["setup.exe", f"{NAME}.exe", "unins000.exe"]
    assert not os.path.exists(app)
    # the markers it left are its own to remove; the data folder stays
    assert os.listdir(local / "iemod-fetch" / "data") == []


def test_the_check_fails_when_the_installed_program_does_not_start(tmp_path, local,
                                                                     monkeypatch):
    monkeypatch.setattr(wi.subprocess, "run",
                        FakeWindows(str(local / "Programs" / NAME), starts=False))
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(SystemExit, match="does not start"):
        wi.check(str(tmp_path / "setup.exe"), str(work))


def test_the_check_fails_when_the_uninstaller_takes_the_players_data(tmp_path, local,
                                                                      monkeypatch):
    app = str(local / "Programs" / NAME)

    def too_much():
        shutil.rmtree(app)
        shutil.rmtree(local / "iemod-fetch")
    monkeypatch.setattr(wi.subprocess, "run", FakeWindows(app, uninstall=too_much))
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(SystemExit, match="removed what the player made"):
        wi.check(str(tmp_path / "setup.exe"), str(work))


def test_the_check_fails_when_the_uninstaller_leaves_the_program(tmp_path, local,
                                                                 monkeypatch):
    monkeypatch.setattr(wi.subprocess, "run",
                        FakeWindows(str(local / "Programs" / NAME), uninstall=lambda: None))
    monkeypatch.setattr(wi.time, "sleep", lambda s: None)
    monkeypatch.setattr(wi.time, "monotonic", iter(range(0, 10_000, 100)).__next__)
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(SystemExit, match="left .* behind"):
        wi.check(str(tmp_path / "setup.exe"), str(work))


def test_the_check_refuses_to_install_over_an_existing_copy(tmp_path, local, monkeypatch):
    (local / "Programs" / NAME).mkdir(parents=True)
    monkeypatch.setattr(wi.subprocess, "run", FakeWindows(str(local / "Programs" / NAME)))
    with pytest.raises(SystemExit, match="exists already"):
        wi.check(str(tmp_path / "setup.exe"), str(tmp_path))


def test_it_is_built_on_windows_only(tmp_path, monkeypatch):
    monkeypatch.setattr(wi.sys, "platform", "linux")
    with pytest.raises(SystemExit, match="built on Windows"):
        wi.main([windows_zip(tmp_path), "--dist", str(tmp_path / "dist")])
