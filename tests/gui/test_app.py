"""
The wizard's arguments (iemod_fetch_gui.app): the project folder is the
current one, but in a Flatpak, where the folder it was started from and its
home are not kept, a folder in the app's own data (review of #135).
"""
from iemod_fetch import gamelock
from iemod_fetch_gui.app import parse_args


def test_the_project_is_the_current_folder_outside_a_sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert parse_args([]).project == str(tmp_path)
    assert parse_args(["--project", "/elsewhere"]).project == "/elsewhere"


def test_in_a_flatpak_the_project_is_in_the_apps_data_not_the_current_folder(
        tmp_path, monkeypatch):
    info = tmp_path / ".flatpak-info"
    info.write_text("[Application]\n")
    monkeypatch.setattr(gamelock, "FLATPAK_INFO", str(info))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "var-app" / "data"))
    started = tmp_path / "started-here"
    started.mkdir()
    monkeypatch.chdir(started)
    project = parse_args([]).project
    assert project == str(tmp_path / "var-app" / "data" / "project") != str(started)
    assert (tmp_path / "var-app" / "data" / "project").is_dir()
    assert parse_args(["--project", "/chosen"]).project == "/chosen"   # still given


def test_in_a_flatpak_without_xdg_data_home_the_project_is_still_kept(tmp_path, monkeypatch):
    info = tmp_path / ".flatpak-info"
    info.write_text("[Application]\n")
    monkeypatch.setattr(gamelock, "FLATPAK_INFO", str(info))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("FLATPAK_ID", "io.github.example.app")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))     # Windows' expanduser reads this
    assert parse_args([]).project == str(tmp_path / ".var" / "app" / "io.github.example.app"
                                         / "data" / "project")
