"""
Conflicts as options, and decisions.json (M2, GUI-AUDIT item 10).

The acceptance test of the milestone: every conflict in the mock EET plan has
at least one option, and applying it leaves the plan free of that conflict.
The rest pins the file format and what happens to a decision that no longer
fits: it is reported, never applied to something else.
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.conflicts import DESELECT, INSTALL, REORDER, Finding, Side
from iemod_fetch.decisions import Decisions, decisions_to_json, parse_decisions
from iemod_fetch.errors import ConfigError
from iemod_fetch.rules import DEPENDS, INCOMPATIBLE

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")


def settings(tmp_path, **extra):
    return api.Settings(
        check_only=True, quiet=True, manifest=os.path.join(HERE, "data", "mod_downloads.json"),
        weidu_log=[os.path.join(MOCK, "WeiDU.log") + ":EET",
                   os.path.join(MOCK, "WeiDU-BGEE.log") + ":BGEE"],
        target=os.path.join(MOCK, "Mods"), rules=[os.path.join(MOCK, "rules")],
        order_catalogue=os.path.join(HERE, "data", "krion"),
        plan_order=str(tmp_path / "plan"), conflict_report=str(tmp_path / "conflicts.json"),
        no_update_data=True, no_default_data=True, **extra)


def report(tmp_path, **extra):
    outcome = api.run(settings(tmp_path, **extra))
    with open(tmp_path / "conflicts.json", encoding="utf-8") as fh:
        return outcome, json.load(fh)["findings"]


def write(tmp_path, entries):
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps({"schema_version": 1, "decisions": entries}))
    return str(path)


def planned(tmp_path):
    return (tmp_path / "plan" / "WeiDU.log").read_text()


# ----------------------------------------------------- the acceptance test
def test_every_conflict_has_at_least_one_option(tmp_path):
    _outcome, findings = report(tmp_path)
    assert findings
    for finding in findings:
        assert finding["options"], finding["id"]
        ids = [o["id"] for o in finding["options"]]
        assert len(ids) == len(set(ids))


def cases(tmp_path_factory):
    _outcome, findings = report(tmp_path_factory.mktemp("cases"))
    return [(f["id"], o) for f in findings for o in f["options"]
            if o["applicable"] and o["action"] == DESELECT]


def test_applying_each_option_clears_its_conflict(tmp_path_factory):
    for finding_id, option in cases(tmp_path_factory):
        tmp = tmp_path_factory.mktemp("apply")
        outcome, findings = report(tmp, decisions=write(tmp, [
            {"finding": finding_id, "choose": option["id"]}]))
        after = next((f for f in findings if f["id"] == finding_id), None)
        assert after is None or after["fixed_by_plan"], (finding_id, option)
        # and the plan itself no longer holds what the option dropped
        removed = [r for r in outcome.order_plan.resolution.removed
                   if r.finding_id == finding_id]
        assert removed and removed[0].by == "decision"
        lines = [line for line in planned(tmp).splitlines()
                 if line.lower().startswith("~" + option["mod"].lower() + "\\")]
        for number in option["components"]:
            assert not any(f" #{number} " in line for line in lines), (option, lines)


def test_the_tie_the_rules_leave_open_is_settled_by_the_players_choice(tmp_path):
    """stratagems #4100 vs cdtweaks #2370: one component each, so the rules do
    not decide (test_eet_mock). The player keeps SCS."""
    _outcome, findings = report(tmp_path)
    tie = next(f for f in findings
               if f["kind"] == INCOMPATIBLE and f["left"]["mod"] == "stratagems"
               and f["right"]["mod"] == "cdtweaks")
    assert not any(o["recommended"] for o in tie["options"])     # never guessed
    drop_tweak = next(o for o in tie["options"] if o["mod"] == "cdtweaks")
    outcome, after = report(tmp_path, resolve_conflicts=True, decisions=write(
        tmp_path, [{"finding": tie["id"], "choose": drop_tweak["id"]}]))
    assert "#0 #2370 " not in planned(tmp_path)
    assert "#0 #4100 " in planned(tmp_path)
    settled = next(f for f in after if f["id"] == tie["id"])
    assert settled["fixed_by_plan"] and "your decision" in settled["remedy"]
    assert not any(u.finding_id == tie["id"]
                   for u in outcome.order_plan.resolution.left_for_operator)


def test_an_accepted_conflict_keeps_both_sides_and_is_no_longer_outstanding(tmp_path):
    _outcome, findings = report(tmp_path)
    tie = next(f for f in findings if f["kind"] == INCOMPATIBLE and f["severity"] == "error")
    outcome, after = report(tmp_path, resolve_conflicts=True, decisions=write(
        tmp_path, [{"finding": tie["id"], "accept": "tested together, works"}]))
    accepted = next(f for f in after if f["id"] == tie["id"])
    assert accepted["suppressed"] == "accepted in decisions.json: tested together, works"
    assert "#0 #4100 " in planned(tmp_path) and "#0 #2370 " in planned(tmp_path)
    # and --resolve-conflicts no longer lists it as the player's to decide
    assert not any(u.finding_id == tie["id"]
                   for u in outcome.order_plan.resolution.left_for_operator)


def test_a_stale_decision_is_reported_not_applied(tmp_path):
    outcome, _findings = report(tmp_path, decisions=write(tmp_path, [
        {"finding": "conflict-0000000000000000", "choose": "option-0000000000000000"}]))
    assert outcome.order_plan.resolution.stale_decisions == ["conflict-0000000000000000"]
    assert not outcome.order_plan.resolution.removed


def test_an_option_of_another_finding_is_refused(tmp_path):
    _outcome, findings = report(tmp_path)
    one, other = findings[0], findings[1]
    with pytest.raises(ConfigError, match="is not an option of"):
        report(tmp_path, decisions=write(tmp_path, [
            {"finding": one["id"], "choose": other["options"][0]["id"]}]))


def test_decisions_need_a_plan(tmp_path):
    with pytest.raises(ConfigError, match="--decisions works on an install plan"):
        api.run(api.Settings(check_only=True, quiet=True,
                             weidu_log=[os.path.join(MOCK, "WeiDU.log")],
                             decisions="d.json", no_update_data=True))


def test_the_resolution_file_records_the_decision(tmp_path):
    _outcome, findings = report(tmp_path)
    tie = next(f for f in findings if f["kind"] == INCOMPATIBLE and f["severity"] == "error")
    report(tmp_path, decisions=write(tmp_path, [
        {"finding": tie["id"], "choose": tie["options"][0]["id"]}]))
    resolution = json.loads((tmp_path / "plan" / "RESOLUTION.json").read_text())
    assert resolution["removed"][0]["by"] == "decision"
    assert resolution["removed"][0]["finding_id"] == tie["id"]


# ------------------------------------------------------------- the options
def side(key, numbers=(1,), whole=False):
    return Side(key=key, mod=key, components=tuple((n, "") for n in numbers),
                whole_mod=whole)


def test_a_missing_prerequisite_offers_installing_it_or_dropping_the_dependent():
    finding = Finding(kind=DEPENDS, severity="error", log="WeiDU.log",
                      left=side("a"), right=side("b", (), True), scope="missing")
    actions = [(o.action, o.mod, o.applicable) for o in finding.options]
    assert actions == [(INSTALL, "b", False), (DESELECT, "a", True)]


def test_the_cheaper_pinned_side_is_recommended_when_the_rules_decide():
    finding = Finding(kind=INCOMPATIBLE, severity="error", log="WeiDU.log",
                      left=side("a", (1, 2, 3)), right=side("b", (7,)))
    first, second = finding.options
    assert (first.mod, first.recommended, first.cost) == ("b", True, 1)
    assert (second.mod, second.recommended) == ("a", False)


def test_a_warning_or_speculation_recommends_nothing():
    for severity, evidence in (("warning", ""), ("error", "speculative")):
        finding = Finding(kind=INCOMPATIBLE, severity=severity, log="WeiDU.log",
                          left=side("a", (1, 2)), right=side("b", (7,)), evidence=evidence)
        assert not any(o.recommended for o in finding.options)


def test_an_outstanding_order_finding_shows_its_id_and_option_in_the_text():
    import io
    from iemod_fetch.conflicts import ConflictReport, render_conflict_report
    finding = Finding(kind="order", severity="error", log="WeiDU.log",
                      left=side("a"), right=side("b"), first="b",
                      remedy="install b before a", fixed_by_plan=False)
    out = io.StringIO()
    render_conflict_report(ConflictReport(findings=[finding]), out)
    assert finding.id in out.getvalue()
    assert finding.options[0].id(finding.id) in out.getvalue()


def test_an_order_finding_offers_the_reorder():
    finding = Finding(kind="order", severity="error", log="WeiDU.log",
                      left=side("a"), right=side("b"), first="b")
    (only,) = finding.options
    assert (only.action, only.description) == (REORDER, "install b before a")


def test_option_ids_are_stable_and_distinct():
    finding = Finding(kind=INCOMPATIBLE, severity="error", log="WeiDU.log",
                      left=side("a"), right=side("b"))
    ids = [o.id(finding.id) for o in finding.options]
    assert ids == [o.id(finding.id) for o in finding.options]
    assert len(set(ids)) == 2 and all(i.startswith("option-") for i in ids)


# ------------------------------------------------------------- the format
def test_the_format_round_trips():
    decisions = Decisions(choose={"conflict-1": "option-2"}, accept={"conflict-3": "fine"})
    assert parse_decisions(decisions_to_json(decisions)) == decisions


@pytest.mark.parametrize("entry,message", [
    ({"finding": "x", "choose": "option-1"}, "must be a conflict id"),
    ({"finding": "conflict-1"}, "exactly one of"),
    ({"finding": "conflict-1", "choose": "o", "accept": "y"}, "exactly one of"),
    ({"finding": "conflict-1", "accept": " "}, "must say why"),
    ({"finding": "conflict-1", "choose": "nope"}, "must be an option id"),
    ({"finding": "conflict-1", "extra": 1, "accept": "y"}, "unknown key"),
])
def test_a_wrong_entry_is_refused_with_where_and_why(entry, message):
    with pytest.raises(ConfigError, match=message):
        parse_decisions(json.dumps({"schema_version": 1, "decisions": [entry]}))


def test_a_finding_decided_twice_is_refused():
    entry = {"finding": "conflict-1", "accept": "y"}
    with pytest.raises(ConfigError, match="decided twice"):
        parse_decisions(json.dumps({"schema_version": 1, "decisions": [entry, entry]}))


def test_the_report_and_resolution_match_their_schemas(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    _outcome, findings = report(tmp_path)
    tie = next(f for f in findings if f["kind"] == INCOMPATIBLE and f["severity"] == "error")
    report(tmp_path, decisions=write(tmp_path, [
        {"finding": tie["id"], "choose": tie["options"][0]["id"]}]))
    schemas = os.path.join(HERE, os.pardir, "schemas")
    for document, schema in (("conflicts.json", "conflicts-v1.schema.json"),
                             ("plan/RESOLUTION.json", "resolution-v1.schema.json"),
                             ("decisions.json", "decisions-v1.schema.json")):
        with open(os.path.join(schemas, schema), encoding="utf-8") as fh:
            jsonschema.validate(json.loads((tmp_path / document).read_text()),
                                json.load(fh))
