"""
Phase 2, mod selection, driven like a player drives it (M3, GUI-AUDIT item 16).
The catalogue comes from a fixed loader - the page's loader is injected - so
the tests need no network and no community data.
"""
import json
import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch_gui.pages.mods import ModsPage  # noqa: E402
from iemod_fetch_gui.window import MainWindow  # noqa: E402
from test_project import bg2ee, bgee  # noqa: E402

TP2 = "bg1ub/setup-bg1ub.tp2"


def no_plan(*_args):
    return {"phases": [], "cycles": [], "violations": [], "planned": False, "custom": False}


def no_check(*_args):
    """No rules: these tests are about choosing (test_conflicts.py checks)."""
    return {"findings": [], "stale": [], "rules_checked": 0, "planned": False,
            "problem": None}


def component(number, name, exclusive="", subgroup="", requires=()):
    return {"number": number, "name": name, "subgroup": subgroup, "exclusive": exclusive,
            "groups": [], "requires": list(requires), "forced": False}


MODS = [
    {"key": "bg1ub", "name": "BG1 Unfinished Business", "games": ["BGEE", "EET"],
     "categories": ["Quests"], "status": [], "advisories": [], "version": "v17",
     "installed": "v16", "update_available": True, "latest": {"version": "v17"},
     "tp2s": [{"tp2": TP2, "origin": "krion64", "components": [
         component(0, "Restoration"),
         component(10, "classic", "g:7", "Portraits"),
         component(11, "new", "g:7", "Portraits"),
         component(20, "Needs the first", requires=[0])]}]},
    {"key": "unknown", "name": "A mod nobody describes", "games": ["EET"],
     "categories": ["Tweaks"], "status": [], "advisories": [], "tp2s": []},
]


def page(qtbot, folder, mods=MODS):
    widget = ModsPage(str(folder), load=lambda game, project: json.loads(json.dumps(mods)),
                      check=no_check)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    return widget


