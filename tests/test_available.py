"""
The mods a player can choose from, merged from every source given (M1).

A UI's selection screen starts here, before any WeiDU.log exists: one entry
per mod, whatever mix of the download manifest, the lcc-docs catalogue and the
BWS-NG / krion64 mod database knows about it, with the facts each source adds.
"""
import json
import os

import pytest

from iemod_fetch.available import SCHEMA_VERSION, available_mods, mods_document
from iemod_fetch.catalogues import CatalogueSet, SupplementaryCatalogue
from iemod_fetch.manifest import parse_manifest
from iemod_fetch.moddb import ModDatabase, ModFile, ModRecord

SCHEMA = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                      "mods-v1.schema.json")

MANIFEST = parse_manifest({"mods": [
    {"name": "EE Fixpack", "tp2": "eefixpack", "github": "gibberlings3/ee_fixpack",
     "url": "https://github.com/gibberlings3/ee_fixpack"},
    {"name": "DLC Merger", "tp2": "DlcMerger", "github": "Argent77/A7-DlcMerger",
     "url": "https://github.com/Argent77/A7-DlcMerger/releases"}]})

LCC = CatalogueSet([SupplementaryCatalogue.from_entries([
    {"tp2": "eefixpack", "name": "EE Fixpack", "games": ["BGEE", "BG2EE", "EET"],
     "categories": ["Correctifs"], "safe": 2, "status": [], "last_update": "2025-06-01",
     "urls": ["https://github.com/Gibberlings3/EE_Fixpack"]},
    {"tp2": "oldmod", "name": "Old Mod", "games": ["BG2EE"], "safe": 0,
     "status": ["obsolete"], "last_update": "2012-01-01",
     "urls": ["https://example.org/oldmod.zip"]},
], name="lcc")])

DB = ModDatabase(records={"eefixpack": ModRecord(
    key="eefixpack", name="EE Fixpack", version="1.2",
    files=[ModFile(download="https://x/eefixpack-1.2.zip", sha256="ab" * 32)],
    games=["eet"])}, origin="bws")


def by_key(mods):
    return {m.key: m for m in mods}


def test_every_source_contributes_one_entry_per_mod():
    mods = by_key(available_mods(MANIFEST, LCC, DB))
    assert sorted(mods) == ["dlcmerger", "eefixpack", "oldmod"]
    fix = mods["eefixpack"]
    assert fix.in_manifest
    assert fix.games == ("BG2EE", "BGEE", "EET")
    assert (fix.safe, fix.last_update, fix.version) == (2, "2025-06-01", "1.2")
    assert {s["origin"] for s in fix.sources} == {"manifest", "lcc", "bws"}
    assert any(s.get("sha256") == "ab" * 32 for s in fix.sources)


def test_a_mod_only_a_catalogue_knows_is_offered_with_its_advisories():
    old = by_key(available_mods(MANIFEST, LCC, DB))["oldmod"]
    assert not old.in_manifest
    assert old.blocking
    assert any("obsolete" in note for note in old.advisories)


def test_nothing_but_a_manifest_is_enough():
    mods = available_mods(MANIFEST)
    assert [m.key for m in mods] == ["dlcmerger", "eefixpack"]   # sorted by name
    assert mods[0].name == "DLC Merger"


def test_the_document_is_versioned_and_valid_json():
    doc = json.loads(mods_document(available_mods(MANIFEST, LCC, DB)))
    assert doc["schema_version"] == SCHEMA_VERSION
    assert len(doc["mods"]) == 3


def test_the_json_schema_accepts_the_document():
    jsonschema = pytest.importorskip("jsonschema")
    with open(SCHEMA, encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.validate(json.loads(mods_document(available_mods(MANIFEST, LCC, DB))),
                        schema)
