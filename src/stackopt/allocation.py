"""Enumerate and evaluate declared drawing tolerance assignments."""

from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction
from itertools import product
from math import prod
from time import monotonic_ns
from typing import Literal, NotRequired, TypedDict

from .analysis import evaluate
from .contract_validation import format_decimal_text
from .contracts import (
    AllocationStatus,
    CalloutRef,
    Candidate,
    ClosestCandidate,
    Evaluation,
    Ranking,
    ResolvedDimension,
    ResolvedProblem,
    SearchBudget,
    SearchEvidence,
    SelectedOption,
    ToleranceOption,
    callout_key,
)
from .diagnostics import ContractError, Diagnostic, ExitStatus

_CalloutKey = tuple[str, str, str | None, str | None]
_Option = ToleranceOption[Fraction, Fraction]
_StopReason = Literal["evaluation_limit", "time_limit", "interrupted"]
_NANOSECONDS_PER_SECOND = 10**9


class AllocationRun(TypedDict):
    """Exact allocator evidence for report assembly."""

    baseline: Evaluation[Fraction]
    search: SearchEvidence[Fraction]
    feasible_candidates: list[Candidate[Fraction]]
    ranking: Ranking
    closest: NotRequired[ClosestCandidate[Fraction]]
    diagnostics: list[Diagnostic]


def _apply_options(
    problem: ResolvedProblem[Fraction], choices: Mapping[_CalloutKey, _Option],
) -> ResolvedProblem[Fraction]:
    dimensions: list[ResolvedDimension[Fraction]] = []
    for original in problem["dimensions"]:
        option = choices.get(callout_key(original["callout"]))
        if option is None:
            dimensions.append(original)
            continue
        deviations = option["deviations"]
        dimension = original.copy()
        dimension["drawing_limits"] = {
            "lower": original["nominal"] + deviations["lower"],
            "upper": original["nominal"] + deviations["upper"],
            "deviations": deviations.copy(),
        }
        dimension["tolerance_source"] = "option"
        dimensions.append(dimension)
    candidate = problem.copy()
    candidate["dimensions"] = dimensions
    return candidate


def apply_assignment(
    problem: ResolvedProblem[Fraction], assignment: Sequence[SelectedOption[Fraction]],
) -> ResolvedProblem[Fraction]:
    """Recreate a candidate problem for point evaluation and report attribution.

    Pass an assignment from this baseline. Its qualified callout and option IDs
    select the declared deviations. Treat shared input records as read-only.
    """
    groups = {callout_key(group["callout"]): group["options"] for group in problem["option_groups"]}
    selected = {callout_key(item["callout"]): item["option_id"] for item in assignment}
    if selected.keys() != groups.keys() or len(assignment) != len(groups):
        raise ValueError("The assignment must select one option per adjustable callout.")

    choices: dict[_CalloutKey, _Option] = {}
    for key, options in groups.items():
        option_id = selected[key]
        option = next((item for item in options if item["id"] == option_id), None)
        if option is None:
            raise ValueError(f"Option {option_id!r} is undeclared for callout {key!r}.")
        choices[key] = option
    return _apply_options(problem, choices)


def _selection(callout: CalloutRef, option: _Option) -> SelectedOption[Fraction]:
    selection: SelectedOption[Fraction] = {"callout": callout.copy(), "option_id": option["id"]}
    if "score" in option:
        selection["score"] = option["score"].copy()
    return selection


def _ranking(problem: ResolvedProblem[Fraction]) -> Ranking:
    ranking: Ranking = {"status": "unranked", "best_candidate_indices": []}
    if "objective" not in problem:
        ranking["reason"] = "no_objective"
        return ranking

    ranking["objective"] = problem["objective"].copy()
    groups = problem["option_groups"]
    if not groups:
        ranking["reason"] = "no_option_groups"
    elif any("score" not in option for group in groups for option in group["options"]):
        ranking["reason"] = "missing_scores"
    else:
        ranking["status"] = "complete"
    return ranking


