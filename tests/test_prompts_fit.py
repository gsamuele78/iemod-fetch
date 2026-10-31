"""
A recorded answer goes only to a question it fits (GUI-AUDIT M8 item 63):
one the question offers, and the question asked when it was given. Answers
that shifted against a mod's changed prompts are asked of the player instead.
"""
import pytest

from iemod_fetch.prompts import (Answers, fits, offered, question_block, question_line,
                                 same_question)

UB = ("setup-ub.tp2", 0)
BW = ("bardicwonders.tp2", 1008)


@pytest.mark.parametrize("question,choices", [
    ("Restore the tavern? [y]es or [n]o", {"y", "n", "yes", "no"}),
    ("Install it (y/n)?", {"y", "n", "yes", "no"}),
    # CEBG's Bardic Wonders 1008 (recipes/.../bardicwonders.toml L40)
    ("Please select 1 or 2 and press Enter.", {"1", "2"}),
    ("Choose one (1-3):", {"1", "2", "3"}),
    ("Choose 1, 2 or 3", {"1", "2", "3"}),
    ("1] Classic 2] New\nPlease choose 1 or 2", {"1", "2"}),
    ("Enter a number between 5 and 7", {"5", "6", "7"}),
])
def test_what_a_question_offers(question, choices):
    assert offered(question) == choices


@pytest.mark.parametrize("question", [
    "Enter the full path to your BG:EE+SoD installation then press Enter.",
    # CEBG's Item Randomiser 510 (manifest/mods/randomiser.toml L16): free input
    ("Please enter the chance for items to randomly not be randomised as a integet "
     "number (e.g. 10 for 10%)"),
    "Which portraits?", "Press Enter to continue", "Enter 2026 to confirm", "",
])
def test_a_question_that_says_nothing_takes_any_answer(question):
    assert offered(question) is None and fits(question, "anything")


def test_fits_aside_case_and_spaces():
    assert fits("Restore? [y]es or [n]o", " Y ") and not fits("Restore? [y]es or [n]o", "2")
    assert same_question("Choose  one (1-3):", "choose one (1-3):")


def test_a_shifted_answer_is_not_given_nor_are_the_rest_of_its_batch():
    """The mod gained a yes/no question before the numbered one: the log's
    "2" would answer it, and the "y" after would answer the number."""
    answers = Answers({BW: ["2", "y"]})
    answers.start((BW,))
    assert answers.next("Keep Garrick a Troubadour? [y]es or [n]o") is None
    assert "'2' is not one this question offers" in answers.refused
    assert answers.next("Please select 1 or 2") is None and answers.refused is None


def test_an_answer_goes_where_it_was_given_before_and_nowhere_else():
    answers = Answers({UB: ["y"]}, {UB: {0: {"q": "Restore the tavern? [y]es or [n]o"}}})
    answers.start((UB,))
    assert answers.next("restore the  tavern? [Y]es or [N]o") == "y"
    assert answers.last == (UB, 0)
    answers.start((UB,))
    assert answers.next("Remove the tavern? [y]es or [n]o") is None
    assert "asked something else here" in answers.refused


def test_without_a_question_the_answers_go_in_order_as_before():
    answers = Answers({UB: ["y", "", "c"]})
    answers.start((UB,))
    assert [answers.next(), answers.next(), answers.next(), answers.next()] == \
        ["y", "", "c", None]


# What mod_installer sends: WeiDU's lines before the question, then it (review
# of #98: src/parser.rs copies the last `lookback` lines, 10 by default).
WINDOW = ("[weidu] WeiDU version 25100\n    \n    Installing [Restorations] [v30]\n"
          "    Restore the tavern? [y]es or [n]o\n    \n    Copying 1 file ...\n    {}")


@pytest.mark.parametrize("question,answer", [
    ("Please select 1 or 2 and press Enter.", "2"),         # a yes/no before it
    ("Enter the chance as a number:", "10"),                # a free number
    ("Choose 1, 2 or 3", "3"),                              # its own menu, not one before
    ("Choose one (1-3), or 0 to skip", "0"),
    ("Your name (press Enter for the default):", ""),
])
def test_only_the_questions_own_line_says_what_it_takes(question, answer):
    window = WINDOW.format(question)
    assert question_line(window) == question
    assert fits(window, answer)


