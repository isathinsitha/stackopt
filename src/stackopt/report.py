"""Assemble exact v1 reports and render them without performing I/O."""

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
import json
from typing import Literal, cast

from .allocation import AllocationRun, apply_assignment
from .analysis import evaluate_at_temperature
from .contract_validation import format_decimal_text
from .contracts import (
    SCHEMA_VERSION,
    AllocationResult,
    AnalysisResult,
    CalloutChange,
    CalloutRef,
    Candidate,
    CandidateExplanation,
    ContributionChange,
    DecimalText,
    Deviations,
    Evaluation,
    MarginChange,
    Side,
    Sides,
    callout_key,
)
from .diagnostics import Diagnostic, DiagnosticResult
from .snapshot import AnalysisInput

_Bound = Literal["lower_bound", "upper_bound"]
_Role = Literal["selected", "provisional_best", "closest_tested", "closest_so_far"]
_SIDE_BOUNDS: dict[Side, _Bound] = {"minimum": "lower_bound", "maximum": "upper_bound"}
_ROLES: dict[_Role, str] = {
    "selected": "Selected feasible candidate",
    "provisional_best": "Provisional best among evaluated candidates",
    "closest_tested": "Closest tested candidate (diagnostic, still fails)",
    "closest_so_far": "Closest evaluated so far (diagnostic, still fails)",
}


def _encode_exact(value: object) -> object:
    if isinstance(value, Fraction):
        return format_decimal_text(value)
    if isinstance(value, dict):
        return {key: _encode_exact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode_exact(item) for item in value]
    return value


def _context(source: AnalysisInput, baseline: Evaluation[Fraction]) -> dict[str, object]:
    problem = source.problem
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": source.case_id,
        "source_kind": source.source_kind,
        "scope": problem["scope"],
        "chain_id": problem["chain"]["id"],
        "requirement": problem["requirement"],
        "model": problem["model"],
        "baseline": baseline,
        "diagnostics": source.diagnostics,
    }


def build_analysis_report(source: AnalysisInput, baseline: Evaluation[Fraction]) -> AnalysisResult:
    """Assemble the v1 result for an already evaluated baseline."""
    return cast(AnalysisResult, _encode_exact({"kind": "analysis_result", **_context(source, baseline)}))


def _callout_changes(
    baseline: Evaluation[Fraction], candidate: Candidate[Fraction],
) -> list[CalloutChange[Fraction]]:
    before = {callout_key(entry["callout"]): entry["limits"]["deviations"]
              for entry in baseline["drawing_limits"]}
    after = {callout_key(entry["callout"]): entry["limits"]["deviations"]
             for entry in candidate["evaluation"]["drawing_limits"]}
    changes: list[CalloutChange[Fraction]] = []
    for option in candidate["assignment"]:
        callout = option["callout"]
        key = callout_key(callout)
        if before[key] != after[key]:
            changes.append({"callout": callout, "option_id": option["option_id"],
                            "before": before[key], "after": after[key]})
    return changes


def _explain_candidate(
    source: AnalysisInput, baseline: Evaluation[Fraction], candidate: Candidate[Fraction], role: _Role,
) -> CandidateExplanation[Fraction]:
    evaluation = candidate["evaluation"]
    candidate_problem = apply_assignment(source.problem, candidate["assignment"])
    temperatures = dict.fromkeys(
        baseline[bound]["temperature"] for side, bound in _SIDE_BOUNDS.items() if side in baseline["margins"]
    )
    point_bounds = {temperature: evaluate_at_temperature(candidate_problem, temperature)
                    for temperature in temperatures}
    margins: Sides[MarginChange[Fraction]] = {}
    for side, bound in _SIDE_BOUNDS.items():
        if side not in baseline["margins"]:
            continue
        baseline_bound = baseline[bound]
        candidate_bound = evaluation[bound]
        temperature = baseline_bound["temperature"]
        upper = side == "maximum"
        lower_at_temperature, upper_at_temperature = point_bounds[temperature]
        same_temperature = upper_at_temperature if upper else lower_at_temperature
        by_physical_id = {term["physical_id"]: term["contribution"] for term in same_temperature["terms"]}
        terms: list[ContributionChange[Fraction]] = [
            {"physical_id": term["physical_id"], "baseline_contribution": term["contribution"],
             "candidate_contribution": by_physical_id[term["physical_id"]]}
            for term in baseline_bound["terms"]
        ]
        sign = -1 if upper else 1
        before = cast(Fraction, baseline["margins"][side])
        after = cast(Fraction, evaluation["margins"][side])
        margins[side] = {
            "baseline_margin": before,
            "candidate_margin": after,
            "margin_delta": after - before,
            "baseline_temperature": temperature,
            "candidate_temperature": candidate_bound["temperature"],
            "same_temperature_delta": sign * sum(
                (term["candidate_contribution"] - term["baseline_contribution"] for term in terms), Fraction(0)
            ),
            "governing_temperature_delta": sign * (candidate_bound["value"] - same_temperature["value"]),
            "terms": terms,
        }
    return {"candidate_index": candidate["index"], "role": role,
            "callout_changes": _callout_changes(baseline, candidate), "margins": margins}