def _validate_budget(budget: SearchBudget[Fraction]) -> None:
    if budget.keys() - {"max_evaluations", "max_seconds"}:
        raise ValueError("Unknown search budget field.")
    if "max_evaluations" in budget:
        limit = budget["max_evaluations"]
        if type(limit) is not int or limit < 0:
            raise ValueError("max_evaluations must be a nonnegative integer.")
    if "max_seconds" in budget:
        seconds = budget["max_seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, (Fraction, int)) or seconds < 0:
            raise ValueError("max_seconds must be a nonnegative exact number of seconds.")
        # v1 must be able to persist the supplied budget without rounding.
        format_decimal_text(Fraction(seconds))


def _evaluate(problem: ResolvedProblem[Fraction]) -> Evaluation[Fraction]:
    try:
        return evaluate(problem)
    except ContractError:
        raise
    except Exception as error:
        raise ContractError({
            "code": "internal.failure",
            "severity": "error",
            "message": "The clearance evaluator failed during allocation.",
            "recovery": "Inspect the evaluator error and the resolved drawing limits.",
        }, ExitStatus.EXECUTION_FAILURE) from error


def allocate(
    problem: ResolvedProblem[Fraction],
    *,
    budget: SearchBudget[Fraction] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> AllocationRun:
    """Search the validated single-chain problem in declared product order.

    The budget covers candidate search after baseline evaluation. The callback
    and limits are checked before starting each candidate. An evaluation that
    finishes after the time limit still counts. At most one candidate is in flight.
    """
    if budget is not None:
        budget = budget.copy()
        _validate_budget(budget)
    baseline = _evaluate(problem)
    groups = problem["option_groups"]
    keys = [callout_key(group["callout"]) for group in groups]
    pools = [group["options"] for group in groups]
    total = prod(map(len, pools))
    ranking = _ranking(problem)
    comparable = ranking["status"] != "unranked"

    max_evaluations = None if budget is None else budget.get("max_evaluations")
    max_seconds = None if budget is None else budget.get("max_seconds")
    deadline = None if max_seconds is None else monotonic_ns() + max_seconds * _NANOSECONDS_PER_SECOND
    evaluated = 0
    feasible: list[Candidate[Fraction]] = []
    nearest: tuple[Fraction, Candidate[Fraction]] | None = None
    stop_reason: _StopReason | None = None

    for index, options in enumerate(product(*pools)):
        try:
            if should_stop is not None and should_stop():
                stop_reason = "interrupted"
                break
            if max_evaluations is not None and evaluated >= max_evaluations:
                stop_reason = "evaluation_limit"
                break
            if deadline is not None and monotonic_ns() >= deadline:
                stop_reason = "time_limit"
                break
            evaluation = _evaluate(_apply_options(problem, dict(zip(keys, options))))
            assignment = [_selection(group["callout"], option) for group, option in zip(groups, options)]
            candidate: Candidate[Fraction] = {"index": index, "assignment": assignment, "evaluation": evaluation}
            if comparable:
                candidate["total_score"] = sum((option["score"]["value"] for option in options), Fraction(0))
        except KeyboardInterrupt:
            stop_reason = "interrupted"
            break

        evaluated += 1

        if evaluation["meets_requirement"]:
            feasible.append(candidate)
            nearest = None
        elif not feasible:
            violation = max(Fraction(0), -min(evaluation["margins"].values()))
            if nearest is None or violation < nearest[0]:
                nearest = violation, candidate

    if evaluated == total:
        status: AllocationStatus = "complete" if feasible else "infeasible"
    else:
        status = "incomplete" if evaluated else "zero_tested"
        if comparable:
            ranking["status"] = "provisional"

    if comparable and feasible:
        best_score = min(candidate["total_score"] for candidate in feasible)
        ranking["best_candidate_indices"] = [
            candidate["index"] for candidate in feasible if candidate["total_score"] == best_score
        ]

    search: SearchEvidence[Fraction] = {
        "status": status, "total": total, "evaluated": evaluated, "feasible": len(feasible),
    }
    diagnostics: list[Diagnostic] = []
    if budget is not None:
        search["budget"] = budget
    if stop_reason is not None:
        search["stop_reason"] = stop_reason
        diagnostics.append({
            "code": "search.incomplete",
            "severity": "warning",
            "message": f"The search stopped after {evaluated} of {total} assignments.",
            "recovery": "Run the search to completion to assess all declared assignments.",
        })

    run: AllocationRun = {
        "baseline": baseline, "search": search, "feasible_candidates": feasible,
        "ranking": ranking, "diagnostics": diagnostics,
    }
    if nearest is not None:
        violation, closest = nearest
        run["closest"] = {
            "qualification": "closest_tested" if status == "infeasible" else "closest_so_far",
            "maximum_violation": violation,
            "candidate": closest,
        }
    return run
