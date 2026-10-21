"""
Engine limits (ADR-0034): kits, spell states, spell slots per level.

The numbers are the primary sources' (WeiDU's ADD_KIT and ADD_SPELL, EEex,
IESDP), not Infinity Mod Forge's; what a component adds is krion64's count.
"""
import io
import json
import os

from iemod_fetch import api
from iemod_fetch.limits import KITS, SPELL_STATES, engine_limits

HERE = os.path.dirname(__file__)


def record(t, components, **extra):
    return {"t": t, "co": components, **extra}


def kits_of(report):
    return report.tallies[0]


def test_kits_are_counted_against_weidus_256_not_forges_320():
    records = [record("dof", [{"cn": 0, "k": 15}, {"cn": 3, "k": 1}])]
    report = engine_limits("EET", [("dof", 0), ("dof", 3)], records)
    kits = kits_of(report)
    assert (kits.base, kits.added, kits.total, kits.cap) == (40, 16, 56, 256)
    assert kits.severity is None and "320" in kits.note
    assert KITS.forge_cap == 320 and KITS.cap == 256


def test_a_kit_table_near_or_past_its_end_warns_or_errs():
    near = engine_limits("EET", [("big", 0)], [record("big", [{"cn": 0, "k": 191}])])
    assert kits_of(near).total == 231 and kits_of(near).severity == "warning"
    past = engine_limits("EET", [("big", 0)], [record("big", [{"cn": 0, "k": 217}])])
    assert kits_of(past).total == 257 and kits_of(past).severity == "error"


def test_a_mod_krion64_does_not_know_is_named_never_counted_as_zero():
    report = engine_limits("EET", [("known", 0), ("mystery", 1)],
                           [record("known", [{"cn": 0}])])
    assert report.unknown_mods == ["mystery"]
    assert "at least" in report.render()


def test_spell_states_are_shown_but_never_warned_on():
    """krion64 counts EE Fixpack 19 - references it only looks up."""
    report = engine_limits("EET", [("eefixpack", 1)],
                           [record("eefixpack", [{"cn": 1, "ss": 200}])])
    states = report.tallies[1]
    assert states.total > states.cap and states.severity is None
    assert not states.checked and "references" in states.note
    assert SPELL_STATES.forge_base == 128


def test_eeex_lifts_the_spell_state_range():
    report = engine_limits("EET", [], [], eeex=True)
    assert report.tallies[1].cap > 10 ** 9 and "EEex" in report.tallies[1].note


def test_spells_are_counted_per_type_and_level():
    records = [record("ctb", [{"cn": 0, "spLv": {"w1": 1, "w6": 4}}]),
               record("x", [{"cn": 0, "spLv": {"w6": 30}}])]
    report = engine_limits("EET", [("ctb", 0), ("x", 0)], records)
    level6 = next(t for t in report.tallies if t.label.startswith("wizard level 6"))
    assert (level6.base, level6.added, level6.total, level6.cap) == (20, 34, 54, 50)
    assert level6.severity == "error"
    assert not any(t.label.startswith("priest") for t in report.tallies)   # nothing added


def test_spells_without_levels_are_reported_not_guessed():
    report = engine_limits("EET", [("m", 0)], [record("m", [{"cn": 0, "sp": 7}])])
    assert report.unlevelled_spells == 7
    assert "not counted against a level" in report.render()


def test_components_are_matched_by_weidu_number_and_folder():
    records = [record("SCS", [{"cn": 5, "wc": 4100, "wf": "stratagems", "k": 2}])]
    report = engine_limits("EET", [("stratagems", 4100)], records)
    assert kits_of(report).added == 2 and report.unknown_mods == []


def test_a_mod_level_spell_state_count_belongs_to_its_first_component():
    records = [record("m", [{"cn": 0}, {"cn": 1}], ss=3)]
    assert engine_limits("EET", [("m", 0)], records).tallies[1].added == 3
    assert engine_limits("EET", [("m", 1)], records).tallies[1].added == 0


def test_the_conflict_report_carries_the_limits(tmp_path):
    log = tmp_path / "WeiDU.log"
    log.write_text("~stratagems/setup-stratagems.tp2~ #0 #4100 // x\n")
    krion = tmp_path / "krion"
    (krion / "mods").mkdir(parents=True)
    (krion / "categories.json").write_text(json.dumps({"categories": {"A": {}}}))
    (krion / "mods" / "stratagems.json").write_text(json.dumps(
        {"t": "stratagems", "ord": 1, "co": [{"cn": 4100, "k": 3}]}))
    (tmp_path / "rules").mkdir()
    out = io.StringIO()
    report_path = tmp_path / "conflicts.json"
    api.run(api.Settings(weidu_log=[f"{log}:EET"], check_only=True,
                         rules=[str(tmp_path / "rules")], order_catalogue=str(krion),
                         conflict_report=str(report_path), no_update_data=True,
                         no_default_data=True,
                         manifest=os.path.join(HERE, "data", "mod_downloads.json")),
            stream=out)
    (limits,) = json.loads(report_path.read_text())["engine_limits"]
    assert limits["install"] == "EET"
    assert limits["tables"][0]["total"] == 43
    assert "ENGINE LIMITS" in out.getvalue()