def test_two_askings_are_one_question_whatever_came_before():
    v30 = WINDOW.format("Please select 1 or 2 and press Enter.")
    v31 = v30.replace("[v30]", "[v31]").replace("Copying 1 file", "Copying 2 files")
    assert same_question(v30, v31)
    assert not same_question(v30, WINDOW.format("Please select 1, 2 or 3"))


def test_a_players_answer_kept_is_given_for_the_same_question():
    answers = Answers({UB: ["2"]}, {UB: {0: {"q": "Remove? [y]es or [n]o", "a": "n", "r": "2"}}})
    answers.start((UB,))
    assert answers.next(WINDOW.format("Remove? [y]es or [n]o")) == "n"
    assert answers.source == "remembered" and answers.last == (UB, 0)


def test_a_refused_answer_hands_its_place_and_the_rest_to_the_player():
    answers = Answers({UB: ["2", "y"], BW: ["1"]})
    answers.start((UB, BW))
    assert answers.next("Keep it? [y]es or [n]o") is None
    assert answers.player_place() == (UB, 0, "2")
    assert answers.player_place() == (UB, 1, "y")
    assert answers.player_place() == (BW, 0, "1")
    assert answers.player_place() is None          # two components: which asked is unknown


def test_past_the_recorded_answers_a_lone_component_keeps_the_next_place():
    answers = Answers({UB: ["y"]})
    answers.start((UB,))
    assert answers.next("Restore? [y]es or [n]o") == "y"
    assert answers.next("And the portraits?") is None and answers.refused is None
    assert answers.player_place() == (UB, 1, None)


# ---------------------------------------------- second review of #98
def test_a_menu_printed_after_the_question_is_part_of_it_not_its_limit():
    window = WINDOW.format("Which portraits?\n    1] Original\n    2] Select 5 or 10 random ones")
    assert question_block(window) == ["Which portraits?", "1] Original",
                                      "2] Select 5 or 10 random ones"]
    assert offered(window) is None and fits(window, "1")


def test_a_bare_yes_or_no_line_takes_the_question_above_it():
    delete = WINDOW.format("Do you want to DELETE your saves?\n    [Y]es or [N]o")
    keep = WINDOW.format("Do you want to keep your saves?\n    [Y]es or [N]o")
    assert question_line(delete) == "Do you want to DELETE your saves? / [Y]es or [N]o"
    assert offered(delete) == {"y", "n", "yes", "no"}
    assert not same_question(delete, keep)
    answers = Answers({UB: ["y"]}, {UB: {0: {"q": question_line(keep), "a": "y", "r": "y"}}})
    answers.start((UB,))
    assert answers.next(delete) is None and "asked something else here" in answers.refused


@pytest.mark.parametrize("question", [
    "Use the default portraits? [y]es or [n]o", "Skip the intro? [y]es or [n]o",
    "Leave the blank tiles? [y]es or [n]o"])
def test_a_default_or_skip_that_is_not_an_answer_does_not_open_a_yes_or_no(question):
    assert offered(question) == {"y", "n", "yes", "no"}


@pytest.mark.parametrize("question", [
    "Choose one (1-3), or 0 to skip", "Choose 1 or 2 [default: 2]",
    "Select 1 or 2 (or press Enter)", "Enter 1 or 2, enter for the default"])
def test_a_default_or_skip_bound_to_an_answer_opens_it(question):
    assert offered(question) is None


def test_a_remembered_answer_gives_way_when_the_log_changes_its_own():
    kept = {UB: {0: {"q": "Remove? [y]es or [n]o", "a": "n", "r": "2"}}}
    answers = Answers({UB: ["y"]}, kept)                  # the log now records "y"
    answers.start((UB,))
    assert answers.next("Remove? [y]es or [n]o") == "y" and answers.source == "recorded"
