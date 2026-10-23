"""
Presets in phase 2 (M3, GUI-AUDIT item 19), driven like a player drives them:
a choice saved to a file and loaded back, and a WeiDU.log loaded as a choice.
The file dialogs are answered by the test.
"""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from iemod_fetch import api  # noqa: E402

from .test_conflicts import NEED, TW, UB, choose, page  # noqa: E402


def answer(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def test_a_saved_preset_loads_back_into_the_tree(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 100))
    preset = tmp_path / "my build"
    answer(monkeypatch, preset)
    widget.save_preset.click()
    assert (tmp_path / "my build.json").is_file()       # the extension is added
    assert "Preset saved" in widget.status.text()
    choose(qtbot, widget, (UB, 10), (TW, 100), on=False)
    assert widget.chosen() == []
    answer(monkeypatch, tmp_path / "my build.json")
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.load_preset.click()
    assert sorted(widget.chosen()) == sorted([(UB, 10), (TW, 100)])
    assert shown == []                                   # nothing to report


def test_a_weidu_log_chooses_what_it_lists_and_names_what_it_cannot(qtbot, tmp_path,
                                                                    monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    log = tmp_path / "WeiDU.log"
    log.write_text("// Log of Currently Installed WeiDU Mods\n"
                   "~BG1UB\\SETUP-BG1UB.TP2~ #0 #10 // Restored\n"
                   "~NEEDED\\SETUP-NEEDED.TP2~ #0 #0 // Needed\n"
                   "~ghost\\setup-ghost.tp2~ #0 #1 // not in the list\n")
    answer(monkeypatch, log)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.load_preset.click()
    assert sorted(widget.chosen()) == sorted([(UB, 10), (NEED, 0)])
    assert len(shown) == 1 and "ghost/setup-ghost.tp2 #1" in shown[0]


def test_a_file_that_is_no_preset_changes_nothing(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10))
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    answer(monkeypatch, bad)
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: errors.append(a[1]))
    widget.load_preset.click()
    assert errors == ["Cannot load the preset"]
    assert widget.chosen() == [(UB, 10)]


def test_a_cancelled_dialog_does_nothing(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10))
    answer(monkeypatch, "")
    widget.load_preset.click()
    widget.save_preset.click()
    assert widget.chosen() == [(UB, 10)]
    assert not list(tmp_path.glob("*.json")) or \
        {p.name for p in tmp_path.glob("*.json")} <= {api.SELECTION_FILE,
                                                      api.DECISIONS_FILE}
