"""
A mod's own install-time constraints, read from its .tp2 (ADR-0025).

WeiDU enforces these when it installs a component - they are not opinions:

    BEGIN @100 DESIGNATED 1100
      REQUIRE_COMPONENT ~setup-dlcmerger.tp2~ ~1~ @200     must already be there
      FORBID_COMPONENT  ~setup-bgt.tp2~ ~0~ @201          must NOT already be there
      REQUIRE_PREDICATE GAME_IS ~bgee~ @202               only on this game
      REQUIRE_PREDICATE MOD_IS_INSTALLED ~x.tp2~ ~3~ @203
      REQUIRE_PREDICATE NOT MOD_IS_INSTALLED ~y.tp2~ ~4~ @204

The claims: component numbers follow WeiDU (position, unless DESIGNATED);
`ACTION_IF ... BEGIN` is not a component; NOT and GAME_IS are read in their
simple, common forms and anything more complex is counted as unread rather
than half-understood.
"""
from iemod_fetch.tp2 import parse_components

TP2 = r"""
BACKUP ~mymod/backup~
AUTHOR ~me~
VERSION ~v3~
LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~

BEGIN @0                                         // component 0
REQUIRE_COMPONENT ~setup-dlcmerger.tp2~ ~1~ @10
COPY_EXISTING ~sw1h01.itm~ ~override~
ACTION_IF GAME_IS ~eet~ BEGIN                    // not a component
  PRINT ~x~
END

BEGIN ~Second~ DESIGNATED 1100                   /* component 1100 */
FORBID_COMPONENT ~SETUP-BGT.TP2~ ~0~ ~no BGT~
REQUIRE_PREDICATE GAME_IS ~bgee eet~ @11

BEGIN @2                                         // component 2: position
SUBCOMPONENT @3
REQUIRE_PREDICATE MOD_IS_INSTALLED ~cdtweaks/setup-cdtweaks.tp2~ ~2100~ @12

BEGIN @4                                         // component 3
SUBCOMPONENT @3
REQUIRE_PREDICATE NOT MOD_IS_INSTALLED ~stratagems/setup-stratagems.tp2~ ~4115~ @13

BEGIN @5 DESIGNATED 50
REQUIRE_PREDICATE (GAME_IS ~bgee~ OR MOD_IS_INSTALLED ~a.tp2~ ~1~) @14
"""


def by_number():
    return {c.number: c for c in parse_components(TP2)}


def test_component_numbers_follow_weidu():
    assert list(by_number()) == [0, 1100, 2, 3, 50]


def test_an_action_if_block_is_not_a_component():
    assert len(parse_components(TP2)) == 5


def test_require_component_is_read_with_the_tp2_identity():
    assert by_number()[0].requires == [("dlcmerger", 1)]


def test_forbid_component_is_read_case_insensitively():
    assert by_number()[1100].forbids == [("bgt", 0)]


def test_a_component_game_requirement_is_read():
    assert by_number()[1100].games == ["BGEE", "EET"]
    assert by_number()[0].games == []                # an ACTION_IF is not a requirement


def test_mod_is_installed_predicates_become_requires_and_forbids():
    assert by_number()[2].requires == [("cdtweaks", 2100)]
    assert by_number()[3].forbids == [("stratagems", 4115)]


def test_subcomponent_groups_are_kept():
    assert by_number()[2].group == by_number()[3].group != ""


def test_a_compound_predicate_is_counted_not_half_read():
    complex_one = by_number()[50]
    assert complex_one.requires == [] and complex_one.games == []
    assert complex_one.unread == 1


# --------------------------------------- forms seen in the real tp2s (2026-10)
# Lines quoted from SCS, Tweaks Anthology, Ascension, EEFixPack, DlcMerger and
# EET, as cloned from their upstream repositories.
REAL = r"""
BEGIN @20013 DESIGNATED 4100 GROUP @4                         // SCS
FORBID_COMPONENT "setup-cdtweaks.tp2" 2370 @50010

BEGIN @123 DESIGNATED 2370                                   // Tweaks
REQUIRE_PREDICATE !MOD_IS_INSTALLED ~stratagems.tp2~ 4100 @24

BEGIN @124 DESIGNATED 2371
REQUIRE_PREDICATE !(MOD_IS_INSTALLED ~iwdification/setup-iwdification.tp2~ 30) @25

BEGIN @0 DESIGNATED 0                                        // EEFixPack
REQUIRE_PREDICATE !GAME_IS ~eet~ @11

BEGIN @1 DESIGNATED 1                                        // Ascension
REQUIRE_PREDICATE GAME_INCLUDES tob @1

BEGIN @2 DESIGNATED 2                                        // EET core
REQUIRE_PREDICATE ENGINE_IS ~bg2ee~ @3
FORBID_COMPONENT ~setup-bp-bgt-worldmap.tp2~ ~0~ @4

BEGIN @3 DESIGNATED 3                                        // DlcMerger
REQUIRE_PREDICATE (GAME_IS ~bgee bg2ee eet iwdee pstee~) @5
ACTION_IF (NOT GAME_IS ~bgee~) BEGIN
  ABORT @50
END
"""


def real():
    return {c.number: c for c in parse_components(REAL)}


def test_bang_and_bang_paren_negations_are_forbids():
    assert real()[2370].forbids == [("stratagems", 4100)]
    assert real()[2371].forbids == [("iwdification", 30)]


def test_an_unquoted_component_number_is_read():
    assert real()[4100].forbids == [("cdtweaks", 2370)]


def test_a_negated_game_is_a_game_this_component_refuses():
    assert real()[0].not_games == ["EET"]


def test_game_includes_and_engine_is_name_the_games_they_hold_on():
    assert {"BG2EE", "EET"} <= set(real()[1].games)          # GAME_INCLUDES tob
    assert "BGEE" not in real()[1].games
    assert set(real()[2].games) == {"BG2EE", "EET"}          # ENGINE_IS bg2ee


def test_an_abort_in_the_body_narrows_the_header_requirement():
    """DlcMerger allows five games in its header, then ABORTs unless BGEE."""
    assert real()[3].games == ["BGEE"]
