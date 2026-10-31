"""
A recorded answer goes only to a question it fits (GUI-AUDIT M8 item 63):
one the question offers, and the question asked when it was given. Answers
that shifted against a mod's changed prompts are asked of the player instead.
"""
import pytest

from iemod_fetch.prompts import Answers, fits, offered, same_question

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
    assert same_question("Choose  one\n(1-3):", "choose one (1-3):")


def test_a_shifted_answer_is_not_given_nor_are_the_rest_of_its_batch():
    """The mod gained a yes/no question before the numbered one: the log's
    "2" would answer it, and the "y" after would answer the number."""
    answers = Answers({BW: ["2", "y"]})
    answers.start((BW,))
    assert answers.next("Keep Garrick a Troubadour? [y]es or [n]o") is None
    assert "'2' is not one this question offers" in answers.refused
    assert answers.next("Please select 1 or 2") is None and answers.refused is None


def test_an_answer_goes_where_it_was_given_before_and_nowhere_else():
    answers = Answers({UB: ["y"]}, {UB: {0: "Restore the tavern? [y]es or [n]o"}})
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
