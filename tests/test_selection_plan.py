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


def test_a_tp2_name_with_spaces_is_written_as_its_key_reads_it(tmp_path):
    # krion64 lists `Setup-Unofficial Item Pack.tp2`; one such mod must not
    # stop every drag.
    unit = {"tp2": "Setup-Unofficial Item Pack.tp2", "split": False, "components": []}
    with open(api.save_install_order(str(tmp_path), [[unit]]), encoding="utf-8") as fh:
        assert "UnofficialItemPack *" in fh.read()


def test_a_name_that_cannot_be_a_sorting_line_is_refused(tmp_path):
    with pytest.raises(ConfigError):
        api.save_install_order(str(tmp_path), [[{"tp2": "--.tp2", "split": False,
                                                 "components": []}]])
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()


def test_an_unwritable_project_ini_leaves_no_order_file(tmp_path):
    (tmp_path / api.PROJECT_FILE).write_text("not an ini [[[\n")
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    with pytest.raises(ConfigError):
        api.save_install_order(str(tmp_path), phases)
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()


def test_your_own_order_does_not_mark_every_mod_as_placed_by_a_rule(tmp_path):
    def constrained(result):
        return sorted(u["name"] for p in result["phases"] for u in p["units"]
                      if u["constrained"])
    before = constrained(plan(tmp_path))
    api.save_install_order(str(tmp_path), [p["units"] for p in plan(tmp_path)["phases"]])
    assert constrained(plan(tmp_path)) == before


def test_the_cli_finds_the_order_file_beside_the_ini_from_anywhere(tmp_path, monkeypatch):
    from iemod_fetch.config import load_config
    api.save_install_order(str(tmp_path), [p["units"] for p in plan(tmp_path)["phases"]])
    monkeypatch.chdir(tmp_path.parent)
    config = load_config(str(tmp_path / api.PROJECT_FILE))
    assert config.values["sorting_order"] == str(tmp_path / api.INSTALL_ORDER_FILE)


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


