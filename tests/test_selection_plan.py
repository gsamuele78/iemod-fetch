"""
The wizard's install order without a window (M3 phase 3, ADR-0038): the plan
of a selection, split by EET phase, and the order the player sets by hand -
kept as a Project Infinity Sorting Order file the command line reads too.
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.errors import ConfigError
from iemod_fetch.weidu import parse_weidu_files

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")
KRION = os.path.join(HERE, "data", "krion")


def chosen_of(*logs):
    parsed = parse_weidu_files([(log, None) for log in logs])
    components = sorted((c for mod in parsed.mods.values() for c in mod.components),
                        key=lambda c: c.line)
    return [((c.path or f"{c.folder}/{c.tp2_file}").replace("\\", "/"), c.index)
            for c in components]


# the BG:EE phase's mod first, as a player might tick it
CHOSEN = chosen_of(os.path.join(MOCK, "WeiDU-BGEE.log"), os.path.join(MOCK, "WeiDU.log"))


def plan(folder, chosen=CHOSEN, **extra):
    extra.setdefault("order_catalogue", KRION)
    return api.selection_plan("EET", chosen, folder=str(folder),
                              rules=extra.pop("rules", [os.path.join(MOCK, "rules")]),
                              target=os.path.join(MOCK, "Mods"),
                              data_dir=str(folder / "no-cache"), **extra)


def names(result, title):
    phase = next(p for p in result["phases"] if p["title"] == title)
    return [u["name"].lower() for u in phase["units"]]


# ------------------------------------------------------------- the plan
def test_an_eet_build_is_planned_in_its_two_phases(tmp_path):
    result = plan(tmp_path)
    assert result["planned"] and not result["custom"]
    assert [p["title"] for p in result["phases"]] == ["BG:EE before the conversion", "EET"]
    assert names(result, "BG:EE before the conversion") == ["bg1ub"]
    eet = names(result, "EET")
    # the test catalogue places EET, then cdtweaks (pre-tactical), then
    # stratagems (tactical); components it files apart are units of their own
    first = {name.split(" #")[0]: n for n, name in reversed(list(enumerate(eet)))}
    assert first["eet"] < first["cdtweaks"] < first["stratagems"] < first["eet_end"]
    assert "stratagems #4100" in eet


def test_the_selection_is_saved_in_the_same_two_phases(tmp_path):
    api.save_selection(str(tmp_path), "EET", CHOSEN, order_catalogue=KRION)
    selection = api.load_selection(str(tmp_path / api.SELECTION_FILE))
    assert [i.game for i in selection.installs] == ["BGEE", "EET"]
    assert [c.tp2.lower() for c in selection.installs[0].components] == ["bg1ub/bg1ub.tp2"]


def test_without_krion64s_data_there_is_no_plan_and_one_install(tmp_path):
    result = plan(tmp_path, order_catalogue=None)
    assert result == {"phases": [], "cycles": [], "violations": [], "planned": False,
                      "custom": False}
    api.save_selection(str(tmp_path), "EET", CHOSEN)          # no data cache here
    selection = api.load_selection(str(tmp_path / api.SELECTION_FILE))
    assert [i.game for i in selection.installs] == ["EET"]


def test_a_rule_placed_mod_is_marked(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "ub(-):ascension(-)", "direction": "before", "severity": "warning"}]}))
    result = plan(tmp_path, rules=[str(rules)])
    eet = next(p for p in result["phases"] if p["title"] == "EET")["units"]
    marked = {u["name"].lower() for u in eet if u["constrained"]}
    assert {"ub", "ascension"} <= marked
    order = names(result, "EET")
    assert order.index("ub") < order.index("ascension")


# --------------------------------------------------- the order by hand
def test_an_order_set_by_hand_is_kept_and_applied(tmp_path):
    first = plan(tmp_path)
    phases = [p["units"] for p in first["phases"]]
    eet = phases[1]
    ub = next(u for u in eet if u["name"].lower() == "ub")
    eet.remove(ub)
    eet.insert(eet.index(next(u for u in eet if u["name"].lower() == "ascension")), ub)
    path = api.save_install_order(str(tmp_path), phases)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert "ub *" in text and text.index("ub *") < text.index("Ascension *")
    # the command line run in the project reads it as --sorting-order
    assert "sorting_order = install-order.txt" in (tmp_path / api.PROJECT_FILE).read_text()
    again = plan(tmp_path)
    assert again["custom"]
    order = names(again, "EET")
    assert order.index("ub") < order.index("ascension")


def test_an_order_that_breaks_a_rule_is_reported_not_silently_won(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "ascension(-):ub(-)", "direction": "before", "severity": "warning"}]}))
    phases = [p["units"] for p in plan(tmp_path, rules=[str(rules)])["phases"]]
    eet = phases[1]
    ub = next(u for u in eet if u["name"].lower() == "ub")
    eet.remove(ub)
    eet.insert(0, ub)
    api.save_install_order(str(tmp_path), phases)
    result = plan(tmp_path, rules=[str(rules)])
    assert result["cycles"] or result["violations"]


def test_using_the_computed_order_again_forgets_the_file(tmp_path):
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    api.save_install_order(str(tmp_path), phases)
    api.reset_install_order(str(tmp_path))
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()
    assert "sorting_order" not in (tmp_path / api.PROJECT_FILE).read_text()
    assert not plan(tmp_path)["custom"]


def test_a_split_mod_names_its_components(tmp_path):
    unit = {"tp2": "stratagems/setup-stratagems.tp2", "split": True,
            "components": [["stratagems/setup-stratagems.tp2", 4100, ""]]}
    whole = {"tp2": "ub/setup-ub.tp2", "split": False, "components": []}
    with open(api.save_install_order(str(tmp_path), [[whole, unit]]), encoding="utf-8") as fh:
        text = fh.read()
    assert "ub *\nstratagems 4100\n" in text


def test_a_name_that_cannot_be_a_sorting_line_is_refused(tmp_path):
    with pytest.raises(ConfigError):
        api.save_install_order(str(tmp_path), [[{"tp2": "my mod/my mod.tp2",
                                                 "split": False, "components": []}]])
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()


def collapsed(folders):
    out = []
    for folder in folders:
        if not out or out[-1] != folder:
            out.append(folder)
    return out


def test_the_wizards_order_is_the_order_the_command_line_writes(tmp_path):
    # The acceptance test: the same selection.json and install-order.txt give
    # the same order on the page and in the run's plan.
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    eet = phases[1]
    ub = next(u for u in eet if u["name"].lower() == "ub")
    eet.remove(ub)
    eet.insert(1, ub)
    api.save_install_order(str(tmp_path), phases)
    shown = plan(tmp_path)
    api.save_selection(str(tmp_path), "EET", CHOSEN, order_catalogue=KRION)
    api.run(api.Settings(
        selection=str(tmp_path / api.SELECTION_FILE),
        sorting_order=str(tmp_path / api.INSTALL_ORDER_FILE),
        check_only=True, quiet=True, manifest=os.path.join(HERE, "data", "mod_downloads.json"),
        target=os.path.join(MOCK, "Mods"), rules=[os.path.join(MOCK, "rules")],
        order_catalogue=KRION, plan_order=str(tmp_path / "plan"),
        data_dir=str(tmp_path / "no-cache"), no_update_data=True, no_default_data=True))
    for title, log in (("BG:EE before the conversion", "WeiDU-BGEE.log"), ("EET", "WeiDU.log")):
        lines = (tmp_path / "plan" / log).read_text().splitlines()
        written = collapsed([line[1:].split("\\")[0].lower() for line in lines
                             if line.startswith("~")])
        page = collapsed([u["components"][0][0].split("/")[0].lower()
                          for u in next(p for p in shown["phases"]
                                        if p["title"] == title)["units"]])
        assert written == page, title
