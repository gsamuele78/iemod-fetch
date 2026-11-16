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
    """The two installers, the installed program, unins000.exe and the
    "Installed apps" entry, as the check sees them. `upgrade` is what the
    second install does to the first ("replace", or "beside" as a second
    copy would), `unregister` whether the uninstaller removes the entry,
    `uninstall` what it removes from disk."""

    def __init__(self, app, *, starts=True, uninstall=None, upgrade="replace",
                 unregister=True):
        self.app, self.starts, self.calls = app, starts, []
        self.upgrade, self.unregister, self.registered = upgrade, unregister, None
        self.uninstall = uninstall or (lambda: shutil.rmtree(app))

    def __call__(self, args, **kwargs):
        name = os.path.basename(args[0])
        self.calls.append(name)
        if name.endswith("setup.exe"):
            first = not os.path.exists(self.app)
            os.makedirs(os.path.join(self.app, "licenses", "inno-setup"), exist_ok=True)
            files = [f"{NAME}.exe", "LICENSE", "NOTICE-installer.txt",
                     os.path.join("licenses", "inno-setup", "license.txt"), "unins000.exe"]
            if not first and self.upgrade == "beside":
                files.append("unins001.exe")
            for each in files:
                open(os.path.join(self.app, each), "w").close()
            if first or self.upgrade == "replace":
                self.registered = wi.PREVIOUS if name.startswith("previous") else "9.9.9"
            return subprocess.CompletedProcess(args, 0)
        if name == f"{NAME}.exe":
            assert kwargs["env"]["QT_QPA_PLATFORM"] == "offscreen"
            return subprocess.CompletedProcess(args, 0 if self.starts else 1,
                                               "ok\n" if self.starts else "", "")
        assert name == "unins000.exe"
        self.uninstall()
        if self.unregister:
            self.registered = None
        return subprocess.CompletedProcess(args, 0)


@pytest.fixture
def local(tmp_path, monkeypatch):
    path = tmp_path / "Local"
    path.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(path))
    monkeypatch.delenv("IEMOD_DATA_DIR", raising=False)
    return path


def run_check(tmp_path, local, monkeypatch, **fake):
    windows = FakeWindows(str(local / "Programs" / NAME), **fake)
    monkeypatch.setattr(wi.subprocess, "run", windows)
    monkeypatch.setattr(wi, "registered_version", lambda: windows.registered)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    wi.check(str(tmp_path / "setup.exe"), str(work / "previous-setup.exe"), str(work),
             "9.9.9")
    return windows


def test_the_check_upgrades_starts_and_uninstalls(tmp_path, local, monkeypatch):
    windows = run_check(tmp_path, local, monkeypatch)
    assert windows.calls == ["previous-setup.exe", "setup.exe", f"{NAME}.exe",
                             "unins000.exe"]
    assert not os.path.exists(local / "Programs" / NAME) and windows.registered is None
    # the markers it left are its own to remove; the data folder stays
    assert os.listdir(local / "iemod-fetch" / "data") == []


def test_the_check_fails_when_the_installed_program_does_not_start(tmp_path, local,
                                                                     monkeypatch):
    with pytest.raises(SystemExit, match="does not start"):
        run_check(tmp_path, local, monkeypatch, starts=False)


def test_the_check_fails_when_an_upgrade_installs_beside_the_previous(tmp_path, local,
                                                                       monkeypatch):
    with pytest.raises(SystemExit, match="Installed apps lists '0.0.0'"):
        run_check(tmp_path, local, monkeypatch, upgrade="beside")


def test_the_check_fails_when_the_uninstaller_takes_the_players_data(tmp_path, local,
                                                                      monkeypatch):
    def too_much():
        shutil.rmtree(local / "Programs" / NAME)
        shutil.rmtree(local / "iemod-fetch")
    with pytest.raises(SystemExit, match="removed what the player made"):
        run_check(tmp_path, local, monkeypatch, uninstall=too_much)


def test_the_check_fails_when_the_uninstaller_leaves_the_program(tmp_path, local,
                                                                 monkeypatch):
    monkeypatch.setattr(wi.time, "sleep", lambda s: None)
    monkeypatch.setattr(wi.time, "monotonic", iter(range(0, 10_000, 100)).__next__)
    with pytest.raises(SystemExit, match="left .* behind"):
        run_check(tmp_path, local, monkeypatch, uninstall=lambda: None)


def test_the_check_fails_when_the_uninstaller_leaves_it_registered(tmp_path, local,
                                                                   monkeypatch):
    with pytest.raises(SystemExit, match="left the program in Installed apps"):
        run_check(tmp_path, local, monkeypatch, unregister=False)


def test_the_check_refuses_to_install_over_an_existing_copy(tmp_path, local, monkeypatch):
    (local / "Programs" / NAME).mkdir(parents=True)
    with pytest.raises(SystemExit, match="exists already"):
        run_check(tmp_path, local, monkeypatch)


def test_inno_setups_licence_and_a_notice_go_into_the_folder(tmp_path):
    inno = tmp_path / "inno"
    inno.mkdir()
    (inno / "license.txt").write_text("Inno Setup License\n==================\n")
    source = tmp_path / "src"
    source.mkdir()
    wi.add_inno_licence(str(source), str(inno / "ISCC.exe"))
    assert (source / "licenses" / "inno-setup" / "license.txt").read_text().startswith(
        "Inno Setup License")
    notice = (source / "NOTICE-installer.txt").read_text()
    assert "licenses/inno-setup/license.txt" in notice and "is-6_7_3" in notice
    assert "6.7.3" in notice and wi.INNO[0].split("/")[-2] == "is-6_7_3"


@pytest.mark.parametrize("text", [None, "something else"])
def test_a_missing_or_wrong_inno_licence_stops_the_build(tmp_path, text):
    if text is not None:
        (tmp_path / "license.txt").write_text(text)
    with pytest.raises(SystemExit, match="licence"):
        wi.add_inno_licence(str(tmp_path / "src"), str(tmp_path / "ISCC.exe"))


def test_the_registry_key_is_the_scripts_app_id():
    assert setup_section()["AppId"] == "{" + wi.APP_ID
    assert wi.UNINSTALL_KEY.endswith(wi.APP_ID + "_is1")


def test_it_is_built_on_windows_only(tmp_path, monkeypatch):
    monkeypatch.setattr(wi.sys, "platform", "linux")
    with pytest.raises(SystemExit, match="built on Windows"):
        wi.main([windows_zip(tmp_path), "--dist", str(tmp_path / "dist")])
