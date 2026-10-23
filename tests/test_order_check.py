"""
The check after a drop on the order page (GUI-AUDIT M5b item 31): only the
rules the moved unit is in are looked at again - and that is always the full
check's answer, whatever the order, the rules and the moves.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from iemod_fetch.ordering import broken_after_move, broken_pairs, reverse


def test_a_unit_after_one_a_rule_puts_before_it_breaks_that_pair():
    before = {"b": {"a"}, "c": {"a", "b"}}
    assert broken_pairs(["a", "b", "c"], before) == set()
    assert broken_pairs(["b", "a", "c"], before) == {("b", "a")}
    assert broken_pairs(["c", "b"], before) == {("c", "b")}        # "a" not in it


@st.composite
def cases(draw):
    size = draw(st.integers(min_value=2, max_value=12))
    nodes = [f"n{i}" for i in range(size)]
    before = {node: set(draw(st.lists(st.sampled_from(nodes), max_size=4))) - {node}
              for node in nodes}
    order = draw(st.permutations(nodes))
    moves = draw(st.lists(st.tuples(st.integers(0, size - 1), st.integers(0, size - 1)),
                          max_size=10))
    return list(order), before, moves


@settings(max_examples=300, deadline=None)
@given(cases())
def test_the_check_after_each_move_equals_the_full_check(case):
    order, before, moves = case
    followers = reverse(before)
    breaks = broken_pairs(order, before)
    for source, target in moves:
        node = order.pop(source)
        order.insert(target, node)
        breaks = broken_after_move(breaks, order, before, node, followers)
        assert breaks == broken_pairs(order, before)
        assert broken_after_move(breaks, order, before, node) == breaks   # no followers


def test_the_benchmark_finds_no_disagreement_and_says_so(tmp_path):
    import json
    from tools import order_check_benchmark
    out = tmp_path / "out.json"
    assert order_check_benchmark.main(["--size", "60", "--moves", "40",
                                       "--json", str(out)]) == 0
    result = json.loads(out.read_text())["synthetic"]
    assert result["units"] == 60 and result["disagreements"] == 0
    assert set(result["after a move (ms)"]) == {"p50", "p95"}
