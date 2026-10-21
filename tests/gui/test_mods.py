"""
Phase 2, mod selection, driven like a player drives it (M3, GUI-AUDIT item 16).
The catalogue comes from a fixed loader - the page's loader is injected - so
the tests need no network and no community data.
"""
import json

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch_gui.pages.mods import ModsPage  # noqa: E402
from iemod_fetch_gui.window import MainWindow  # noqa: E402
from test_project import bg2ee, bgee  # noqa: E402

TP2 = "bg1ub/setup-bg1ub.tp2"


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
    widget = ModsPage(str(folder), load=lambda game, project: json.loads(json.dumps(mods)))
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    return widget


def check(widget, key, on=True):
    widget.items[key].setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def test_the_catalogue_loads_off_the_window_thread_with_its_categories(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    assert widget.tree.topLevelItemCount() == 2
    assert [widget.categories.item(i).text() for i in range(widget.categories.count())] == [
        "All categories (2)", "Quests (1)", "Tweaks (1)"]
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
    widget = ModsPage(str(tmp_path), load=broken)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    assert "could not be loaded: no network" in widget.status.text()


def test_the_wizard_goes_from_folders_to_mods_and_saves_both(qtbot, tmp_path):
    project = tmp_path / "project"
    main = MainWindow(str(project), load=lambda game, proj: json.loads(json.dumps(MODS)))
    qtbot.addWidget(main)
    main.game.bgee.edit.setText(bgee(tmp_path))
    main.game.bg2ee.edit.setText(bg2ee(tmp_path))
    main.game.check()
    with qtbot.waitSignal(main.mods.loaded, timeout=5000):
        qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 1 and not main.next.isEnabled()
    check(main.mods, (TP2, 0))
    assert main.next.isEnabled()
    qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 2 and (project / api.SELECTION_FILE).is_file()


def test_closing_the_page_while_the_list_loads_does_not_crash(qtbot, tmp_path):
    """A loader still on the network when the window closes: Qt aborts if a
    running QThread is destroyed, so the thread outlives the page."""
    import threading

    from iemod_fetch_gui.pages.mods import wait_for_loaders
    release = threading.Event()

    def slow(game, project):
        release.wait(5)
        return []
    widget = ModsPage(str(tmp_path), load=slow)
    widget.start("EET")
    widget.close()
    widget.deleteLater()
    qtbot.wait(50)                     # the page is gone; its thread is not
    release.set()
    wait_for_loaders(5000)