def check(widget, key, on=True):
    widget.items[key].setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def test_the_catalogue_loads_off_the_window_thread_with_its_categories(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    assert widget.tree.topLevelItemCount() == 2
    # A list from before item 26 has no kinds: its categories stand in.
    assert [widget.categories.item(i).text() for i in range(widget.categories.count())] == [
        "All kinds (2)", "Quests (1)", "Tweaks (1)"]
    assert not widget.is_complete()


def test_choosing_one_of_a_subcomponent_clears_the_others(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    check(widget, (TP2, 10))
    check(widget, (TP2, 11))
    assert widget.chosen() == [(TP2, 11)]


def test_a_component_brings_the_one_it_needs(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    check(widget, (TP2, 20))
    assert widget.chosen() == [(TP2, 0), (TP2, 20)] and widget.is_complete()


def test_a_mod_whose_components_are_unknown_cannot_be_chosen(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    unknown = widget.tree.topLevelItem(1)
    assert unknown.isDisabled() and "not known until it is downloaded" in unknown.toolTip(0)


def test_search_category_and_filters_hide_what_does_not_match(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    visible = lambda: [widget.tree.topLevelItem(i).text(0)  # noqa: E731
                       for i in range(widget.tree.topLevelItemCount())
                       if not widget.tree.topLevelItem(i).isHidden()]
    widget.search.setText("portraits")                 # a component's name finds its mod
    assert visible() == ["BG1 Unfinished Business"]
    widget.search.setText("")
    widget.categories.setCurrentRow(2)
    assert visible() == ["A mod nobody describes"]
    widget.categories.setCurrentRow(0)
    widget.filter.setCurrentText("Updates available")
    assert visible() == ["BG1 Unfinished Business"]
    widget.filter.setCurrentText("Chosen only")
    assert visible() == []
    check(widget, (TP2, 0))
    widget.apply_filter()
    assert visible() == ["BG1 Unfinished Business"]


def test_the_choice_is_saved_as_the_selection_the_cli_reads_and_comes_back(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    check(widget, (TP2, 10))
    path = widget.save()
    (install,) = api.load_selection(path).installs
    assert install.game == "EET"
    assert [(c.tp2, c.component, c.label) for c in install.components] == [(TP2, 10, "classic")]
    again = page(qtbot, tmp_path)
    assert again.chosen() == [(TP2, 10)]


def test_a_loader_that_fails_is_shown_not_raised(qtbot, tmp_path):
    def broken(game, project):
        raise OSError("no network")
    widget = ModsPage(str(tmp_path), load=broken, check=no_check)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    assert "could not be loaded: no network" in widget.status.text()


def test_a_list_that_failed_loads_when_the_game_is_chosen_again(qtbot, tmp_path):
    # Review of #41: after a failed switch the old game's tree stayed, so
    # choosing the game again found "a list" and loaded nothing, presets off
    offline = [True]

    def flaky(game, project):
        if game == "BGEE" and offline[0]:
            raise OSError("offline")
        return json.loads(json.dumps(MODS))
    widget = ModsPage(str(tmp_path), load=flaky, check=no_check)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("BGEE")
    assert "could not be loaded: offline" in widget.status.text()
    assert widget.tree.topLevelItemCount() == 0        # not EET's list
    offline[0] = False
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("BGEE")
    assert widget.tree.topLevelItemCount() == 2
    assert widget.load_preset.isEnabled() and widget.save_preset.isEnabled()


def test_the_wizard_goes_from_folders_to_mods_and_saves_both(qtbot, tmp_path):
    project = tmp_path / "project"
    planned = {"phases": [{"role": "WeiDU.log", "title": "EET", "units": [{
        "node": "n", "name": "bg1ub", "tp2": "setup-bg1ub.tp2", "key": "bg1ub", "part": 0,
        "split": False, "category": "", "components": [[TP2, 0, ""]],
        "constrained": False, "moved": False, "flagged": False}]}],
        "cycles": [], "violations": [], "planned": True, "custom": False}
    main = MainWindow(str(project), load=lambda game, proj: json.loads(json.dumps(MODS)),
                      check=no_check, plan=lambda *a: planned)
    qtbot.addWidget(main)
    main.game.bgee.edit.setText(bgee(tmp_path))
    main.game.bg2ee.edit.setText(bg2ee(tmp_path))
    main.game.check()
    with qtbot.waitSignal(main.mods.loaded, timeout=5000):
        qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 1 and not main.next.isEnabled()
    check(main.mods, (TP2, 0))
    assert main.next.isEnabled()
    with qtbot.waitSignal(main.order.planned, timeout=5000):
        qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 2 and (project / api.SELECTION_FILE).is_file()
    # once the order is planned, Next goes on (it stayed disabled: the page
    # said it was complete before its thread had ended)
    assert main.order.is_complete() and main.next.isEnabled()


def test_closing_the_page_while_the_list_loads_does_not_crash(qtbot, tmp_path):
    """A loader still on the network when the window closes: Qt aborts if a
    running QThread is destroyed, so the thread outlives the page."""
    import threading

    from iemod_fetch_gui.pages.mods import wait_for_loaders
    release = threading.Event()

    def slow(game, project):
        release.wait(5)
        return []
    widget = ModsPage(str(tmp_path), load=slow, check=no_check)
    widget.start("EET")
    widget.close()
    widget.deleteLater()
    qtbot.wait(50)                     # the page is gone; its thread is not
    release.set()
    wait_for_loaders(5000)


# ------------------------------------------- selection by kind (item 26)
KINDS = [
    dict(MODS[1], key="turnabout", name="Turnabout", kinds=["gameplay", "quest"],
         kinds_by_source={"lcc-docs": ["quest"], "BWS-NG": ["gameplay"]},
         kind_disagreement=True),
    dict(MODS[1], key="ascension", name="Ascension", kinds=["quest"],
         kinds_by_source={"lcc-docs": ["quest"], "BWS-NG": ["quest"]},
         kind_disagreement=False, install_category="QUEST MODS BG2", tags=["tob"]),
]


def test_the_list_is_chosen_by_kind_and_a_disagreement_is_shown(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, KINDS)
    visible = lambda: [widget.tree.topLevelItem(i).text(0)  # noqa: E731
                       for i in range(widget.tree.topLevelItemCount())
                       if not widget.tree.topLevelItem(i).isHidden()]
    assert [widget.categories.item(i).text() for i in range(widget.categories.count())] == [
        "All kinds (2)", "gameplay (1)", "quest (2)"]
    turnabout, ascension = (widget.tree.topLevelItem(i) for i in range(2))
    assert ascension.text(3) == "quest"
    assert turnabout.text(3).startswith("\u26a0") and "gameplay, quest" in turnabout.text(3)
    assert turnabout.toolTip(3) == "lcc-docs: quest; BWS-NG: gameplay"
    widget.categories.setCurrentRow(1)
    assert visible() == ["Turnabout"]
    widget.categories.setCurrentRow(0)
    widget.filter.setCurrentText("Kinds disagree")
    assert visible() == ["Turnabout"]

    widget._show(turnabout)               # disabled rows: nothing to choose yet
    text = widget.details.toPlainText()
    assert "lcc-docs: quest; BWS-NG: gameplay" in text
    assert "disagree" in text
    widget._show(ascension)
    assert "krion64 install category: QUEST MODS BG2 (tags: tob)" in widget.details.toPlainText()


# --------------------------------------------- review follow-ups (#32)
EXCLUSIVE_NEEDED = [{
    "key": "fp", "name": "Faiths and Powers", "games": ["EET"], "categories": ["Kits"],
    "status": [], "advisories": [], "tp2s": [{"tp2": "fp/fp.tp2", "origin": "krion64",
                                              "refused": None, "components": [
        component(10, "kit a", "g:paladin"), component(11, "kit b", "g:paladin"),
        component(30, "needs kit a", requires=[10]),
        component(30, "listed twice")]}]}]


def test_a_needed_component_clears_the_rest_of_its_subcomponent(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, EXCLUSIVE_NEEDED)
    check(widget, ("fp/fp.tp2", 11))
    check(widget, ("fp/fp.tp2", 30))
    assert widget.chosen() == [("fp/fp.tp2", 10), ("fp/fp.tp2", 30)]


def test_a_component_listed_twice_has_one_box_that_works(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, EXCLUSIVE_NEEDED)
    rows = [widget.tree.topLevelItem(0).child(i).text(0)
            for i in range(widget.tree.topLevelItem(0).childCount())]
    assert sum(row.startswith("#30") for row in rows) == 1


def test_a_refused_tp2_cannot_be_chosen_and_says_why(qtbot, tmp_path):
    refused = [dict(EXCLUSIVE_NEEDED[0], tp2s=[dict(EXCLUSIVE_NEEDED[0]["tp2s"][0],
                                                    refused="tp2 path is unsafe")])]
    widget = page(qtbot, tmp_path, refused)
    assert widget.tree.topLevelItem(0).isDisabled()


def test_changing_the_game_while_the_list_loads_loads_the_new_game(qtbot, tmp_path):
    import threading
    gate = threading.Event()
    asked = []

    def load(game, project):
        asked.append(game)
        if game == "EET":
            gate.wait(5)
        return [dict(MODS[0], name=f"for {game}")]
    widget = ModsPage(str(tmp_path), load=load, check=no_check)
    qtbot.addWidget(widget)
    widget.start("EET")
    widget.start("BGEE")                       # Back, another game, Next
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        gate.set()
    assert asked == ["EET", "BGEE"] and widget.game == "BGEE"
    assert widget.tree.topLevelItem(0).text(0) == "for BGEE"


def test_catalogue_text_is_shown_as_text_not_html(qtbot, tmp_path):
    hostile = [dict(MODS[0], name="<a href='file:///etc/passwd'>click</a>",
                    advisories=["<img src='file:///x'>"])]
    widget = page(qtbot, tmp_path, hostile)
    widget._show(widget.tree.topLevelItem(0))
    assert "&lt;a href" in widget.details.toHtml() and "<img" not in widget.details.toHtml()


def test_a_selection_for_another_game_is_not_carried_over(qtbot, tmp_path):
    api.save_selection(str(tmp_path), "BGEE", [(TP2, 0)])
    widget = page(qtbot, tmp_path)                     # loads for EET
    assert widget.chosen() == []


def test_an_eet_build_saved_in_two_phases_is_chosen_again(qtbot, tmp_path):
    # bg1ub belongs to the BG:EE phase (krion64): selection.json holds it in a
    # BGEE install beside the EET one, and the EET page must find it there.
    krion = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "krion")
    api.save_selection(str(tmp_path), "EET", [(TP2, 0), ("eet/EET.tp2", 0)],
                       order_catalogue=krion)
    saved = api.load_selection(str(tmp_path / api.SELECTION_FILE))
    assert [i.game for i in saved.installs] == ["BGEE", "EET"]
    widget = page(qtbot, tmp_path)
    assert widget.chosen() == [(TP2, 0)]
