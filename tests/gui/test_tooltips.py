"""
Text that is not ours is shown as text (review of #123): catalogue text, a
mod's or a file's name, GitHub's version, a reason the player typed, an
error message. Qt renders a tooltip, an AutoText QLabel or a QMessageBox as
HTML when the text looks like HTML; each place listed here is driven with
markup and must show it as written.
"""
import ast
import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import Qt as GuiQt, QTextDocument  # noqa: E402

from iemod_fetch_gui import text as qtext  # noqa: E402

HOSTILE = '<a href="https://evil.example">x</a> <img src="https://evil.example/i.png"> <b>B</b>'
GUI = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "iemod_fetch_gui")


def shown(tip: str) -> str:
    """What a tooltip shows: Qt's own reading of it."""
    if not GuiQt.mightBeRichText(tip):
        return tip
    doc = QTextDocument()
    doc.setHtml(tip)
    return doc.toPlainText()


def test_plain_tip_shows_markup_as_written(qtbot):
    assert shown(qtext.plain_tip(HOSTILE)) == HOSTILE
    assert shown(qtext.plain_tip("a\nb")) == "a\nb"
    assert "<a " not in qtext.plain_tip(HOSTILE) and qtext.plain_tip("") == ""


def test_the_mods_page_tooltips(qtbot, tmp_path):
    from .test_mods import component, page
    mods = [{"key": "m", "name": "M", "games": ["EET"], "categories": [], "status": [],
             "advisories": [], "kinds": [], "kinds_by_source": {"lcc-docs": [HOSTILE]},
             "tp2s": [{"tp2": "m/setup-m.tp2", "origin": "tp2",
                       "components": [component(0, "One")]},
                      {"tp2": "m/../bad.tp2", "origin": "tp2", "refused": HOSTILE,
                       "components": [component(1, "Two")]}]}]
    widget = page(qtbot, tmp_path, mods)
    item = widget.tree.topLevelItem(0)
    assert HOSTILE in shown(item.toolTip(3))
    def every(node):
        for i in range(node.childCount()):
            yield node.child(i)
            yield from every(node.child(i))
    refused = [c for c in every(item) if c.toolTip(0)]
    assert refused and all(shown(c.toolTip(0)) == HOSTILE for c in refused)


def test_the_order_page_tooltip(qtbot, tmp_path):
    from .test_order import page, unit

    def planner(game, chosen, labels, folder):
        units = [unit("eet"), dict(unit("x"), category="", placed_by=HOSTILE)]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    assert HOSTILE in shown(widget.tabs.widget(0).item(1).toolTip())


def test_the_download_page_tooltips(qtbot, tmp_path):
    from .test_download import page
    widget = page(qtbot, tmp_path, lambda *a, **k: {"records": []})
    from PySide6.QtWidgets import QTreeWidgetItem
    item = QTreeWidgetItem(["m"])
    widget.table.addTopLevelItem(item)
    widget._finish_row(item, "failed", HOSTILE)
    widget._offer(item, {"version": HOSTILE, "repo": "a/b", "installed": "1"})
    from iemod_fetch_gui.pages.download import DETAIL, NEWER
    assert shown(item.toolTip(DETAIL)) == HOSTILE
    assert HOSTILE in shown(item.toolTip(NEWER))


@pytest.mark.parametrize("make", ["window", "mods", "download"])
def test_labels_that_show_names_or_messages_are_plain_text(qtbot, tmp_path, make):
    if make == "mods":
        from .test_mods import page
        label = page(qtbot, tmp_path, []).status
    elif make == "download":
        from .test_download import page
        label = page(qtbot, tmp_path, lambda *a, **k: {"records": []}).summary
    else:
        from iemod_fetch_gui.window import MainWindow
        main = MainWindow(str(tmp_path), load=lambda game, project: [])
        qtbot.addWidget(main)
        label = main.status
    assert label.textFormat() == Qt.TextFormat.PlainText


def test_message_boxes_show_plain_text(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    seen = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.append(
        (self.textFormat(), self.text())) or int(QMessageBox.StandardButton.Yes))
    assert qtext.question(None, "t", HOSTILE) == QMessageBox.StandardButton.Yes
    qtext.critical(None, "t", HOSTILE)
    qtext.information(None, "t", HOSTILE)
    assert seen == [(Qt.TextFormat.PlainText, HOSTILE)] * 3


def _own_constant(part) -> bool:
    """A piece of an f-string that is ours: text, or one of our UPPER_CASE
    constants (api.INSTALL_ORDER_FILE)."""
    if isinstance(part, ast.Constant):
        return True
    value = part.value if isinstance(part, ast.FormattedValue) else part
    name = value.attr if isinstance(value, ast.Attribute) else getattr(value, "id", "")
    return bool(name) and name.isupper()


def test_every_tooltip_is_a_fixed_string_or_plain_tip():
    """A tooltip added later with data in it, and no plain_tip, fails here.
    pages/install.py is the other session's (its one tooltip lists local
    prerequisites); it is reported, not changed, by this PR."""
    offenders = []
    for root, _dirs, files in os.walk(GUI):
        for name in files:
            if not name.endswith(".py") or name == "install.py":
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "setToolTip" and node.args):
                    arg = node.args[-1]
                    fixed = isinstance(arg, ast.Constant) or (
                        isinstance(arg, ast.JoinedStr) and all(
                            _own_constant(v) for v in arg.values)) or (
                        isinstance(arg, ast.BinOp) and all(
                            isinstance(v, ast.Constant) for v in (arg.left, arg.right)))
                    tipped = (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                              and arg.func.attr == "plain_tip")
                    if not (fixed or tipped):
                        offenders.append(f"{name}:{node.lineno}")
    assert offenders == []
