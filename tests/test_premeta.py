"""
The author's own install order before download (ADR-0037): Project Infinity's
metadata ini fetched from the mod's repository, and its Sorting Order file.

The network is a fake client: what it is asked for, and what it answers, is
the test. The end-to-end tests plan the EET mock with nothing staged, so only
the fetched ini or the sorting order can move a mod the catalogue does not
place.
"""
import json
import os

import pytest

from iemod_fetch import api, premeta, sortorder
from iemod_fetch.errors import ConfigError, HttpStatusError, NetworkError

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")
INI = "[Metadata]\nName = Unfinished Business\nBefore = ascension\nAfter = EET\n"


class FakeClient:
    def __init__(self, files=None, fail=None):
        self.files, self.fail, self.asked = files or {}, fail or {}, []

    def read_bytes(self, url, limit=None):
        self.asked.append(url)
        if url in self.fail:
            raise self.fail[url]
        if url in self.files:
            return self.files[url].encode()
        raise HttpStatusError(url, 404, "Not Found")


def raw(repo, path):
    return f"{premeta.RAW}/{repo}/HEAD/{path}"


UB = premeta.Wanted("ub", "setup-ub.tp2", "Pocket-Plane-Group/ub")


# ------------------------------------------------------------- fetching
def test_the_ini_is_looked_for_beside_the_tp2_named_after_it():
    assert premeta.candidates("ub", "setup-ub.tp2") == [
        "ub/setup-ub.ini", "setup-ub.ini", "ub/ub.ini", "ub.ini"]
    # GitHub is case-sensitive; Region of Terror ships RoT/rot.ini
    assert "RoT/rot.ini" in premeta.candidates("RoT", "setup-RoT.tp2")
    assert premeta.candidates("eet", "EET_end/EET_end.tp2") == [
        "eet/EET_end.ini", "EET_end.ini", "eet/eet_end.ini", "eet_end.ini"]


def test_a_found_ini_is_cached_and_gives_the_authors_order(tmp_path):
    client = FakeClient({raw("pocket-plane-group/ub", "ub/ub.ini"): INI})
    cache = premeta.MetadataCache(str(tmp_path))
    assert premeta.fetch(client, cache, [UB], now=100.0) == (1, 0, [])
    cache.save()
    meta = premeta.MetadataCache(str(tmp_path)).get("ub")
    assert meta.before == ["ascension"] and meta.after == ["eet"]


def test_a_missing_ini_is_remembered_and_not_asked_for_again_for_a_week(tmp_path):
    client = FakeClient()
    cache = premeta.MetadataCache(str(tmp_path))
    assert premeta.fetch(client, cache, [UB], now=100.0) == (0, 1, [])
    asked = len(client.asked)
    assert asked == 4 and cache.get("ub") is None
    premeta.fetch(client, cache, [UB], now=100.0 + 86400)
    assert len(client.asked) == asked
    premeta.fetch(client, cache, [UB], now=100.0 + 8 * 86400)
    assert len(client.asked) == 2 * asked


def test_another_repository_is_asked_again(tmp_path):
    client = FakeClient()
    cache = premeta.MetadataCache(str(tmp_path))
    premeta.fetch(client, cache, [UB], now=100.0)
    moved = premeta.Wanted("ub", "setup-ub.tp2", "Spellhold-Studios/ub")
    premeta.fetch(client, cache, [moved], now=101.0)
    assert any("spellhold-studios/ub" in url for url in client.asked)


def test_a_network_error_keeps_the_last_good_entry(tmp_path):
    good = FakeClient({raw("pocket-plane-group/ub", "ub/setup-ub.ini"): INI})
    cache = premeta.MetadataCache(str(tmp_path))
    premeta.fetch(good, cache, [UB], now=100.0)
    down = FakeClient(fail={raw("pocket-plane-group/ub", "ub/setup-ub.ini"):
                            NetworkError("offline")})
    found, missing, problems = premeta.fetch(down, cache, [UB], now=100.0 + 8 * 86400)
    assert (found, missing) == (0, 0) and problems == ["ub: offline"]
    assert cache.get("ub").before == ["ascension"]


