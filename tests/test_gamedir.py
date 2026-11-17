"""
Game folders, verified before anything is planned onto them (ADR-0026).

The game is identified exactly as WeiDU's GAME_IS does it (WeiDU src/tppe.ml):
`oh1000.are` is BG:EE, `oh6000.are` BG2:EE, `eet.flag` EET - each looked up in
override/ and in chitin.key. EET's own requirements come from its readme: a
clean BG2:EE, and BG:EE with Siege of Dragonspear (`movies/sodcin05.wbm`), which
on GOG/Steam is a DLC archive DlcMerger must merge first.
"""
import struct

import pytest

from iemod_fetch import gamedir
from iemod_fetch.gamedir import identify, key_resources, verify_eet

ARE, TWODA = 0x3F2, 0x3F4


def chitin(resources):
    """A real KEY V1 file: no BIFs, the given (resref, type) entries."""
    header = b"KEY V1  " + struct.pack("<IIII", 0, len(resources), 24, 24)
    body = b"".join(name.encode().ljust(8, b"\0") + struct.pack("<HI", kind, 0)
                    for name, kind in resources)
    return header + body


def game(tmp_path, name, resources=(), override=(), files=()):
    root = tmp_path / name
    (root / "override").mkdir(parents=True)
    (root / "chitin.key").write_bytes(chitin(list(resources)))
    for item in override:
        (root / "override" / item).write_bytes(b"")
    for item in files:
        path = root / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return str(root)


def test_key_resources(tmp_path):
    root = game(tmp_path, "g", resources=[("OH6000", ARE), ("CAMPAIGN", TWODA)])
    assert key_resources(root) == {("oh6000", ARE), ("campaign", TWODA)}


@pytest.mark.parametrize("resources,override,expected", [
    ([("OH1000", ARE)], (), "BGEE"),
    ([("OH1000", ARE), ("OH6000", ARE)], (), "BG2EE"),   # BGEE needs NOT bg2ee
    ([("OH6000", ARE)], (), "BG2EE"),
    ([("OH6000", ARE)], ("EET.flag",), "EET"),
    ([], ("oh1000.are",), "BGEE"),                       # override counts, any case
    ([], (), None),
])
def test_the_game_is_identified_as_weidu_does(tmp_path, resources, override, expected):
    assert identify(game(tmp_path, "g", resources, override)) == expected


def test_a_folder_without_chitin_key_is_not_a_game(tmp_path):
    (tmp_path / "empty").mkdir()
    assert identify(str(tmp_path / "empty")) is None


def bgee(tmp_path, **extra):
    return game(tmp_path, "BGEE", [("OH1000", ARE)], **extra)


def bg2ee(tmp_path, **extra):
    return game(tmp_path, "BG2EE", [("OH6000", ARE)], **extra)


def test_a_clean_pair_with_merged_sod_passes(tmp_path):
    report = verify_eet(bgee(tmp_path, files=["movies/sodcin05.wbm"]), bg2ee(tmp_path),
                        plan_mods={"dlcmerger"})
    assert report.problems == []
    assert report.sod == "merged"


def test_sod_as_a_dlc_archive_needs_dlcmerger_in_the_plan(tmp_path):
    folder, other = bgee(tmp_path, files=["dlc/sod-dlc.zip"]), bg2ee(tmp_path)
    report = verify_eet(folder, other, plan_mods=set())
    assert report.sod == "dlc"
    assert any("DlcMerger" in p for p in report.problems)
    assert verify_eet(folder, other, plan_mods={"dlcmerger"}).problems == []


def test_no_sod_at_all_is_refused(tmp_path):
    report = verify_eet(bgee(tmp_path), bg2ee(tmp_path), plan_mods={"dlcmerger"})
    assert any("Siege of Dragonspear" in p for p in report.problems)


def test_the_folders_must_be_the_right_games(tmp_path):
    swapped = verify_eet(bg2ee(tmp_path), bgee(tmp_path, files=["movies/sodcin05.wbm"]),
                         plan_mods=set())
    assert any("is BG2EE, not BGEE" in p for p in swapped.problems)
    assert any("is BGEE, not BG2EE" in p for p in swapped.problems)


def test_an_eet_game_is_not_a_clean_bg2ee(tmp_path):
    done = game(tmp_path, "EETdone", [("OH6000", ARE)], override=["EET.flag"])
    report = verify_eet(bgee(tmp_path, files=["movies/sodcin05.wbm"]), done,
                        plan_mods=set())
    assert any("already EET" in p for p in report.problems)


def test_a_modded_bg2ee_is_not_clean(tmp_path):
    folder = bg2ee(tmp_path)
    with open(f"{folder}/WeiDU.log", "w") as fh:
        fh.write("~UB/SETUP-UB.TP2~ #0 #0 // Unfinished Business\n")
    report = verify_eet(bgee(tmp_path, files=["movies/sodcin05.wbm"]), folder,
                        plan_mods=set())
    assert any("clean" in p for p in report.problems)


def test_one_folder_cannot_be_both_games(tmp_path):
    folder = bgee(tmp_path, files=["movies/sodcin05.wbm"])
    report = verify_eet(folder, folder, plan_mods=set())
    assert any("same folder" in p for p in report.problems)


def test_the_report_names_what_was_not_checked(tmp_path):
    report = verify_eet(bgee(tmp_path, files=["movies/sodcin05.wbm"]), bg2ee(tmp_path),
                        plan_mods=set())
    assert any("patch" in note for note in report.notes)
    assert "GAME FOLDERS" in report.render()


# ------------------------------- a folder seen through a Flatpak's portal (ADR-0064)
def test_a_folder_through_the_document_portal_gets_the_override_command(monkeypatch):
    monkeypatch.setenv("FLATPAK_ID", "io.github.example.app")
    folder = "/run/user/1000/doc/ab12cd34/Baldur's Gate II Enhanced Edition"
    note = gamedir.portal_note("BG2EE_DIR", folder)
    assert note and "document portal" in note and "experimental" in note
    assert ("flatpak override --user --filesystem=<the game folder> "
            "io.github.example.app") in note


def test_the_portals_host_path_fills_the_command_when_it_is_given(monkeypatch):
    monkeypatch.setenv("FLATPAK_ID", "io.github.example.app")
    host = b"/home/me/.local/share/Steam/steamapps/common/Baldur's Gate II Enhanced Edition"
    monkeypatch.setattr(gamedir.os, "getxattr", lambda path, name: host + b"\0",
                        raising=False)
    note = gamedir.portal_note("BG2EE_DIR", "/run/user/1000/doc/ab12cd34/BG2EE")
    assert ("--filesystem='/home/me/.local/share/Steam/steamapps/common/Baldur'\"'\"'s "
            "Gate II Enhanced Edition' io.github.example.app") in note


def test_any_other_folder_gets_no_portal_note():
    for folder in (None, "", "/home/me/BG2EE", "/run/user/1000/BG2EE", "C:\\Games\\BG2EE"):
        assert gamedir.portal_note("BG2EE_DIR", folder) is None


def test_the_first_phase_check_says_it(tmp_path):
    report = gamedir.check_folders("BG2EE", None, "/run/user/1000/doc/ab12cd34/BG2EE")
    assert any("document portal" in note for note in report.notes)
    assert report.problems                     # the folder itself is still checked
    plain = gamedir.check_folders("BG2EE", None, str(tmp_path))
    assert not any("document portal" in note for note in plain.notes)