def build_allocation_report(source: AnalysisInput, run: AllocationRun) -> AllocationResult:
    """Assemble a v1 allocation result and explain the reported candidate, if any."""
    baseline = run["baseline"]
    search = run["search"].copy()
    if "budget" in search and "max_seconds" in search["budget"]:
        # The allocator accepts an integer seconds budget as an exact input too.
        search["budget"] = {**search["budget"], "max_seconds": Fraction(search["budget"]["max_seconds"])}
    report = {
        "kind": "allocation_result",
        **_context(source, baseline),
        "search": search,
        "ranking": run["ranking"],
        "feasible_candidates": run["feasible_candidates"],
        "diagnostics": [*source.diagnostics, *run["diagnostics"]],
    }
    best = run["ranking"]["best_candidate_indices"]
    if best:
        candidate = next(item for item in run["feasible_candidates"] if item["index"] == best[0])
        role: _Role = "provisional_best" if run["ranking"]["status"] == "provisional" else "selected"
        report["explanation"] = _explain_candidate(source, baseline, candidate, role)
    elif "closest" in run:
        closest = run["closest"]
        report["closest"] = closest
        report["explanation"] = _explain_candidate(source, baseline, closest["candidate"], closest["qualification"])
    return cast(AllocationResult, _encode_exact(report))


def build_diagnostic_report(
    command: Literal["extract", "analyze", "allocate"], diagnostics: Sequence[Diagnostic],
) -> DiagnosticResult:
    """Frame an application failure for JSON stderr."""
    return {"kind": "diagnostic_result", "schema_version": SCHEMA_VERSION,
            "command": command, "diagnostics": [item.copy() for item in diagnostics]}


def render_json(report: AnalysisResult | AllocationResult | DiagnosticResult) -> str:
    """Return a UTF-8-ready JSON document with a final newline."""
    return json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def render_diagnostics(diagnostics: Sequence[Diagnostic]) -> str:
    """Render structured diagnostics for terminal stderr."""
    lines: list[str] = []
    for item in diagnostics:
        context = ", ".join(f"{key}={item[key]!r}" for key in ("field", "logical_id", "source_ref") if key in item)
        location = f" ({context})" if context else ""
        lines.append(f"{item['severity']} [{item['code']}]{location} {item['message']}")
        lines.append(f"  {item['recovery']}")
    return "".join(f"{line}\n" for line in lines)


def _signed(value: DecimalText) -> str:
    return f"+{value}" if Decimal(value) > 0 else value


def _margin_um(value: DecimalText) -> str:
    micrometres = Decimal(format_decimal_text(Fraction(Decimal(value)) * 1000))
    with localcontext(rounding=ROUND_HALF_EVEN):
        display = format(micrometres, ".4f")
    if micrometres and Decimal(display) == 0:
        display = format(micrometres, "f")
    return f"{_signed(display)} µm"


def _callout_text(callout: CalloutRef) -> str:
    qualifiers = ", ".join(f"{key} {callout[key]!r}" for key in ("revision", "configuration") if key in callout)
    name = f"{callout['document_id']!r} / {callout['dimension_id']!r}"
    return f"{name} ({qualifiers})" if qualifiers else name


def _deviations_text(deviations: Deviations[DecimalText]) -> str:
    return f"[{_signed(deviations['lower'])}, {_signed(deviations['upper'])}] mm"


def _evaluation_lines(title: str, evaluation: Evaluation[DecimalText]) -> list[str]:
    outcome = "PASS" if evaluation["meets_requirement"] else "FAIL"
    lines = [f"{title} | {outcome} | limiting side: {evaluation['limiting_side']}"]
    for side, bound in _SIDE_BOUNDS.items():
        trace = evaluation[bound]
        label = "Lower" if side == "minimum" else "Upper"
        lines.append(f"  {label} bound {trace['value']} mm at {trace['temperature']} °C")
        for term in trace["terms"]:
            lines.append(f"    {term['physical_id']}: {_signed(term['contribution'])} mm "
                         f"({_signed(term['coefficient'])} * {term['expanded_length']} mm, "
                         f"{term['drawing_limit']} drawing limit)")
        if side in evaluation["margins"]:
            margin = evaluation["margins"][side]
            side_status = "FAIL" if Decimal(margin) < 0 else "PASS"
            lines.append(f"    {side} margin {_margin_um(margin)} | {side_status}")
    if evaluation["drawing_limits"]:
        lines.append("  Drawing limits at reference temperature")
    for entry in evaluation["drawing_limits"]:
        limits = entry["limits"]
        lines.append(f"    {entry['physical_id']} | {_callout_text(entry['callout'])} | "
                     f"[{limits['lower']}, {limits['upper']}] mm | "
                     f"deviations {_deviations_text(limits['deviations'])} ({entry['tolerance_source']})")
    return lines


