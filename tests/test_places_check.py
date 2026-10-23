"""
tools/places_check.py, the live check of the kinds and the places (GUI-AUDIT
M5 item 29): a data cache written by hand in the sources' own shapes - BWS-NG's
is GPL and is never bundled, so its files here are made up to its schema.
"""
import json

from tools import places_check


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def cache(root, lcc_label="Interface", bws_code="ui", order=("eet:0", "leui:0", "newui:0",
                                                               "otherui:0")):
    write(root / "lcc-docs" / "db" / "mods.json", [
        {"tp2": "newui", "name": "New UI", "categories": [lcc_label], "games": ["BG2EE"],
         "urls": []},
        {"tp2": "tweak", "name": "A tweak", "categories": ["Gameplay"], "games": ["BG2EE"],
         "urls": []}])
    write(root / "bws-ng" / "data" / "mods" / "newui.json",
          {"name": "New UI", "categories": [bws_code]})
    write(root / "bws-ng" / "data" / "games" / "eet.json",
          {"sequences": [{"game": "bg2ee", "order": list(order)}]})
    write(root / "krion64" / "data" / "categories.json",
          {"categories": {"EET STARTS HERE": {}, "INTERFACE": {}}})
    for key, category in (("EET", "EET STARTS HERE"), ("LeUI", "INTERFACE"),
                          ("otherui", "INTERFACE")):
        write(root / "krion64" / "data" / "mods" / f"{key}.json",
              {"t": key, "c": category, "ord": 10})
    return str(root)


def test_the_live_data_as_expected_passes_and_counts_the_places(tmp_path, capsys):
    out = tmp_path / "out.json"
    assert places_check.main([cache(tmp_path), "--json", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["unknown labels"] == {"lcc-docs": [], "BWS-NG": []}
    assert result["places"] == {"with a kind, krion64 does not place": 2,
                                "by BWS-NG's sequence": 1, "by kind": 0, "no place": 1}


def test_a_category_the_tables_do_not_map_fails_and_is_named(tmp_path, capsys):
    root = cache(tmp_path, lcc_label="Nouvelle catégorie", bws_code="newcode")
    assert places_check.main([root]) == 1
    err = capsys.readouterr().err
    assert "lcc-docs uses categories kinds.py does not map: Nouvelle catégorie" in err
    assert "BWS-NG uses categories kinds.py does not map: newcode" in err


def test_a_sequence_without_the_eet_core_fails(tmp_path, capsys):
    assert places_check.main([cache(tmp_path, order=("leui:0", "newui:0"))]) == 1
    assert "no bg2ee sequence with eet:0" in capsys.readouterr().err


def test_a_cache_missing_a_source_fails(tmp_path, capsys):
    assert places_check.main([str(tmp_path)]) == 1


def test_inversions_count_the_pairs_ordered_the_other_way_round():
    sequence = [("a", 0), ("b", 0), ("c", 0)]
    assert places_check.inversions([("a", 0), ("b", 0), ("c", 0)], sequence) == (0, 3)
    assert places_check.inversions([("c", 0), ("a", 0), ("b", 0)], sequence) == (2, 3)
    assert places_check.inversions([("x", 1), ("b", 0)], sequence) == (0, 0)
