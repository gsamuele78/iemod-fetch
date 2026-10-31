"""
A recorded answer a question plainly does not take is not given (GUI-AUDIT
M8 item 63): the "2" of a log recorded on another version, for a "[y]es or
[n]o". Plainly: the question's last line names its choices, no menu is in
mod_installer's window, and no other answer (a default, a skip, Enter) is
named. Anything else takes any answer, as before (third review of #98:
which question and which component cannot be told from the window).
"""
import pytest

from iemod_fetch.prompts import Answers, fits, offered, question_line

UB = ("setup-ub.tp2", 0)
BW = ("bardicwonders.tp2", 1008)

# What mod_installer sends: WeiDU's lines before the question, then it (review
# of #98: src/parser.rs copies the last `lookback` lines, 10 by default).
WINDOW = ("[weidu] WeiDU version 25100\n    \n    Installing [Restorations] [v30]\n"
          "    Restore the tavern? [y]es or [n]o\n    \n    Copying 1 file ...\n    {}")


@pytest.mark.parametrize("question,choices", [
    ("Restore the tavern? [y]es or [n]o", {"y", "n", "yes", "no"}),
    ("Install it (y/n)?", {"y", "n", "yes", "no"}),
    ("Continue? [Y]es or [N]o", {"y", "n", "yes", "no"}),
    # CEBG's Bardic Wonders 1008 (recipes/.../bardicwonders.toml L40)
    ("Please select 1 or 2 and press Enter.", {"1", "2"}),
    ("Choose one (1-3):", {"1", "2", "3"}),
    ("Choose 1, 2 or 3", {"1", "2", "3"}),
    ("Enter a number between 5 and 7", {"5", "6", "7"}),
    ("Use the default portraits? [y]es or [n]o", {"y", "n", "yes", "no"}),
])
def test_what_a_plain_question_offers(question, choices):
    assert offered(question) == choices
    assert offered(WINDOW.format(question)) == choices        # in the real window too


@pytest.mark.parametrize("question", [
    "Enter the full path to your BG:EE+SoD installation then press Enter.",
    # CEBG's Item Randomiser 510 (manifest/mods/randomiser.toml L16): free input
    ("Please enter the chance for items to randomly not be randomised as a integet "
     "number (e.g. 10 for 10%)"),
    "Which portraits?", "Press Enter to continue", "Enter 2026 to confirm", "",
    "Enter your choice:", "[Y]es, [N]o, [C]ancel",
    "Choose one (1-3), or 0 to skip", "Choose 1 or 2 [default: 2]",
    "Select 1 or 2 (or press Enter)", "Your name (press Enter for the default):",
])
def test_a_question_that_does_not_say_plainly_takes_any_answer(question):
    assert offered(question) is None and fits(question, "anything")


@pytest.mark.parametrize("menu", [
    "Which portraits?\n    1] Original\n    2] Select 5 or 10 random ones",
    "Which portraits?\n    (1) Original\n    (2) Select 5 or 10 random ones",
    "Install the extras? [Y]es or [N]o\n    1] Small\n    2] Large",
    "Which size?\n    a) Small\n    b) Large\n    Please select 1 or 2",
])
def test_a_menu_in_the_window_makes_it_not_plain(menu):
    """Reviews of #98: a menu's options name its choices; with one in the
    window, which line is the question is not known - any answer goes."""
    assert offered(WINDOW.format(menu)) is None and fits(WINDOW.format(menu), "1")


def test_a_question_earlier_in_the_window_is_not_this_one():
    assert offered(WINDOW.format("Please select 1 or 2 and press Enter.")) == {"1", "2"}
    assert fits(WINDOW.format("Enter the chance as a number:"), "10")


def test_fits_aside_case_and_spaces():
    assert fits("Restore? [y]es or [n]o", " Y ") and not fits("Restore? [y]es or [n]o", "2")
    assert question_line(WINDOW.format("Last?")) == "Last?"


def test_a_shifted_answer_is_not_given_nor_are_the_rest_of_its_batch():
    """The mod gained a yes/no question before the numbered one: the log's
    "2" would answer it, and the "y" after would answer the number."""
    answers = Answers({BW: ["2", "y"]})
    answers.start((BW,))
    assert answers.next("Keep Garrick a Troubadour? [y]es or [n]o") is None
    assert "'2' is not one this question offers" in answers.refused
    assert answers.next("Please select 1 or 2") is None and answers.refused is None


def test_an_answer_that_fits_goes_and_says_where_it_came_from():
    answers = Answers({UB: ["y", "2"]})
    answers.start((UB,))
    assert answers.next(WINDOW.format("Restore? [y]es or [n]o")) == "y"
    assert answers.last == (UB, 0)
    assert answers.next(WINDOW.format("Please select 1 or 2")) == "2"
    assert answers.last == (UB, 1)


def test_without_a_question_the_answers_go_in_order_as_before():
    answers = Answers({UB: ["y", "", "c"]})
    answers.start((UB,))
    assert [answers.next(), answers.next(), answers.next(), answers.next()] == \
        ["y", "", "c", None]