def _allocation_lines(report: AllocationResult) -> list[str]:
    search = report["search"]
    labels = {"complete": "Complete", "infeasible": "Infeasible across all declared assignments",
              "incomplete": "Incomplete search", "zero_tested": "Stopped before evaluating any assignment"}
    lines = [f"{labels[search['status']]} | evaluated {search['evaluated']} of {search['total']} | "
             f"{search['feasible']} feasible"]
    if "stop_reason" in search:
        lines.append(f"  Stop reason: {search['stop_reason'].replace('_', ' ')}")
    if "budget" in search:
        budget = search["budget"]
        limits = []
        if "max_evaluations" in budget:
            limits.append(f"{budget['max_evaluations']} evaluations")
        if "max_seconds" in budget:
            limits.append(f"{budget['max_seconds']} s")
        if limits:
            lines.append(f"  Budget: {', '.join(limits)}")
    ranking = report["ranking"]
    if "objective" in ranking:
        objective = ranking["objective"]
        lines.append(f"  Objective: minimize {objective['basis'].replace('_', ' ')} in {objective['unit']} "
                     f"| source {objective['source_ref']} | {objective['context']}")
    if ranking["status"] == "unranked":
        lines.append(f"  Ranking unavailable: {ranking['reason'].replace('_', ' ')}")
    elif ranking["best_candidate_indices"]:
        best = ranking["best_candidate_indices"]
        status = "Best evaluated" if ranking["status"] == "provisional" else "Best"
        candidates = ", ".join(f"#{index}" for index in best)
        ties = " (tie)" if len(best) > 1 else ""
        lines.append(f"  {status}: {candidates}{ties}")
    for candidate in report["feasible_candidates"]:
        evaluation = candidate["evaluation"]
        margins = ", ".join(f"{side} {_margin_um(margin)}"
                            for side, margin in cast(dict[str, DecimalText], evaluation["margins"]).items())
        score = f" | score {candidate['total_score']}" if "total_score" in candidate else ""
        lines.append(f"  Feasible #{candidate['index']} | {margins}{score}")
        by_callout = {callout_key(entry["callout"]): entry["limits"]["deviations"]
                      for entry in evaluation["drawing_limits"]}
        for option in candidate["assignment"]:
            callout = option["callout"]
            deviations = by_callout[callout_key(callout)]
            lines.append(f"    {_callout_text(callout)} -> {option['option_id']!r} | {_deviations_text(deviations)} deviations")
    return lines


def _explanation_lines(report: AllocationResult, explanation: CandidateExplanation[DecimalText]) -> list[str]:
    index = explanation["candidate_index"]
    candidate = (report["closest"]["candidate"] if "closest" in report else
                 next(item for item in report["feasible_candidates"] if item["index"] == index))
    lines = _evaluation_lines(f"{_ROLES[explanation['role']]} #{index}", candidate["evaluation"])
    if "closest" in report:
        lines.append(f"  Maximum violation {_margin_um(report['closest']['maximum_violation'])}")
    if explanation["callout_changes"]:
        lines.append("  Changed callout deviations")
    else:
        lines.append("  Drawing deviations match the baseline.")
    for change in explanation["callout_changes"]:
        lines.append(f"    {_callout_text(change['callout'])} | option {change['option_id']!r} | "
                     f"{_deviations_text(change['before'])} -> {_deviations_text(change['after'])}")
    lines.append("  Margin changes from baseline")
    side_changes = cast(dict[str, MarginChange[DecimalText]], explanation["margins"])
    for side, margin_change in side_changes.items():
        lines.append(f"    {side}: {_margin_um(margin_change['baseline_margin'])} -> "
                     f"{_margin_um(margin_change['candidate_margin'])} "
                     f"(delta {_margin_um(margin_change['margin_delta'])})")
        baseline_temp = margin_change["baseline_temperature"]
        candidate_temp = margin_change["candidate_temperature"]
        lines.append(f"      Same-temperature margin delta at {baseline_temp} °C: "
                     f"{_margin_um(margin_change['same_temperature_delta'])}")
        for term in margin_change["terms"]:
            lines.append(f"        {term['physical_id']}: {_signed(term['baseline_contribution'])} -> "
                         f"{_signed(term['candidate_contribution'])} mm signed contribution")
        lines.append(f"      Governing temperature {baseline_temp} -> {candidate_temp} °C | "
                     f"margin delta {_margin_um(margin_change['governing_temperature_delta'])}")
    return lines


def render_terminal(report: AnalysisResult | AllocationResult) -> str:
    """Render the engineering result for stdout. Diagnostics render separately."""
    requirement = report["requirement"]
    limits = ", ".join(f"{side} {requirement[side]} mm" for side in _SIDE_BOUNDS if side in requirement)
    model = report["model"]
    lines = [
        f"StackOpt | {report['case_id']} ({report['source_kind']}) | chain {report['chain_id']} | single-chain scope",
        f"Requirement {requirement['id']}: {limits}",
        f"Linear free expansion | reference {model['reference']} °C | common operating temperature "
        f"{model['operating_min']} to {model['operating_max']} °C",
        "",
        *_evaluation_lines("Baseline", report["baseline"]),
    ]
    if report["kind"] == "allocation_result":
        lines += ["", *_allocation_lines(report)]
        if "explanation" in report:
            lines += ["", *_explanation_lines(report, report["explanation"])]
    return "\n".join(lines) + "\n"