def test_a_file_without_a_metadata_section_is_not_taken():
    client = FakeClient({raw("pocket-plane-group/ub", "ub/setup-ub.ini"): "[Settings]\nx=1\n"})
    cache = premeta.MetadataCache("/nonexistent-for-the-test")
    assert premeta.fetch(client, cache, [UB], now=1.0) == (0, 1, [])


def test_a_broken_cache_file_is_started_again(tmp_path):
    (tmp_path / premeta.CACHE_FILE).write_text("{ not json")
    assert premeta.MetadataCache(str(tmp_path)).entries == {}


# --------------------------------------------------------- sorting order
def test_the_sorting_order_file_reads_as_project_infinity_writes_it():
    entries = sortorder.parse("Ascension *  // all of it\n\najantisbg2 *\n"
                              "Ascension 101 102 // apart\n# a note\n")
    assert [(e.key, e.numbers) for e in entries] == [
        ("ascension", None), ("ajantisbg2", None), ("ascension", (101, 102))]


@pytest.mark.parametrize("text", ["Ascension one\n", "Ascension * 3\n"])
def test_a_line_that_is_neither_star_nor_numbers_is_refused(text):
    with pytest.raises(ConfigError, match=":1:"):
        sortorder.parse(text, source="order.txt")


def test_named_components_leave_their_mods_star_line():
    # The wiki's own example: Ascension's portraits go after Ajantis.
    entries = sortorder.parse("Ascension *\najantisbg2 *\nAscension 101 102\n")
    rules = sortorder.rules(entries, {"ascension": {0, 1, 101, 102}, "ajantisbg2": {0}})
    pairs = [((r.left.mod, sorted(r.left.components)),
              (r.right[0].mod, sorted(r.right[0].components))) for r in rules]
    assert pairs == [(("ascension", [0, 1]), ("ajantisbg2", [0])),
                     (("ajantisbg2", [0]), ("ascension", [101, 102]))]


def test_what_is_not_chosen_is_not_ordered():
    entries = sortorder.parse("a *\nb *\nc *\n")
    rules = sortorder.rules(entries, {"a": {1}, "c": {2}})
    assert [(r.left.mod, r.right[0].mod) for r in rules] == [("a", "c")]


# ------------------------------------------------------------ end to end
def plan(tmp_path, **extra):
    settings = api.Settings(
        check_only=True, quiet=True, manifest=os.path.join(HERE, "data", "mod_downloads.json"),
        weidu_log=[os.path.join(MOCK, "WeiDU.log") + ":EET"],
        target=str(tmp_path / "nothing-staged"), rules=[os.path.join(MOCK, "rules")],
        order_catalogue=os.path.join(HERE, "data", "krion"),
        plan_order=str(tmp_path / "plan"), data_dir=str(tmp_path / "data"),
        no_update_data=True, no_default_data=True, **extra)
    api.run(settings)
    lines = (tmp_path / "plan" / "WeiDU.log").read_text().splitlines()
    return [line.split("\\")[0].lstrip("~").lower() for line in lines if line.startswith("~")]


def test_without_the_ini_the_log_order_stands(tmp_path):
    order = plan(tmp_path)
    assert order.index("ascension") < order.index("ub")


def test_a_cached_ini_moves_a_mod_not_downloaded_yet(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / premeta.CACHE_FILE).write_text(json.dumps({"ub": {
        "repo": "pocket-plane-group/ub", "path": "ub/ub.ini", "text": INI, "checked": 1}}))
    order = plan(tmp_path)
    assert order.index("ub") < order.index("ascension")


def test_a_sorting_order_moves_what_it_names(tmp_path):
    path = tmp_path / "SortingOrder.txt"
    path.write_text("ub *\nascension *\n")
    order = plan(tmp_path, sorting_order=str(path))
    assert order.index("ub") < order.index("ascension")