def test_a_failed_second_save_keeps_the_ini_naming_the_file_still_there(tmp_path, monkeypatch):
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    api.save_install_order(str(tmp_path), phases)

    def full(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(api, "_write_whole", full)
    with pytest.raises(OSError):
        api.save_install_order(str(tmp_path), phases)
    assert (tmp_path / api.INSTALL_ORDER_FILE).exists()
    assert "sorting_order = install-order.txt" in (tmp_path / api.PROJECT_FILE).read_text()


def test_a_path_the_player_wrote_is_put_back_and_never_reset(tmp_path, monkeypatch):
    (tmp_path / api.PROJECT_FILE).write_text("[iemod-fetch]\nsorting_order = my-order.txt\n")
    api.reset_install_order(str(tmp_path))
    assert "my-order.txt" in (tmp_path / api.PROJECT_FILE).read_text()

    def full(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(api, "_write_whole", full)
    with pytest.raises(OSError):
        api.save_install_order(str(tmp_path), [p["units"] for p in plan(tmp_path)["phases"]])
    assert "sorting_order = my-order.txt" in (tmp_path / api.PROJECT_FILE).read_text()


# ---------------------------------------------- the place by kind (item 27)
def test_what_krion64_does_not_place_takes_the_place_its_kind_decides(tmp_path):
    """ub and ascension are not in the test catalogue: lcc-docs, in the data
    cache, says ub is a BG1 quest and ascension gameplay."""
    import shutil
    krion = tmp_path / "krion"
    shutil.copytree(KRION, krion)
    categories = json.loads((krion / "categories.json").read_text(encoding="utf-8"))
    names_ = list(categories["categories"])
    names_.insert(names_.index("ENGINE") + 1, "QUEST MODS BG1")
    categories["categories"] = {name: categories["categories"].get(name, {})
                                for name in names_}
    (krion / "categories.json").write_text(json.dumps(categories), encoding="utf-8")
    lcc = tmp_path / "no-cache" / "lcc-docs" / "db"
    lcc.mkdir(parents=True)
    (lcc / "mods.json").write_text(json.dumps([
        {"tp2": "ub", "name": "Unfinished Business", "categories": ["Quête"],
         "games": ["BGEE"], "urls": []},
        {"tp2": "ascension", "name": "Ascension", "categories": ["Gameplay"],
         "games": ["BG2EE"], "urls": []}]), encoding="utf-8")

    result = plan(tmp_path, order_catalogue=str(krion))

    eet = {u["name"].lower(): u for u in
           next(p for p in result["phases"] if p["title"] == "EET")["units"]}
    assert eet["ub"]["category"] == "QUEST MODS BG1"
    assert eet["ub"]["placed_by"] == "placed by kind: quest, 73% (lcc-docs)"
    assert eet["ascension"]["placed_by"] == ""
    assert eet["ascension"]["no_place"] == "no place: its kind does not decide one (gameplay)"
    order = names(result, "EET")
    first_tweak = next(n for n, name in enumerate(order) if name.startswith("cdtweaks"))
    assert order.index("ub") < first_tweak          # QUEST MODS BG1 before PRE-TACTICAL


def test_bws_ngs_sequence_in_the_data_cache_places_first(tmp_path):
    """Decision 2a: games/eet.json, cached, places ascension after EEex, its
    neighbour after it agreeing (ENGINE), before any kind would."""
    import shutil
    krion = tmp_path / "krion"
    shutil.copytree(KRION, krion)
    (krion / "mods" / "engine2.json").write_text(json.dumps(
        {"t": "engine2", "c": "ENGINE", "ord": 20}), encoding="utf-8")
    games = tmp_path / "no-cache" / "bws-ng" / "data" / "games"
    games.mkdir(parents=True)
    (games / "eet.json").write_text(json.dumps({"sequences": [
        {"game": "bg2ee", "order": ["eet:0", "eeex:0", "ascension:0", "engine2:0"]}]}),
        encoding="utf-8")

    result = plan(tmp_path, order_catalogue=str(krion))

    eet = {u["name"].lower(): u for u in
           next(p for p in result["phases"] if p["title"] == "EET")["units"]}
    assert eet["ascension"]["placed_by"] == "placed by BWS-NG's EET sequence: after eeex #0"
    assert eet["ascension"]["placed_from"] == "BWS-NG"
    assert eet["ub"]["placed_by"] == ""


def test_a_broken_cached_sequence_does_not_block_the_plan(tmp_path):
    """Review of #71 (F2): the data cache's eet.json is warned about; one
    given by hand still stops the run."""
    games = tmp_path / "no-cache" / "bws-ng" / "data" / "games"
    games.mkdir(parents=True)
    (games / "eet.json").write_text('{"sequences": [', encoding="utf-8")

    result = plan(tmp_path)

    assert result["planned"]
    by_hand = api.Settings(eet_sequence=str(games / "eet.json"),
                           data_dir=str(tmp_path / "elsewhere"))
    with pytest.raises(ConfigError, match="cannot read --eet-sequence"):
        api._eet_sequences(by_hand)
    cached = api.Settings(eet_sequence=str(games / "eet.json"),
                          data_dir=str(tmp_path / "no-cache"))
    warned: list = []
    assert api._eet_sequences(cached, warned) is None and "cannot be read" in warned[0]


def test_a_keep_both_decision_in_the_project_orders_the_wizards_plan(tmp_path):
    """Item 28: the wizard's decisions.json "keep both, ascension last"
    becomes an order rule of the plan - here against the mock's own rule
    (ascension before stratagems #5900), which the plan then says."""
    before = plan(tmp_path)
    assert not before["violations"] and not before["cycles"]
    found = api.selection_conflicts("EET", CHOSEN, folder=str(tmp_path),
                                    order_catalogue=KRION,
                                    rules=[os.path.join(MOCK, "rules")],
                                    target=os.path.join(MOCK, "Mods"),
                                    data_dir=str(tmp_path / "no-cache"))
    overlap = next(f for f in found["findings"]
                   if f["kind"] == "incompatible" and f["severity"] == "warning")
    last = next(o for o in overlap["options"]
                if o["action"] == "keep-both" and o["mod"] == "ascension")
    api.save_decisions(str(tmp_path), choose={overlap["id"]: last["id"]})

    after = plan(tmp_path)

    assert after["violations"] or after["cycles"]
