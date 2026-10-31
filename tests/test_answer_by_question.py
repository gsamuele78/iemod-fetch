"""
A question recognised by its expected text and answered by its key (ADR-0049,
item 48): prompts.match_question over mod_installer's window, and Answers
kept in step when an answer is taken by question.
"""
from iemod_fetch.prompts import Answers, match_question

A, B = ("setup-a.tp2", 0), ("setup-a.tp2", 10)
WINDOW = ("[weidu] WeiDU version 25100\nInstalling [A] [v1]\nCopying 1 file ...\n"
          "Which portraits do you want?\n  1 - old\n  2 - new\nChoose 1 or 2 for portraits:")


def test_the_question_that_ends_the_window_is_found():
    expected = [(A, "@1", "Choose 1 or 2 for portraits:"),
                (A, "@2", "Which portraits do you want?"),
                (B, "@3", "Enter a percentage between 0 and 100:")]
    assert match_question(WINDOW, expected) == (A, "@1")
    # an earlier line of the window is not the question being asked
    assert match_question(WINDOW, expected[1:]) is None


def test_white_space_and_a_variable_are_read_as_weidu_prints_them():
    text = "Detected BG:EE directory as %bgee_dir%. Is this correct? [Y]es  [N]o"
    window = "Detected BG:EE directory as C:\\Games\\BGEE.\nIs this correct? [Y]es [N]o"
    assert match_question(window, [(A, "@9", text)]) == (A, "@9")


def test_a_short_text_says_too_little_to_be_recognised():
    assert match_question("Continue? y/n", [(A, "@1", "y/n")]) is None
    assert match_question("Continue? %x%", [(A, "@1", "%answer%")]) is None


def test_the_longer_of_two_matching_texts_wins_and_a_tie_is_no_answer():
    window = "Do you want to install the portraits now? (y/n)"
    assert match_question(window, [(A, "@1", "install the portraits now? (y/n)"),
                                   (A, "@2", "Do you want to install the portraits now? (y/n)")]) \
        == (A, "@2")
    # the same text asked by two components: which one is not known
    assert match_question(window, [(A, "@2", "Do you want to install the portraits now? (y/n)"),
                                   (B, "@7", "Do you want to install the portraits now? (y/n)")]) \
        is None


def test_an_answer_taken_by_question_leaves_the_rest_in_step():
    answers = Answers({A: ["1", "2"], B: ["30"]}, {A: ["@1", "@2"], B: ["@3"]})
    answers.start((A, B))
    assert answers.take(A, "@2") == "2"            # asked first: by its key
    assert answers.next() == "1" and answers.next() == "30" and answers.next() is None
    answers.start((A, B))
    assert answers.take(B, "@9") is None           # none recorded for it


def test_without_keys_the_answers_go_in_order_as_before():
    answers = Answers({A: ["1", "2"]})
    answers.start((A,))
    assert answers.take(A, "@1") is None and answers.next() == "1"
