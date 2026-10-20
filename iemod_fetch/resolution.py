"""
Automatic conflict resolution - opt-in, narrow, and re-verified (ADR-0021).

The conflict report already names the narrowest remedy for every finding:
"deselect stratagems #4115 (alternative: drop infinity_ui)". This module applies
that remedy to an install PLAN, for the one class of finding where the rules
themselves decide what goes:

* an incompatibility,
* graded `error` by the rule set,
* not marked speculative,
* between two different mods,
* where the rule pins at least one side to specific components.

Then the side the rule pinned (the cheaper one, by the same cost the report
uses) loses exactly those components - nothing the rule did not name.

Everything else is left for the operator and listed as such: a rule that
condemns two mods wholesale says "not both", not which one; a same-mod conflict
is a choice between two option groups; a missing dependency is fixed by adding,
never by removing; a warning or a speculative claim is not enough to delete
someone's chosen component. Which mod to lose in those cases stays a human
decision, exactly as ADR-0017 said.

Only the plan is edited. The operator's WeiDU logs are never touched, and the
plan is re-checked against the same rules afterwards rather than trusted.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from .conflicts import ConflictReport, Finding, Side
from .naming import normalize_key
from .rules import INCOMPATIBLE, RuleSet


@dataclass
class Removal:
    log: str
    mod: str
    components: Tuple[int, ...]
    labels: Tuple[str, ...]
    because: str            # the other side, as the report describes it
    reason: str = ""        # the rule's own explanation, if it gave one


@dataclass
class Unresolved:
    log: str
    finding: str
    why: str


@dataclass
class ResolutionResult:
    removed: List[Removal] = field(default_factory=list)
    left_for_operator: List[Unresolved] = field(default_factory=list)

    def render(self) -> str:
        lines = ["CONFLICT RESOLUTION (--resolve-conflicts; the plan only, never your logs)"]
        if not self.removed:
            lines.append("  nothing removed")
        for item in self.removed:
            shown = ", ".join(f"#{n}" + (f" {label}" if label else "")
                              for n, label in zip(item.components, item.labels))
            lines.append(f"  removed  [{item.log}] {item.mod}: {shown}")
            lines.append(f"           conflicts with {item.because}")
            if item.reason:
                lines.append(f"           why: {item.reason[:200]}")
        if self.left_for_operator:
            lines.append(f"  left for you to decide ({len(self.left_for_operator)}):")
            for open_item in self.left_for_operator:
                lines.append(f"    [{open_item.log}] {open_item.finding} - "
                             f"{open_item.why}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "removed": [vars(r) for r in self.removed],
            "left_for_operator": [vars(u) for u in self.left_for_operator],
        }


def _why_not(finding: Finding) -> Optional[str]:
    """None when the rules decide this finding; otherwise the reason they do not."""
    if finding.severity != "error":
        return f"graded {finding.severity}, not error"
    if finding.evidence == "speculative":
        return "the claim is speculative (unverified upstream)"
    if finding.scope == "same-mod":
        return "same mod: a choice between two option groups"
    if finding.right is None:
        return "the rule names only one side"
    if finding.left.whole_mod and finding.right.whole_mod:
        return "whole mod vs whole mod: the rules say 'not both', not which one"
    return None


def _cheaper(left: Side, right: Side) -> Tuple[Side, Side]:
    """The side to remove, by the conflict report's own cost: pinned < wholesale."""
    def cost(side: Side) -> int:
        return 10 ** 6 if side.whole_mod else len(side.components)
    return (left, right) if cost(left) <= cost(right) else (right, left)


def _units_for(plan, log: str, key: str) -> list:
    """The plan units a rule's mod key names: the tp2 identity first, else the folder."""
    units = plan.logs.get(log, [])
    exact = [u for u in units if u.key == key]
    if exact:
        return exact
    by_folder = [u for u in units if normalize_key(u.folder) == key]
    # A folder holding two tp2s (eet: EET and EET_end) is ambiguous; refuse.
    return by_folder if len(by_folder) == 1 else []


def _present(plan, log: str, side: Side) -> Set[int]:
    wanted = set(side.numbers)
    found: Set[int] = set()
    for unit in _units_for(plan, log, side.key):
        for _path, _lang, comp, _comment in unit.lines:
            if side.whole_mod or comp in wanted:
                found.add(comp)
    return found


def resolve_conflicts(plan, report: ConflictReport,
                      ruleset: Optional[RuleSet] = None,
                      context=None) -> ResolutionResult:
    """
    Apply the rules' own remedy to every incompatibility they decide.

    `plan` is an ordering.OrderPlan and is edited in place; `report` must have
    been built from `plan.installs()`, so its log labels are the plan's roles.
    """
    result = ResolutionResult()

    for finding in report.findings:
        if finding.kind != INCOMPATIBLE or finding.suppressed:
            continue
        why = _why_not(finding)
        if why is not None or finding.right is None:
            result.left_for_operator.append(Unresolved(
                finding.log, _describe(finding), why or "one-sided finding"))
            continue
        loser, winner = _cheaper(finding.left, finding.right)

        # An earlier removal may already have settled this pair.
        if not _present(plan, finding.log, winner) or not _present(
                plan, finding.log, loser):
            continue
        targets = _present(plan, finding.log, loser)
        units = _units_for(plan, finding.log, loser.key)
        if not units:
            result.left_for_operator.append(Unresolved(
                finding.log, _describe(finding),
                f"cannot tell which tp2 '{loser.mod}' means in this log"))
            continue

        labels = dict(loser.components)
        for unit in units:
            unit.lines = [line for line in unit.lines if line[2] not in targets]
        numbers = tuple(sorted(targets))
        result.removed.append(Removal(
            log=finding.log, mod=loser.mod, components=numbers,
            labels=tuple(labels.get(n, "") for n in numbers),
            because=winner.describe(limit=3), reason=finding.reason))

    for log, units in list(plan.logs.items()):
        plan.logs[log] = [u for u in units if u.lines]
    if ruleset is not None:
        plan.reverify(ruleset, context)
    return result


def _describe(finding: Finding) -> str:
    right = f" vs {finding.right.describe(limit=3)}" if finding.right else ""
    return f"{finding.left.describe(limit=3)}{right}"
