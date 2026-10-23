"""
A mod krion64 does not place takes the place its kind decides (GUI-AUDIT M5
item 27, ADR-0041 decision 2): only where the kind decides one, after
krion64's own mods in that category, never over a rule, and marked with its
source. Where the kind decides nothing the mod stays where the player put it,
and says why.
"""
import io
import json

from iemod_fetch.kinds import KindHint, place
from iemod_fetch.ordering import (EET_LOG, PRE_EET_LOG, OrderIndex, plan_order,
                                  render_plan_summary)
from iemod_fetch.rules import RuleSet

CATEGORIES = ["PRE EET BGEE MODS", "EET STARTS HERE", "INTERFACE", "QUEST MODS BG1",
              "QUEST MODS BG2", "NEW NPC MODS", "KIT & CLASS MODS", "TACTICAL MODS"]
HEADER = "// Log of Currently Installed WeiDU Mods\n"


def krion(tmp_path):
    root = tmp_path / "krion"
    (root / "mods").mkdir(parents=True)
    (root / "categories.json").write_text(json.dumps(
        {"categories": {name: {} for name in CATEGORIES}}), encoding="utf-8")
    for t, c, order in (("EET", "EET STARTS HERE", 10), ("LeUI", "INTERFACE", 10),
                        ("bg1ub", "PRE EET BGEE MODS", 10),
                        ("ascension", "QUEST MODS BG2", 10),
                        ("stratagems", "TACTICAL MODS", 10)):
        (root / "mods" / f"{t}.json").write_text(json.dumps(
            {"t": t, "c": c, "ord": order}), encoding="utf-8")
    return OrderIndex.load(str(root))


def log(tmp_path, *tp2s, name="WeiDU.log"):
    path = tmp_path / name
    path.write_text(HEADER + "\n".join(f"~{t}\\{t}.tp2~ #0 #0 // {t}" for t in tp2s)
                    + "\n", encoding="utf-8")
    return str(path)


def order(plan, role=EET_LOG):
    return [u.key for u in plan.logs[role]]


UI = KindHint(("interface",), ("BG2EE",), ("lcc-docs", "BWS-NG"))


def test_a_kind_that_decides_places_the_mod_after_krion64s_own(tmp_path):
    index = krion(tmp_path)
    eet = log(tmp_path, "EET", "stratagems", "newui", "LeUI")

    plan = plan_order([(eet, EET_LOG)], index, kinds={"newui": UI})

    assert order(plan) == ["eet", "leui", "newui", "stratagems"]
    assert plan.by_kind == [("newui", "INTERFACE",
                             "placed by kind: interface, 92% / 100% (lcc-docs, BWS-NG)")]
    assert plan.unranked == []
    newui = next(u for u in plan.logs[EET_LOG] if u.key == "newui")
    assert newui.placed_by.startswith("placed by kind")


def test_without_the_kinds_the_mod_stays_where_it_was(tmp_path):
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "EET", "stratagems", "newui"), EET_LOG)], index)
    assert order(plan) == ["eet", "stratagems", "newui"]
    assert plan.unranked == ["newui"] and plan.by_kind == []


def test_a_kind_that_decides_nothing_leaves_it_and_says_why(tmp_path):
    index = krion(tmp_path)
    tweak = KindHint(("gameplay",), (), ("lcc-docs",))
    plan = plan_order([(log(tmp_path, "EET", "stratagems", "tweak"), EET_LOG)], index,
                      kinds={"tweak": tweak})
    assert order(plan) == ["eet", "stratagems", "tweak"]
    assert plan.no_place == {"tweak": "no place: its kind does not decide one (gameplay)"}
    out = io.StringIO()
    render_plan_summary(plan, str(tmp_path), out)
    assert "does not decide one (gameplay)" in out.getvalue()


def test_a_rule_still_decides_over_the_kind(tmp_path):
    index = krion(tmp_path)
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps([{"rule": "newui:stratagems", "direction": "after"}]),
                     encoding="utf-8")
    plan = plan_order([(log(tmp_path, "EET", "stratagems", "newui"), EET_LOG)], index,
                      RuleSet.load([str(rules)]), kinds={"newui": UI})
    assert order(plan) == ["eet", "stratagems", "newui"]
    assert plan.verified


def test_a_quest_for_bg1_alone_goes_with_bg1s_quests(tmp_path):
    index = krion(tmp_path)
    bg1 = KindHint(("quest",), ("BGEE", "EET"), ("lcc-docs",))
    bg2 = KindHint(("quest",), ("BG2EE", "EET"), ("lcc-docs",))
    plan = plan_order([(log(tmp_path, "EET", "ascension", "q2", "q1"), EET_LOG)], index,
                      kinds={"q1": bg1, "q2": bg2})
    assert order(plan) == ["eet", "q1", "ascension", "q2"]
    assert {name: category for name, category, _why in plan.by_kind} == {
        "q2": "QUEST MODS BG2", "q1": "QUEST MODS BG1"}


def test_the_install_before_the_eet_core_is_not_placed_by_kind(tmp_path):
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "bg1ub", "newui", name="WeiDU-BGEE.log"),
                        PRE_EET_LOG)], index, kinds={"newui": UI})
    assert order(plan, PRE_EET_LOG) == ["bg1ub", "newui"]
    assert plan.by_kind == [] and plan.phase_notes == []


def test_the_summary_names_what_its_kind_placed(tmp_path):
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "EET", "newui"), EET_LOG)], index,
                      kinds={"newui": UI})
    out = io.StringIO()
    render_plan_summary(plan, str(tmp_path), out)
    assert "placed by kind (1)" in out.getvalue()
    assert "INTERFACE" in out.getvalue()


def test_every_kind_must_decide_the_same_place():
    assert place(KindHint(("kit", "recruitable NPC")))[0] is None
    assert place(KindHint(("quest", "gameplay")))[0] is None
    assert place(KindHint(("recruitable NPC", "one-day NPC")))[0] == "NEW NPC MODS"
    assert place(KindHint(()))[0] is None
    # a label no table knows decides nothing
    assert place(KindHint(("Catégorie nouvelle",)))[0] is None
